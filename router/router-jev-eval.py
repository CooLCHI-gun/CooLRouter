#!/usr/bin/env python3
"""Jev vs the live router: does a typed-decision model route better?

For 9 real queries (with the tier the router actually chose), ask Jev ONE choice
question (tier) plus two Noul questions (needs world knowledge / needs citations).
Prints agreement, latency and exact cost. Reads OPENROUTER_API_KEY from .env.
"""
import json, os, time
from urllib.request import Request, urlopen

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

def key(name):
    if os.environ.get(name):
        return os.environ[name]
    for p in (os.path.join(ROOT, "scripts", ".router-env"), os.path.join(ROOT, ".env")):
        try:
            for line in open(p, encoding="utf-8", errors="ignore"):
                if line.strip().startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""

K = key("OPENROUTER_API_KEY")
if not K:
    raise SystemExit("no OPENROUTER_API_KEY")

# (query, what the live router actually did today)
CASES = [
    ("say OK", "local"),
    ("用一句話解釋咩係 YAGNI", "local"),
    ("香港人口大約幾多？", "flash"),
    ("恒大係咪2024年1月被香港法院頒令清盤？fact check", "research"),
    ("幫我寫個 python script 用 ffmpeg 抽音軌轉 16k wav", "flash"),
    ("呢張圖入面有咩文字？describe the image", "vision"),
    ("route this query to the right tier", "meta"),
    ("write a python script to hash passwords with bcrypt", "flash"),
    ("解釋一下 LLM serving 裡面嘅 tokens 用量同 latency 有咩關係", "flash/meta"),
]

def decide(state):
    body = {"model": "typesafe/jev-1.13", "state": state, "questions": {
        "tier": {"type": "choice", "instructions": "呢個請求應該交俾邊個 tier 處理？",
                 "criteria": {
                     "local": "極簡單、常識、格式化、改寫、本地或私密資料、唔需要世界知識",
                     "flash": "一般寫程式、解釋、寫作、翻譯、需要一定知識或推理",
                     "research": "需要即時資料、出處、事實核實、多來源比較",
                     "vision": "要睇圖／OCR／圖表",
                 }},
        "needs_world_knowledge": {"type": "noul",
                 "instructions": "答呢條問題係咪需要準確嘅現實世界事實（數字、年份、人物、價格）？"},
        "needs_citations": {"type": "noul",
                 "instructions": "用戶係咪要求出處、核實或最新資料？"},
    }}
    req = Request("https://openrouter.ai/api/alpha/decisions", json.dumps(body).encode(),
                  {"Content-Type": "application/json", "Authorization": "Bearer " + K})
    t0 = time.time()
    d = json.loads(urlopen(req, timeout=60).read())
    dt = round(time.time() - t0, 2)
    a = d.get("answers", {})
    return (a.get("tier", {}).get("choice"), a.get("tier", {}).get("confidence"),
            a.get("needs_world_knowledge", {}).get("noul"), a.get("needs_citations", {}).get("noul"),
            dt, (d.get("usage") or {}).get("cost"))

tot = 0.0
for q, actual in CASES:
    try:
        tier, conf, wkn, cite, dt, cost = decide(q)
        tot += cost or 0
        agg = "AGREE" if (tier or "") in actual else "DIFF "
        print(f"{agg} | jev={tier:9s} conf={conf if conf is None else round(conf,2)} "
              f"| world_knowledge={wkn if wkn is None else round(wkn,2)} citations={cite if cite is None else round(cite,2)} "
              f"| {dt}s ${cost} | router={actual:12s} | {q[:42]}")
    except Exception as e:
        print(f"ERR {type(e).__name__}: {e} | {q[:40]}")
print(f"\nTOTAL Jev cost for {len(CASES)} queries: ${tot:.6f}")
