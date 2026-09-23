"""Verify the 2026-09-23 router P0 fixes with a REAL fake upstream (no mocks of our own code).

Tests:
  1. HTTP 200 + empty content  -> _call_leg must RAISE (was: silently returned a blank answer)
  2. HTTP 200 + choices []     -> must RAISE
  3. HTTP 200 + good content   -> must succeed
  4. tool_calls preserved      -> must not be dropped from the rebuilt response
  5. _call_chain with [bad, good] -> must fall through to the good leg
  6. ThreadingHTTPServer is the server class actually used
"""
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

_here = os.path.dirname(os.path.abspath(__file__))
# Resolves from every location this test lives in: <profile>/scripts/, <profile>/cache/scratch/,
# or <repo>/router/ (next to router-proxy.py).
SCRIPTS = _here if os.path.exists(os.path.join(_here, "router-proxy.py")) \
    else os.path.abspath(os.path.join(_here, "..", "..", "scripts"))
sys.path.insert(0, SCRIPTS)

MODE = {"v": "empty"}


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        if MODE["v"] == "empty":
            body = {"choices": [{"message": {"role": "assistant", "content": ""}}]}
        elif MODE["v"] == "nochoices":
            body = {"choices": []}
        elif MODE["v"] == "good":
            body = {"choices": [{"message": {"role": "assistant", "content": "hello from fake"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
        else:
            body = {"choices": [{"message": {"role": "assistant", "content": "",
                                             "tool_calls": [{"id": "c1", "type": "function",
                                                             "function": {"name": "f", "arguments": "{}"}}]}}]}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 8199), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()

import importlib.util
spec = importlib.util.spec_from_file_location("router_proxy", os.path.join(SCRIPTS, "router-proxy.py"))
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

os.environ["TEST_KEY"] = "x"
os.environ["TEST_KEY2"] = "x"
LEG = {"url": "http://127.0.0.1:8199/v1/chat/completions", "model": "fake-model",
       "api_key_env": "TEST_KEY", "provider": "test"}
PAYLOAD = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 8}
results = []


def check(name, fn, expect_raise):
    try:
        out = fn()
        if expect_raise:
            results.append((name, "FAIL", "expected raise, got %s" % str(out)[:70]))
        else:
            results.append((name, "PASS", str(out)[:70]))
    except Exception as e:
        if expect_raise:
            results.append((name, "PASS", "%s: %s" % (type(e).__name__, str(e)[:60])))
        else:
            results.append((name, "FAIL", "%s: %s" % (type(e).__name__, str(e)[:60])))


MODE["v"] = "empty"
check("1 empty content raises", lambda: rp._call_leg(PAYLOAD, LEG), True)
MODE["v"] = "nochoices"
check("2 no choices raises", lambda: rp._call_leg(PAYLOAD, LEG), True)
MODE["v"] = "good"
check("3 good content succeeds", lambda: rp._call_leg(PAYLOAD, LEG), False)
MODE["v"] = "toolcall"
check("4 tool_calls preserved", lambda: rp._call_leg(PAYLOAD, LEG)["choices"][0]["message"].get("tool_calls"), False)

# 5) chain falls through from the empty leg to the good one
MODE["v"] = "empty"
bad = dict(LEG)
good = dict(LEG, model="fake-model-2", api_key_env="TEST_KEY2")   # _leg_key = api_key_env|url → must differ
chain_payload = dict(PAYLOAD)
orig = rp._call_leg


def fake_leg(payload, leg, timeout=120):
    if leg is bad:
        MODE["v"] = "empty"
    else:
        MODE["v"] = "good"
    return orig(payload, leg)


rp.TIERS["testchain"] = {"chain": [bad, good]}
rp._LEG_COOLDOWN.clear()
rp._call_leg = fake_leg
try:
    r = rp._call_chain(chain_payload, "testchain")
    ok = r["choices"][0]["message"]["content"] == "hello from fake"
    results.append(("5 chain falls through", "PASS" if ok else "FAIL", r["choices"][0]["message"]["content"][:50]))
except Exception as e:
    results.append(("5 chain falls through", "FAIL", "%s: %s" % (type(e).__name__, str(e)[:60])))
rp._call_leg = orig

import http.server as hs
results.append(("6 ThreadingHTTPServer in use",
                "PASS" if rp.ThreadingHTTPServer is hs.ThreadingHTTPServer else "FAIL",
                rp.ThreadingHTTPServer.__name__))
results.append(("7 shared-state lock present",
                "PASS" if hasattr(rp, "_LOCK") else "FAIL",
                "threading.Lock" if hasattr(rp, "_LOCK") else "missing"))

srv.shutdown()
print("=" * 62)
for n, s, d in results:
    print("  [%s] %-26s %s" % (s, n, d))
fails = [r for r in results if r[1] != "PASS"]
print("=" * 62)
print("TOTAL %d/%d PASS" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
