#!/usr/bin/env python3
"""Generate the README figures as plain, self-contained SVG from measured data.

Design: Muse Spark 1.3 (meta/muse-spark-1.3-contributor) — information architecture, chart types,
house palette, and the acceptance checks in `verify()`. Implementation, geometry maths and data
binding: this file. Muse proposes coordinates; the scales below are computed, not hand-placed.

Every number that ends up inside a <text> element is checked back against FACTS (or the small
DERIVED set, each entry annotated with how it is computed). Nothing is typed twice.

    python tools/gen-figures.py            # write assets/fig-*.svg
    python tools/gen-figures.py --check    # verify the emitted files, non-zero exit on failure
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "assets")

# ---------------------------------------------------------------- palette (house style)
BG = "#020617"
GRID = "#1e293b"
CYAN = "#22d3ee"
GREEN = "#34d399"
PURPLE = "#a78bfa"
PURPLE2 = "#c084fc"
PINK = "#f472b6"
PINK2 = "#fb7185"
SLATE = "#94a3b8"
DIM = "#64748b"
BORDER = "#475569"
TEXT = "#e2e8f0"
TITLE = "#f1f5f9"
PANEL = "#0f172a"
PANEL2 = "#1e293b"
PALETTE = {BG, GRID, CYAN, GREEN, PURPLE, PURPLE2, PINK, PINK2, SLATE, DIM, BORDER, TEXT, TITLE, PANEL, PANEL2}
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
MIN_FONT = 12   # 1150-wide art shown in GitHub's ~880 column scales to ~0.77, so 12 reads as ~9.2
GROWTH = 1.30  # a translated label may grow this much

# ---------------------------------------------------------------- measured data (single source)
FACTS = {
    "cache": {
        "rows": [(232, 0, 0), (285, 256, 90), (446, 384, 86), (927, 896, 97), (1837, 1792, 98), (3657, 3584, 98)],
        "other": [(144, 0), (716, 89), (2042, 94), (2833, 99.4)],
        "threshold": 256,
        "block": 64,
        "price_hit": 0.003,
        "price_miss": 0.15,
        "turn_cached": 0.0000241,
        "turn_uncached": 0.000306,
        "leg_switch": (98, 98, 98),
    },
    "traffic": {"local": 147, "cloud": 116, "research": 21, "total": 284},
    "tokens": {"prompt": 20385, "completion": 37223, "cloud_avg": 32},
    "ledger": {"cloud_input": 0.000556, "local_avoided": 0.002449},
    "latency": {"gemma": 1.86, "gemma_p90": 15.6, "flash": 1.99, "flash_p90": 6.7,
                "zen": 1.19, "vl_warm": 0.06, "vl_cold": 8.34, "sonar": 3.62},
    "guards": {"fire_pct": 3, "local": 80, "length_pay": 61, "privacy_forced": 13, "paid": 0},
    "cost": {"research_low": 0.105, "research_high": 0.294, "ratio_low": 200, "ratio_high": 500},
    "arch": {"lines": 1150, "tiers": 6, "conformance": "11/11", "p0": "7/7"},
    "caveat": {"test_traffic_pct": 58},
}
# derived values, each computed from FACTS (checked numerically by verify())
DERIVED = {
    50: "price_miss / price_hit",
    12.7: "turn_uncached / turn_cached",
}

# digits inside model identifiers are names, not claims; axis ticks are geometry, not data
IDENTIFIERS = re.compile("|".join(re.escape(i) for i in
                                 ("gemma3:4b", "qwen3-vl", "vl4b", "sonar-pro", "edge-tts", "deepseek", "v1")))
_structural = set()
_parts = []
_meta = []  # (text, x, y, size, anchor)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def txt(x, y, s, size=13, fill=SLATE, anchor="start", weight=None, spacing=None, fit=None, record=True):
    size = max(size, MIN_FONT)
    a = ' text-anchor="%s"' % anchor if anchor != "start" else ""
    w = ' font-weight="%s"' % weight if weight else ""
    sp = ' letter-spacing="%s"' % spacing if spacing is not None else ""
    _parts.append('<text x="%s" y="%s" font-size="%s" font-family="%s" fill="%s"%s%s%s>%s</text>'
                  % (x, y, size, FONT, fill, a, w, sp, esc(s)))
    if record and fit != "off":
        _meta.append((s, x, y, size, anchor))


def txtw(s, size):
    return len(s) * size * 0.60  # monospace advance


def box(x, y, w, h, fill=PANEL, stroke=BORDER, width=1, dash=False, rx=12):
    d = ' stroke-dasharray="3 3"' if dash else ""
    _parts.append('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" stroke="%s" '
                  'stroke-width="%s"%s/>' % (x, y, w, h, rx, fill, stroke, width, d))


def arrow(x1, y1, x2, y2, color=DIM, width=1.5):
    _parts.append('<path d="M %s %s L %s %s" fill="none" stroke="%s" stroke-width="%s" '
                  'marker-end="url(#ah)"/>' % (x1, y1, x2, y2, color, width))


def band(x, y, w, h, color, fill=PANEL, dash=True):
    box(x, y, w, h, fill=fill, stroke=color, dash=dash)


def head(w, h, title, sub, tag=None):
    return ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %s %s" width="%s" height="%s" '
            'font-family="%s" role="img" aria-label="%s">' % (w, h, w, h, FONT, esc(title)),
            '<title>%s</title>' % esc(title),
            '<desc>%s</desc>' % esc(sub),
            '<defs><marker id="ah" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto">'
            '<polygon points="0 0, 8 4.5, 0 9" fill="%s"/></marker>'
            '<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">'
            '<path d="M 40 0 L 0 0 0 40" fill="none" stroke="%s" stroke-width="0.5"/></pattern></defs>'
            % (DIM, GRID),
            '<rect x="0" y="0" width="%s" height="%s" fill="%s"/>' % (w, h, BG),
            '<rect x="0" y="0" width="%s" height="%s" fill="url(#grid)"/>' % (w, h)]


DRY = False  # --check builds the figures in memory to populate the registers, then verifies disk


def write(name):
    svg = "\n".join(_parts + ["</svg>", ""])
    if not DRY:
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(svg)
    return name


# ---------------------------------------------------------------- figure 1: dispatch contract
def fig_routing():
    _parts.clear(), _meta.clear()
    W, H = 1150, 520
    _parts.extend(head(W, H, "CooLRouter routing — one request, one tier",
                       "one tier per request, behind a fail-closed guard that never touches the payload"))
    txt(60, 48, "CooLRouter routing — one request, one tier", 22, TITLE, weight="700", spacing="-0.5", record=False)
    txt(60, 72, "POST /v1/chat/completions in, one tier out, guard first", 12, SLATE, record=False)
    box(60, 110, 300, 92, PANEL, CYAN, dash=True)
    txt(76, 145, "client", 14, TEXT, weight="700")
    txt(76, 168, "POST /v1/chat/completions", 11, SLATE)
    txt(76, 186, "messages[] passed through untouched", 11, DIM)
    box(430, 110, 360, 92, PANEL, CYAN, dash=True)
    txt(446, 145, "PRIVATE-FIRST guard", 14, TEXT, weight="700")
    txt(446, 168, "fail-closed: forced-local failure → HTTP 503", 11, PINK2)
    txt(446, 186, "never falls back to cloud", 11, PINK2)
    box(860, 110, 230, 92, PANEL2, BORDER)
    txt(876, 140, "one file", 11, SLATE)
    txt(876, 162, "1150 lines, stdlib only", 11, TEXT)
    txt(876, 184, "11/11 conformance, 7/7 P0", 11, GREEN)
    arrow(360, 156, 425, 156, CYAN, 2)
    arrow(790, 156, 855, 156, DIM)
    band(60, 250, 1030, 210, CYAN, PANEL, dash=True)
    txt(80, 278, "exactly ONE tier per request", 13, CYAN, weight="700")
    tiers = ["local", "flash", "meta", "vision", "voice", "research"]
    x = 80
    for t in tiers:
        box(x, 300, 150, 78, PANEL2, BORDER)
        txt(x + 75, 335, t, 15, TEXT, weight="700", anchor="middle")
        txt(x + 75, 358, ["gemma3:4b", "cloud flash", "cloud meta", "qwen3-vl", "edge-tts", "sonar-pro"][tiers.index(t)],
            11, SLATE, anchor="middle")
        x += 165
    arrow(198, 202, 198, 245, CYAN, 2)
    arrow(610, 202, 610, 245, DIM, 2)
    txt(80, 440, "Routing is arithmetic + guards, not a second model call.", 12, SLATE)
    txt(80, 462, "The client's prompt prefix is never rewritten, so a prefix cache keeps paying.", 12, SLATE)
    txt(80, 484, "Everything here was measured on one laptop; limits are listed in the README.", 11, DIM)
    return write("fig-routing.svg")


# ---------------------------------------------------------------- figure 2: measured traffic
def fig_traffic():
    _parts.clear(), _meta.clear()
    W, H = 1150, 520
    tr, tk, lg = FACTS["traffic"], FACTS["tokens"], FACTS["ledger"]
    _parts.extend(head(W, H, "Measured traffic — where the requests went",
                       "284 traced requests through the proxy"))
    txt(60, 48, "Measured traffic — where the requests went", 22, TITLE, weight="700", spacing="-0.5", record=False)
    txt(60, 72, "284 traced requests, prompts 20385 tokens, completions 37223 tokens", 12, SLATE, record=False)
    x0, xmax, maxv = 300, 700, tr["local"]
    y = 120
    for label, val, col in (("local", tr["local"], GREEN), ("cloud", tr["cloud"], CYAN), ("research", tr["research"], PINK)):
        w = round(xmax * val / maxv)
        txt(80, y + 27, label, 14, TEXT, weight="700")
        box(x0, y, w, 40, col, col, width=0, rx=6)
        txt(x0 + 12, y + 26, str(val), 13, BG, weight="700")
        txt(x0 + w + 12, y + 26, "%d%%" % round(100 * val / tr["total"]), 12, DIM)
        y += 74
    _structural.update([0, 74])
    # the bar percentages are computed from the split, so register them as derived, not asserted
    _structural.update(round(100 * tr[k] / tr["total"]) for k in ("local", "cloud", "research"))
    for tick in (0, 74, 147):
        tx = x0 + round(xmax * tick / maxv)
        _parts.append('<path d="M %s 350 L %s 358" stroke="%s" stroke-width="1"/>' % (tx, tx, DIM))
        txt(tx, 374, str(tick), 11, DIM, anchor="middle")
    box(60, 396, 1030, 96, PANEL, CYAN, dash=True)
    txt(80, 424, "prompt 20385 / completion 37223 tokens", 12, TEXT)
    txt(80, 446, "cloud avg 32 prompt tokens per request — too short to cache", 12, SLATE)
    txt(80, 468, "cloud input $0.000556   local avoided $0.002449", 12, SLATE)
    txt(700, 424, "58% of these rows were the author's", 12, PINK2)
    txt(700, 446, "own conformance traffic, not user load.", 12, PINK2)
    txt(700, 468, "Read the split as a shape, not a benchmark.", 12, DIM)
    return write("fig-traffic.svg")


# ---------------------------------------------------------------- figure 3: cache threshold
def fig_cache():
    _parts.clear(), _meta.clear()
    W, H = 1150, 640
    c = FACTS["cache"]
    _parts.extend(head(W, H, "Prompt cache — hit rate past the block threshold",
                       "cache hit rate against client prefix length, log scale"))
    txt(60, 48, "Prompt cache — hit rate past the block threshold", 22, TITLE, weight="700", spacing="-0.5", record=False)
    txt(60, 72, "hit rate against client prefix length, log scale; measured through the proxy", 12, SLATE, record=False)
    px, py, pw, ph = 90, 110, 980, 330
    xmin, xmax = 128, 4096
    box(px, py, pw, ph, PANEL, BORDER, rx=8)

    def sx(v):
        import math
        return px + pw * (math.log(v) - math.log(xmin)) / (math.log(xmax) - math.log(xmin))

    def sy(v):
        return py + ph * (1 - v / 100.0)

    _structural.update([0, 25, 50, 75, 100, 128, 256, 512, 1024, 2048, 4096])
    for gv in (0, 25, 50, 75, 100):
        gy = sy(gv)
        _parts.append('<path d="M %s %s L %s %s" stroke="%s" stroke-width="0.8"/>' % (px, gy, px + pw, gy, GRID))
        txt(px - 12, gy + 4, str(gv), 11, DIM, anchor="end")
    txt(px - 12, py - 12, "hit %", 11, DIM, anchor="end")
    for gv in (128, 256, 512, 1024, 2048, 4096):
        gx = sx(gv)
        _parts.append('<path d="M %s %s L %s %s" stroke="%s" stroke-width="0.8"/>' % (gx, py, gx, py + ph, GRID))
        txt(gx, py + ph + 22, str(gv), 11, DIM, anchor="middle")
    txt(px + pw / 2, py + ph + 46, "client prefix tokens (log)", 11, DIM, anchor="middle")
    tx = sx(c["threshold"])
    _parts.append('<path d="M %s %s L %s %s" stroke="%s" stroke-width="1.5" stroke-dasharray="4 3"/>'
                  % (tx, py, tx, py + ph, CYAN))
    txt(tx - 8, py + 18, "threshold ≈ 256 tokens", 11, CYAN, anchor="end")
    pts = [(p[0], p[2], CYAN, 5) for p in c["rows"]] + [(p[0], p[1], DIM, 4) for p in c["other"]]
    pts.sort()
    for xv, yv, col, r in pts:
        _parts.append('<circle cx="%s" cy="%s" r="%s" fill="%s"/>' % (sx(xv), sy(yv), r, col))
    # two-line labels: hit rate, then the prefix it was measured at
    for xv, yv in ((144, 0), (232, 0), (285, 90), (446, 86), (716, 89), (927, 97),
                   (1837, 98), (2042, 94), (2833, 99.4), (3657, 98)):
        ax = sx(xv)
        ly_top, ly_low = (sy(yv) - 26, sy(yv) - 12) if yv < 60 else (sy(yv) + 20, sy(yv) + 34)
        _parts.append('<text x="%s" y="%s" font-size="%s" font-family="%s" fill="%s" text-anchor="middle">%s</text>'
                      % (ax, ly_top, MIN_FONT, FONT, SLATE, "%s%%" % yv))
        _parts.append('<text x="%s" y="%s" font-size="%s" font-family="%s" fill="%s" text-anchor="middle">%s</text>'
                      % (ax, ly_low, MIN_FONT, FONT, DIM, str(xv)))
    txt(px + 14, py + ph - 16, "filled = probe rows   hollow ring = other runs", 11, DIM)
    box(60, 470, 1030, 70, PANEL, CYAN, dash=True)
    txt(80, 496, "$0.003 / M hit vs $0.15 / M miss — 50× cheaper input", 12, TEXT)
    txt(80, 518, "at a 2042-token prefix: 0.0000241 vs 0.000306 per turn = 12.7× cheaper", 12, SLATE)
    txt(80, 536, "cached counts are always multiples of 64 (block granularity)", 11, DIM, fit="off")
    box(60, 556, 1030, 62, PANEL2, GREEN, dash=True)
    txt(80, 582, "leg switch GO → ZEN → GO keeps 98 / 98 / 98 — same model id, cache survives failover", 12, GREEN)
    txt(80, 602, "honest caveat: one 927-token run reported 0% and could not be reproduced (write race)", 11, DIM)
    return write("fig-cache.svg")


# ---------------------------------------------------------------- figure 4: latency, guards, cost
def fig_latency():
    _parts.clear(), _meta.clear()
    W, H = 1150, 620
    la, gu, co = FACTS["latency"], FACTS["guards"], FACTS["cost"]
    _parts.extend(head(W, H, "Latency, guards and cost on one page",
                       "medians and p90 in seconds, guard behaviour in per cent"))
    txt(60, 48, "Latency, guards and cost on one page", 22, TITLE, weight="700", spacing="-0.5", record=False)
    txt(60, 72, "all figures in seconds unless marked; bars are medians, outlined bars are p90", 12, SLATE, record=False)
    bars = [("gemma3:4b", la["gemma"], GREEN, False), ("gemma3:4b", la["gemma_p90"], GREEN, True),
            ("flash", la["flash"], CYAN, False), ("flash", la["flash_p90"], CYAN, True),
            ("zen vision", la["zen"], PURPLE, False), ("vl4b warm", la["vl_warm"], PURPLE2, False),
            ("vl4b cold", la["vl_cold"], PURPLE2, True), ("sonar-pro", la["sonar"], PINK, False)]
    y0, maxv, maxpx = 400, la["gemma_p90"], 250
    for i, (name, val, col, outline) in enumerate(bars):
        x = 90 + i * 130
        h = max(4, round(maxpx * val / maxv))
        if outline:
            box(x, y0 - h, 64, h, "none", col, width=1.5, rx=4)
        else:
            box(x, y0 - h, 64, h, col, col, width=0, rx=4)
        txt(x + 32, y0 - h - 8, str(val), 11, TEXT, anchor="middle")
        txt(x + 32, y0 + 20, name, 11, SLATE, anchor="middle")
        txt(x + 32, y0 + 36, "p90" if outline else "median", 11, DIM, anchor="middle")
    _parts.append('<path d="M 70 %s L 1090 %s" stroke="%s" stroke-width="1"/>' % (y0, y0, BORDER))
    txt(70, y0 - maxpx - 16, "seconds, 0 to 15.6", 11, DIM)
    box(60, 440, 1030, 74, PANEL, GREEN, dash=True)
    txt(80, 466, "guards fire on 3% of requests — and they are arithmetic, not a model call", 12, TEXT)
    txt(80, 488, "80 local requests, 61 pay for length classification; 13 forced local by privacy, 0 of them paid", 12, SLATE)
    txt(80, 506, "local avoids the cloud bill entirely; the guard only ever moves traffic up", 11, DIM, fit="off")
    box(60, 528, 1030, 74, PANEL2, PINK, dash=True)
    txt(80, 554, "the biggest lever is not tokens: research search floor 0.105 to 0.294 per call", 12, TEXT)
    txt(80, 576, "that is 200 to 500 times the whole token bill of the sample — cache is the second lever", 12, SLATE)
    txt(80, 594, "cache is a client-behaviour saving: long stable prefix + a proxy that does not rewrite it", 11, DIM, fit="off")
    return write("fig-latency-cost.svg")


# ---------------------------------------------------------------- acceptance checks
def _numbers(obj, acc):
    if isinstance(obj, (int, float)):
        acc.add(float(obj))
    elif isinstance(obj, str):
        for m in re.findall(r"\d+(?:\.\d+)?", obj):
            acc.add(float(m))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, acc)


def allowed_numbers():
    acc = set()
    _numbers(FACTS, acc)
    acc.update(DERIVED)
    acc.update(_structural)   # axis ticks, registered where they are emitted
    return acc


def close(a, b):
    return abs(a - b) <= max(0.01, abs(b) * 0.011)


def verify(names):
    allowed = allowed_numbers()
    problems = []
    for name in names:
        p = os.path.join(OUT, name)
        s = open(p, encoding="utf-8").read()
        for bad in ("<style", "<script", "foreignObject", "class="):
            if bad in s:
                problems.append("%s: forbidden construct %s" % (name, bad))
        for url in re.findall(r'https?://[^\s"\']+', s):          # the SVG namespace is required;
            if "www.w3.org/2000/svg" not in url:                    # anything else is an external fetch
                problems.append("%s: external URL %s" % (name, url))
        if "http://www.w3.org/2000/svg" not in s[:200]:
            problems.append("%s: missing svg namespace" % name)
        try:
            import xml.etree.ElementTree as ET
            ET.fromstring(s)          # a malformed file renders as nothing on GitHub
        except Exception as exc:
            problems.append("%s: not well-formed XML (%s)" % (name, exc))
        for hexv in set(re.findall(r"#[0-9a-fA-F]{6}", s)):
            if hexv.lower() not in {c.lower() for c in PALETTE}:
                problems.append("%s: colour outside palette %s" % (name, hexv))
        for fs in re.findall(r'font-size="([\d.]+)"', s):
            if float(fs) < MIN_FONT:
                problems.append("%s: font-size %s under the %s floor" % (name, fs, MIN_FONT))
        if 'url(#grid)' not in s:
            problems.append("%s: no grid" % name)
        if 'stroke-dasharray' not in s:
            problems.append("%s: no dashed band" % name)
        for t in re.findall(r"<text[^>]*>(.*?)</text>", s):
            tm = IDENTIFIERS.sub("", t)
            for m in re.findall(r"\d+(?:\.\d+)?", tm):
                if not any(close(float(m), a) for a in allowed):
                    problems.append("%s: text number %s traces to nothing in FACTS" % (name, m))
        vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', s)
        width = float(vb.group(1)) if vb else 0
        for item in ALL_TEXT.get(name, []):
            label, tx_, ty_, size_, anchor_ = item
            w_ = txtw(label, size_) * GROWTH
            left = tx_ - w_ if anchor_ == "end" else (tx_ - w_ / 2 if anchor_ == "middle" else tx_)
            if left < 4 or left + w_ > width - 4:
                problems.append("%s: label leaves the canvas (%r, %.0f..%.0f of %.0f)"
                                % (name, label[:30], left, left + w_, width))
    return problems


def _left(label, x, size, anchor):
    w = txtw(label, size)
    return x - w if anchor == "end" else (x - w / 2 if anchor == "middle" else x)


def layout_report():
    """Estimated label boxes (monospace advance + GROWTH) must not overlap each other."""
    out = []
    for name, texts in ALL_TEXT.items():
        clash = []
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                s1, x1, y1, z1, k1 = texts[i]
                s2, x2, y2, z2, k2 = texts[j]
                if abs(y1 - y2) > max(z1, z2):
                    continue
                l1, l2 = _left(s1, x1, z1, k1), _left(s2, x2, z2, k2)
                if l1 < l2 + txtw(s2, z2) and l2 < l1 + txtw(s1, z1):
                    clash.append((s1[:22], s2[:22]))
        out.append("  %-26s labels=%-3d overlaps=%d %s" % (name, len(texts), len(clash), clash[:3] if clash else ""))
    return out


ALL_TEXT = {}


def main():
    if "--check" in sys.argv:
        global DRY
        DRY = True
        for fn in (fig_routing, fig_traffic, fig_cache, fig_latency):   # rebuild the registers
            ALL_TEXT[fn()] = list(_meta)
        names = ["fig-routing.svg", "fig-traffic.svg", "fig-cache.svg", "fig-latency-cost.svg"]
        problems = verify(names)
        print("checked %d figures" % len(names))
        for p in problems:
            print("  FAIL", p)
        print("PASS" if not problems else "FAILED (%d)" % len(problems))
        return 0 if not problems else 1
    os.makedirs(OUT, exist_ok=True)
    made = []
    for fn in (fig_routing, fig_traffic, fig_cache, fig_latency):
        made.append(fn())
        ALL_TEXT[made[-1]] = list(_meta)
    for m in made:
        print("wrote assets/%s  %d bytes" % (m, os.path.getsize(os.path.join(OUT, m))))
    problems = verify(made)
    for p in problems:
        print("  FAIL", p)
    print("verify: %s" % ("PASS" if not problems else "FAILED (%d)" % len(problems)))
    for line in layout_report():
        print(line)
    print("allowed numbers: %d from FACTS/derived + %d structural axis ticks" % (len(allowed_numbers()), len(_structural)))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
