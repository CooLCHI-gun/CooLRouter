#!/usr/bin/env python3
"""router-arena.py — is tier routing actually worth it? Measure, don't assume.

Method (borrowed from HarnessRouter's arena, minus the marketing):
  1. GATE ON SUCCESS FIRST. A cheap failure is not a bargain, so success is a constraint and
     cost/latency are only compared among the configurations that pass.
  2. Same task, same input, every tier, N runs each.
  3. Report cost per SUCCESSFUL task and p95 latency — not averages of everything.
  4. Report the counterfactual: what the same workload would cost if it all ran on one tier.
  5. Report notional cost (list price) AND marginal cash (a GO subscription leg bills $0).

Usage
    ./venv-router/Scripts/python.exe scripts/router-arena.py                 # local + flash, 3 runs
    ...  --tiers local,flash,research --runs 5 --tasks 8    # research costs real money
    ...  --out logs/arena.json
"""
import argparse
import json
import os
import re
import statistics as st
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTER = "http://127.0.0.1:8000/v1/chat/completions"

# List prices per 1M tokens (DeepSeek V4.1-Flash off-peak; peak doubles). `marginal` = what actually
# bills: a monthly-subscription leg (GO) is $0 marginal, the metered leg (ZEN) is priced, and
# Perplexity adds a per-request search-context floor (measured $0.006).
PRICES = {
    "gemma3:4b":                      {"in_miss": 0.0,  "in_hit": 0.0,   "out": 0.0,  "marginal": 0.0},
    "deepseek-v4.1-flash":            {"in_miss": 0.15, "in_hit": 0.003, "out": 0.60,
                                       "marginal_if": {"go": 0.0, "zen": None}},
    "deepseek-v4-flash-vision-exp":   {"in_miss": 0.15, "in_hit": 0.003, "out": 0.60,
                                       "marginal_if": {"go": 0.0, "zen": None}},
    "sonar-pro":                      {"in_miss": 1.0,  "in_hit": 1.0,   "out": 1.0,
                                       "request_floor": 0.006, "marginal": None},
    "sonar-reasoning-pro":            {"in_miss": 2.0,  "in_hit": 2.0,   "out": 8.0,
                                       "request_floor": 0.006, "marginal": None},
}

# Real tasks from this profile's actual work, with a deterministic success check wherever one
# exists. `expect` is a regex the answer must match (case-insensitive); `min_chars` is a floor.
FIXTURES = [
    {"id": "trivial-ok",       "expect": r"^\s*ok\s*[.!]?\s*$",
     "prompt": "Reply with exactly one word: OK"},
    {"id": "explain-short",    "expect": r"you aren'?t gonna need it|yagni",
     "prompt": "用一句話解釋咩係 YAGNI"},
    {"id": "fact-population",  "expect": r"75[0-9]|74[0-9]",
     "prompt": "香港人口大約幾多？"},
    {"id": "fact-evergrande",  "expect": r"2024",
     "prompt": "恒大係喺邊一年被香港法院頒令清盤？"},
    {"id": "code-ffmpeg",      "expect": r"ffmpeg",
     "prompt": "幫我寫一個 python script 用 ffmpeg 抽音軌轉 16k wav"},
    {"id": "code-bcrypt",      "expect": r"bcrypt",
     "prompt": "write a python function that hashes a password with bcrypt"},
    {"id": "json-shape",       "expect": r"\{[^}]*\"title\"",
     "prompt": "Return ONLY a JSON object with keys title and year for the film Inception"},
    {"id": "math-exact",       "expect": r"\b1[0-9]{3}\b",
     "prompt": "一個 batch 有 43 個 item，要做 37 個 batch，總共幾多個 item？只答數字"},
    {"id": "translate",        "expect": r"receipt",
     "prompt": "Translate to English, one word only: 收據"},
    {"id": "summarise",        "expect": None, "min_chars": 120,
     "prompt": "用三點總結 prompt caching 對成本嘅影響（每點一句）"},
]


def call(tier, prompt, timeout=180):
    body = json.dumps({"messages": [{"role": "user", "content": prompt}], "tier": tier}).encode()
    req = urllib.request.Request(ROUTER, body, {"Content-Type": "application/json"})
    t0 = time.time()
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "ms": (time.time() - t0) * 1000}
    ms = (time.time() - t0) * 1000
    content = ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
    return {"ok": True, "content": content, "ms": ms, "leg": d.get("x-leg"),
            "route": d.get("x-route"), "model": d.get("model"),
            "usage": d.get("usage") or {}, "total_ms": d.get("x-ms-total")}


def cost_of(model, leg, usage):
    """-> (notional_usd, marginal_usd). Marginal = what actually leaves the wallet today."""
    p = PRICES.get(model)
    if not p:
        return None, None
    det = (usage.get("prompt_tokens_details") or {})
    pt = usage.get("prompt_tokens") or 0
    hit = det.get("cached_tokens") or 0
    miss = max(pt - hit, 0)
    ct = usage.get("completion_tokens") or 0
    notional = (miss * p["in_miss"] + hit * p["in_hit"] + ct * p["out"]) / 1e6 + p.get("request_floor", 0.0)
    if "marginal_if" in p:
        m = p["marginal_if"].get(leg or "")
        marg = None if m is None else notional if m is None else m + (0 if m == 0 else notional)
        marg = 0.0 if m == 0.0 else (notional if m is None else notional)
    else:
        marg = notional if p.get("marginal") is None else p["marginal"]
    return notional, marg


