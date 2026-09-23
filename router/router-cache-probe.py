#!/usr/bin/env python3
"""Prompt-cache probe: what prefix length actually earns the 50x cache discount?

The cloud legs bill input at $0.15/M on a cache miss and $0.003/M on a hit, so anything that
breaks prefix stability costs real money. This probe measures, per prefix length, what the
provider reports for `usage.prompt_tokens_details.cached_tokens` on a REPEATED prefix - and
whether that hit survives a leg switch (GO -> ZEN, same model id).

Prints a markdown table. Reads the key from the environment or .router-env; prints usage
metadata only, never the key.

    python router-cache-probe.py
"""
import json, os, sys, time
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(HERE, "..", ".router-env")
GO = "https://opencode.ai/zen/go/v1/chat/completions"
ZEN = "https://opencode.ai/zen/v1/chat/completions"
MODEL = "deepseek-v4.1-flash"
MISS, HIT = 0.15, 0.003          # USD per 1M input tokens, measured from the tier notes
HDRS = {"Content-Type": "application/json", "User-Agent": "OpenAI/Python",
        "Accept": "application/json", "x-opencode-session": "hermes-router"}
SIZES = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1
                          else "128,256,512,1024,2048,4096".split(","))]


def key(name):
    if os.environ.get(name):
        return os.environ[name]
    for p in (ENV, os.path.join(HERE, "..", ".env")):
        try:
            for line in open(p, encoding="utf-8", errors="ignore"):
                if line.strip().startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""


def prefix_for(n):
    """A deterministic block whose bytes never change between calls (or the cache cannot hit)."""
    unit = "block %d: routing decisions, incident notes, retrieval logs. " % n
    return (unit * (n * 4 // len(unit) + 1))[: n * 4]


def call(url, key_env, prefix, tag):
    body = json.dumps({"model": MODEL,
                       "messages": [{"role": "system", "content": "You answer in one word."},
                                    {"role": "user", "content": prefix + "\n\nReply with OK."}],
                       "max_tokens": 4, "temperature": 0}).encode()
    h = dict(HDRS)
    h["Authorization"] = "Bearer " + key(key_env)
    t0 = time.time()
    try:
        d = json.loads(urlopen(Request(url, body, h), timeout=180).read())
    except Exception as e:
        detail = ""
        try:
            detail = e.read().decode(errors="replace")[:160]
        except Exception:
            pass
        print("  %-18s ERROR %s %s" % (tag, type(e).__name__, detail))
        return None
    u = d.get("usage") or {}
    pt = int(u.get("prompt_tokens") or 0)
    ct = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
    return {"tag": tag, "s": round(time.time() - t0, 2), "prompt": pt, "cached": ct,
            "hit": (ct / pt) if pt else 0.0}


def cost(prompt, cached):
    """What the call cost on the input side, cached vs if every token had missed."""
    return ((prompt - cached) * MISS + cached * HIT) / 1e6, prompt * MISS / 1e6


def row(label, r):
    if not r:
        return "| %s | - | - | - | - | - |" % label
    with_c, without = cost(r["prompt"], r["cached"])
    ratio = ("%.1fx" % (without / with_c)) if with_c else "-"
    return "| %s | %d | %d | **%.0f%%** | $%.6f | %s |" % (
        label, r["prompt"], r["cached"], 100 * r["hit"], with_c, ratio)


print("# Prompt-cache probe - model `%s`\n" % MODEL)
print("| prefix (tokens) | cached_tokens | hit | input cost | vs uncached |")
print("|---|---:|---:|---:|---|")
rows = []
for n in SIZES:
    pre = prefix_for(n)
    a = call(GO, "OPENCODE_GO_API_KEY", pre, "go write")     # first sighting = cache write
    b = call(GO, "OPENCODE_GO_API_KEY", pre, "go repeat")    # second = the measurement
    rows.append((n, a, b))
    print(row("~%d (1st, cold)" % n, a))
    print(row("~%d (repeat)" % n, b))

print("\n## Does the hit survive a leg switch? (GO -> ZEN -> GO, same model id)\n")
print("| step | leg | prompt | cached_tokens | hit |")
print("|---|---|---:|---:|---:|")
warm = prefix_for(2048)
for leg, url, env, tag in (("GO", GO, "OPENCODE_GO_API_KEY", "warm the cache"),
                           ("ZEN", ZEN, "OPENCODE_ZEN_API_KEY", "switch leg"),
                           ("GO", GO, "OPENCODE_GO_API_KEY", "switch back")):
    r = call(url, env, warm, tag)
    if r:
        print("| %s | %s | %d | %d | **%.0f%%** |" % (tag, leg, r["prompt"], r["cached"], 100 * r["hit"]))
    else:
        print("| %s | %s | - | - | - |" % (tag, leg))
print("\nPrice basis: $%.3f/M input on a miss, $%.3f/M on a hit (the tier notes' recorded rates)." % (MISS, HIT))
