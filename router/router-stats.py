#!/usr/bin/env python3
"""Summarise a CooLRouter trace: where requests went, what they cost, how fast.

The router appends one JSON line per request to logs/router-trace.jsonl. This script
turns that file into the numbers a routing decision should be judged by - not into a
marketing table. It reads nothing else and needs no dependencies.

    python router-stats.py [trace.jsonl]

Prices are the ones recorded in ROUTER-TIERS.md for the configured cloud leg
(DeepSeek V4.1-Flash off-peak): $0.15 per 1M input tokens on a cache miss,
$0.003 per 1M on a hit. Output tokens are deliberately NOT priced here: the tier
document does not record an output rate, so any figure would be invented. Research
calls are priced as a per-call search floor ($0.005-$0.014), which is how that
provider bills - tokens are not the unit that matters there.
"""

import json
import statistics as st
import sys
from collections import Counter, defaultdict

MISS_PER_M = 0.15      # USD per 1M input tokens, cache miss
HIT_PER_M = 0.003      # USD per 1M input tokens, cache hit
SEARCH_FLOOR = (0.005, 0.014)   # USD per research call, low/high
CACHE_MIN_PROMPT = 700          # measured 2026-09-23: a 144-token prompt never hit the cache,
                                # 716 tokens hit 89% - so below this the hit rate is meaningless

CLOUD_TIERS = {"flash", "vision", "meta"}
LOCAL_TIERS = {"local"}


def load(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # a half-written final line must not kill the report
    return rows


def tokens(rows):
    p = sum(r.get("prompt_tokens") or 0 for r in rows)
    c = sum(r.get("cached_tokens") or 0 for r in rows)
    o = sum(r.get("completion_tokens") or 0 for r in rows)
    return p, c, o


def pct(values, q):
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, max(0, int(len(values) * q) - 1))]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "logs/router-trace.jsonl"
    rows = load(path)
    if not rows:
        print("no rows in %s - nothing to summarise" % path)
        return 1

    n = len(rows)
    local = [r for r in rows if r.get("tier") in LOCAL_TIERS]
    cloud = [r for r in rows if r.get("tier") in CLOUD_TIERS]
    research = [r for r in rows if r.get("tier") == "research"]

    print("CooLRouter trace summary - %s" % path)
    print("%d requests\n" % n)

    print("WHERE THEY WENT")
    for name, group in (("local", local), ("cloud", cloud), ("research", research)):
        print("  %-9s %5d  (%4.1f%%)" % (name, len(group), 100.0 * len(group) / n))
    print()

    print("TOKENS")
    for name, group in (("local", local), ("cloud", cloud), ("research", research), ("all", rows)):
        p, c, o = tokens(group)
        hit = (100.0 * c / p) if p else 0.0
        print("  %-9s prompt %7d  cached %7d  completion %7d   cache hit %4.1f%%"
              % (name, p, c, o, hit))
    print()

    pc, cc, _ = tokens(cloud)
    miss_cost = (pc - cc) * MISS_PER_M / 1e6
    hit_cost = cc * HIT_PER_M / 1e6
    print("WHAT THE CLOUD LEG COST (input side only)")
    print("  miss %d tok x $%.3f/M = $%.6f" % (pc - cc, MISS_PER_M, miss_cost))
    print("  hit  %d tok x $%.3f/M = $%.6f" % (cc, HIT_PER_M, hit_cost))
    print("  total $%.6f   (without the cache: $%.6f)" % (miss_cost + hit_cost, pc * MISS_PER_M / 1e6))
    print()

    print("PREFIX CACHE")
    cacheable = [r for r in cloud if (r.get("prompt_tokens") or 0) >= CACHE_MIN_PROMPT]
    short = [r for r in cloud if (r.get("prompt_tokens") or 0) < CACHE_MIN_PROMPT]
    if not cacheable:
        print("  no cloud request had a prompt of %d tokens or more, so none of them could be cached"
              % CACHE_MIN_PROMPT)
        print("  a 0%% hit rate here describes SHORT prompts, not broken caching. Measured on the same")
        print("  leg: 144 tok -> 0%%, 716 tok -> 89%%, 2042 tok -> 94%%, 2833 tok -> 99.4%%")
    else:
        cp = sum(r.get("prompt_tokens") or 0 for r in cacheable)
        ch = sum(r.get("cached_tokens") or 0 for r in cacheable)
        print("  cacheable requests %d of %d (%d prompt tokens, %d cached -> %.1f%% hit)"
              % (len(cacheable), len(cloud), cp, ch, 100.0 * ch / cp if cp else 0.0))
        saved = ch * (MISS_PER_M - HIT_PER_M) / 1e6
        print("  saved by the cache $%.6f; without it those tokens cost $%.6f"
              % (saved, cp * MISS_PER_M / 1e6))
        if ch:
            ratio = (cp * MISS_PER_M) / (ch * HIT_PER_M + (cp - ch) * MISS_PER_M)
            print("  input is %.1fx cheaper than sending the same prefix uncached" % ratio)
    print("  %d requests were too short to cache (%d prompt tokens); the cache only pays off on a"
          % (len(short), sum(r.get("prompt_tokens") or 0 for r in short)))
    print("  repeated prefix, which is what an agent session has and a one-shot prompt does not")
    print()

    pl, _, _ = tokens(local)
    print("WHAT STAYING LOCAL AVOIDED")
    print("  %d requests, %d prompt tokens -> $%.6f at the miss rate; actual spend $0"
          % (len(local), pl, pl * MISS_PER_M / 1e6))
    if research:
        print("  %d research calls x $%.3f-%.3f search floor = $%.4f - $%.4f  <-- per-call floor, not tokens"
              % (len(research), SEARCH_FLOOR[0], SEARCH_FLOOR[1],
                 len(research) * SEARCH_FLOOR[0], len(research) * SEARCH_FLOOR[1]))
    print()

    print("SPEED (ms_total, measured)")
    by_model = defaultdict(list)
    for r in rows:
        if r.get("model"):
            by_model[r["model"]].append(r.get("ms_total") or 0)
    for model, values in sorted(by_model.items(), key=lambda kv: -len(kv[1])):
        print("  %-46s n=%-4d median %7.0f  p90 %7.0f" % (model[:46], len(values), st.median(values), pct(values, 0.9)))
    print()

    print("RELIABILITY")
    legs = Counter(r.get("leg") for r in rows if r.get("tier") in CLOUD_TIERS | {"vision"})
    print("  cloud legs: %s  (a non-primary leg means a fallback fired)"
          % ", ".join("%s=%d" % (k, v) for k, v in legs.most_common()))
    print("  empty completions: %d" % sum(1 for r in rows if (r.get("completion_tokens") or 0) == 0))
    print("  privacy-forced local: %d" % sum(1 for r in rows if r.get("forced_local")))
    cls = [r.get("classify_ms") or 0 for r in rows]
    print("  classifier median: %.0f ms" % st.median(cls))
    print("  sources: %s" % ", ".join("%s=%d" % kv for kv in Counter(r.get("source") for r in rows).most_common(4)))
    print()
    print("Read this as a description of the traffic in the file. A trace full of test")
    print("requests describes the router, not a production workload.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