def scored(fx, res):
    if not res.get("ok"):
        return False
    c = res.get("content") or ""
    if fx.get("min_chars") and len(c) < fx["min_chars"]:
        return False
    if fx.get("expect") and not re.search(fx["expect"], c, re.I | re.S):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="local,flash")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--tasks", type=int, default=len(FIXTURES))
    ap.add_argument("--only", default=None,
                    help="comma-separated fixture ids — use it so a PAID tier is only swept on the "
                         "tasks that could plausibly need it (a research call costs a $0.006 floor)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    tiers = [t.strip() for t in a.tiers.split(",") if t.strip()]
    fixtures = FIXTURES[:a.tasks]
    if a.only:
        want = {s.strip() for s in a.only.split(",")}
        fixtures = [f for f in FIXTURES if f["id"] in want]

    print(f"tiers={tiers} runs={a.runs} tasks={len(fixtures)} "
          f"({len(tiers) * a.runs * len(fixtures)} calls)\n")
    rows = []
    for fx in fixtures:
        for tier in tiers:
            for run in range(a.runs):
                r = call(tier, fx["prompt"])
                ok = scored(fx, r)
                notional, marg = cost_of(r.get("model", ""), r.get("leg"), r.get("usage") or {})
                rows.append({"task": fx["id"], "tier": tier, "run": run, "pass": ok,
                             "ms": round(r.get("total_ms") or r.get("ms") or 0, 1),
                             "model": r.get("model"), "leg": r.get("leg"),
                             "notional_usd": notional, "marginal_usd": marg,
                             "usage": r.get("usage"), "err": r.get("error")})
                flag = "PASS" if ok else "FAIL"
                print(f"  {fx['id']:16s} {tier:9s} run{run} {flag} {rows[-1]['ms']:8.0f}ms "
                      f"leg={r.get('leg')} ${notional if notional is None else round(notional, 6)}")

    # ── report ──
    print("\n" + "=" * 78)
    print(f"{'tier':10s} {'n':>3s} {'success':>8s} {'$/success':>11s} {'marg$':>10s} {'p95 ms':>8s} {'med ms':>8s} {'$/task':>10s}")
    summary = {}
    for tier in tiers:
        rs = [r for r in rows if r["tier"] == tier]
        npass = sum(1 for r in rs if r["pass"])
        cs = [r["notional_usd"] for r in rs if r["pass"] and r["notional_usd"] is not None]
        ms = sorted(r["ms"] for r in rs)
        p95 = ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))] if ms else 0
        per_success = (sum(cs) / npass) if npass and cs else None
        tot = [r["notional_usd"] for r in rs if r["notional_usd"] is not None]
        marg = [r["marginal_usd"] for r in rs if r["pass"] and r["marginal_usd"] is not None]
        marg_success = (sum(marg) / npass) if npass and marg else 0.0
        med = st.median(ms) if ms else 0
        summary[tier] = {"n": len(rs), "pass": npass, "success_rate": round(npass / max(len(rs), 1), 3),
                         "usd_per_success": per_success, "usd_marginal_per_success": marg_success,
                         "p95_ms": p95, "median_ms": med,
                         "usd_per_task": (sum(tot) / len(tot)) if tot else None}
        print(f"{tier:10s} {len(rs):3d} {npass/len(rs):8.0%} "
              f"{'-' if per_success is None else round(per_success, 6):>11} "
              f"{round(marg_success, 6):>10} {p95:8.0f} {med:8.0f} "
              f"{'-' if not tot else round(sum(tot)/len(tot), 6):>10}")

    if len(tiers) > 1 and all(summary[t]["usd_per_success"] for t in tiers):
        base = tiers[-1]
        cheap = min(tiers, key=lambda t: summary[t]["usd_per_success"])
        b, c = summary[base], summary[cheap]
        if c["usd_per_success"]:
            print(f"\nCounterfactual: everything on '{base}' costs "
                  f"${b['usd_per_success']:.6f}/success at {b['success_rate']:.0%} success; "
                  f"'{cheap}' costs ${c['usd_per_success']:.6f}/success at {c['success_rate']:.0%}.")
            print(f"  saving per successful task: "
                  f"{(1 - c['usd_per_success'] / b['usd_per_success']) * 100:.1f}% "
                  f"(quality delta {c['success_rate'] - b['success_rate']:+.0%})")
    print("\nNote: notional = list price (apples-to-apples). Marginal = cash actually billed today: "
          "a GO subscription leg is $0, ZEN is metered, Perplexity adds a $0.006 request floor.")
    out = a.out or os.path.join(ROOT, "logs", f"arena-{time.strftime('%Y%m%d-%H%M%S')}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"when": time.strftime("%Y-%m-%dT%H:%M:%S"), "tiers": tiers, "runs": a.runs,
                   "summary": summary, "rows": rows}, f, ensure_ascii=False, indent=1)
    print("written:", out)


if __name__ == "__main__":
    main()
