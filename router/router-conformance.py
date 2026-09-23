#!/usr/bin/env python3
"""Table-driven conformance test for the smart router (closes a documented gap).

Each row is an input and the routing decision it MUST produce. Unlike the unit test
(test-router-p0.py, which checks one function), this exercises the whole chain end to end
against the LIVE proxy, so it catches a guard that stops firing or a tier that quietly moves.

Run:  venv-router/Scripts/python.exe scripts/router-conformance.py
Exit: 0 only when every row passes.
"""
import json, sys, time, threading, urllib.error, urllib.request

BASE = "http://127.0.0.1:8000"
OK = []


def call(content, tier=None, mt=48, timeout=200):
    body = {"messages": [{"role": "user", "content": content}], "max_tokens": mt}
    if tier:
        body["tier"] = tier
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.time()
    d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    return d, time.time() - t0


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, "%s: %s" % (type(e).__name__, e)
    OK.append(ok)
    print("  [%s] %-34s %s" % ("PASS" if ok else "FAIL", name, detail))


# ── rows ────────────────────────────────────────────────────────────────
check("pure arithmetic stays local", lambda: (
    (lambda d, _: (d.get("x-route") == "local" and "pure_calc" in str(d.get("x-guard")),
                   "route=%s guard=%s" % (d.get("x-route"), d.get("x-guard"))))(*call("what is 2+2"))))

check("secret is forced local", lambda: (
    (lambda d, _: (d.get("x-forced-local") is True and d.get("x-route") == "local",
                   "route=%s forced=%s" % (d.get("x-route"), d.get("x-forced-local"))))(
        *call("my api key is sk-test-1234567890, please redact it"))))


def _fact():
    d, _ = call("香港人口大約幾多？")
    return d.get("x-route") in ("flash", "research") and str(d.get("x-source", "")).startswith("guard"), \
        "route=%s src=%s" % (d.get("x-route"), d.get("x-source"))


check("real-world fact escalates", _fact)

check("explicit tier is honoured", lambda: (
    (lambda d, _: (d.get("x-route") == "flash" and d.get("x-source") == "explicit",
                   "route=%s src=%s" % (d.get("x-route"), d.get("x-source"))))(
        *call("hello", tier="flash"))))


def _dev():
    d, _ = call("write a python script that reads a csv file")
    return d.get("x-route") not in ("voice", "video"), "route=%s" % d.get("x-route")


check("dev request is not audio/video", _dev)

check("citation request -> research", lambda: (
    (lambda d, _: (d.get("x-route") == "research", "route=%s src=%s" % (d.get("x-route"), d.get("x-source"))))(
        *call("核實一下 DeepSeek V4.1 幾時推出，要附出處", mt=64))))


# A REAL 64x64 PNG (three colour bands + a white square). The old row sent
# `iVBORw0KGgoAAAANSUhEUg==`, which is not a decodable image at all: the provider rejected it, the
# row died on a 502 and the routing bug underneath it stayed invisible for a whole session.
# A conformance fixture must be valid input.
_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAnUlEQVR4nOXXoRXCQAAE0bl5KQEssVdE0hf9YSgCE00TqSECMY/vR63a8ZmTMomTOImTOImTOImTOImTOImTOImTOImTOImTOImTuDHfT8okTuIkTuIkTuIkTuIkTuIkTuIkTuIkTuIkTuIkTuIkbtweG2USJ3ESJ3HL1eB7vPix+7r/0QISJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESN+qf+ATZ8AbvbdJOigAAAABJRU5ErkJggg=="


def _image_call(text, tier=None, mt=48, timeout=240):
    body = {"messages": [{"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _PNG_B64}}]}],
        "max_tokens": mt}
    if tier:
        body["tier"] = tier
    req = urllib.request.Request(BASE + "/v1/chat/completions", json.dumps(body).encode(),
                                {"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        # Even a failure carries the routing decision now (x-route / x-source / x-guard), so a
        # dead leg can never hide a wrong decision.
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {}


def _vision():
    d = _image_call("what is in this image?")
    return d.get("x-route") == "vision", "route=%s guard=%s" % (d.get("x-route"), d.get("x-guard"))


check("image part -> vision tier", _vision)


def _vision_local():
    """An image with an explicit tier=local stays home AND is served by the LOCAL VL MODEL —
    never by a text model reading base64 as prose."""
    d = _image_call("what is in this image?", tier="local")
    return (d.get("x-route") == "local" and d.get("x-local-vision") is True,
            "route=%s local_vision=%s model=%s" % (d.get("x-route"), d.get("x-local-vision"),
                                                   d.get("model")))


check("image + tier=local -> local VL", _vision_local)


def _vision_private():
    """An image plus private wording must fail closed: served locally, never sent to the cloud."""
    d = _image_call("this is my private photo, don't send it to the cloud")
    return (d.get("x-forced-local") is True and d.get("x-route") == "local",
            "forced=%s route=%s vision=%s" % (d.get("x-forced-local"), d.get("x-route"),
                                              d.get("x-local-vision")))


check("image + private -> forced local", _vision_private)


def _hz():
    h = json.loads(urllib.request.urlopen(BASE + "/healthz", timeout=10).read())
    return (h.get("ok") is True and h.get("ollama_up") is True and len(h.get("tiers", [])) >= 6
            and "jev_calls" in (h.get("stats") or {})), \
        "tiers=%d vram=%s jev_calls=%s" % (len(h.get("tiers", [])), h.get("gpu_vram_used_mb"),
                                           (h.get("stats") or {}).get("jev_calls"))


check("healthz shape + counters", _hz)


def _conc():
    res, lock = [], threading.Lock()

    def w():
        try:
            _, el = call("say ok", tier="local", mt=8)
            with lock:
                res.append(el)
        except Exception as e:
            with lock:
                res.append(-1)

    th = [threading.Thread(target=w) for _ in range(3)]
    t0 = time.time()
    for t in th:
        t.start()
    for t in th:
        t.join()
    wall = time.time() - t0
    worst = max(res)
    return wall < worst * 1.5, "wall=%.2fs worst=%.2fs (serial would be ~%.1fs)" % (wall, worst, sum(res))


check("3 concurrent requests overlap", _conc)

print("\n" + "=" * 62)
print("TOTAL %d/%d PASS" % (sum(OK), len(OK)))
sys.exit(0 if all(OK) else 1)
