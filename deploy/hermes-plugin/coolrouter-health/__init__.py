"""Warn when the local-first router is unreachable.

Observer-only by design: this plugin never returns text, so it never injects anything into the
prompt. Unverified health data injected into a model's context has produced fabricated failures
before, so the only side effect here is a log line and two counters.

Install:
    cp -r deploy/hermes-plugin/coolrouter-health ~/.hermes/plugins/
    hermes plugins enable coolrouter-health
"""
import logging
import os
import threading
import time
import urllib.request

logger = logging.getLogger("hermes.plugins.coolrouter_health")

ROUTER_URL = os.environ.get("COOLROUTER_URL", "http://127.0.0.1:8000")
CHECK_EVERY = 300.0          # seconds between probes — a per-turn check would be wasteful

_lock = threading.Lock()
_last_check = 0.0
_down_since = None
_checks = 0
_failures = 0


def _probe():
    """One cheap health probe. True when the router answers."""
    try:
        with urllib.request.urlopen(ROUTER_URL + "/healthz", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def on_pre_llm_call(**kwargs):
    """Never returns text: the prompt is left exactly as it was."""
    global _last_check, _down_since, _checks, _failures
    try:
        with _lock:
            now = time.time()
            if now - _last_check < CHECK_EVERY:
                return None
            _last_check = now
            _checks += 1
        if _probe():
            with _lock:
                if _down_since is not None:
                    logger.info("coolrouter-health: router reachable again on %s", ROUTER_URL)
                _down_since = None
            return None
        with _lock:
            _failures += 1
            first = _down_since is None
            if first:
                _down_since = time.time()
            checks, failures = _checks, _failures
        if first:
            logger.warning(
                "coolrouter-health: %s is unreachable (%d/%d probes failed) — local-first routing "
                "is degraded and requests are falling back to cloud providers",
                ROUTER_URL, failures, checks)
    except Exception:
        logger.warning("coolrouter-health: probe error, passing through", exc_info=True)
    return None


def register(ctx):
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    logger.info("coolrouter-health: watching %s every %ds", ROUTER_URL, int(CHECK_EVERY))
