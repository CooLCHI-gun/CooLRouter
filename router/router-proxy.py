#!/usr/bin/env python3
"""Ponytail Router v2 — 8-tier multi-destination router. Replaces centroid."""
import hashlib, json, os, re, shutil, sys, subprocess, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from memory_enhancer import route_query      # optional: trained intent classifier
except Exception:                                # absent in a standalone checkout
    def route_query(text, *args, **kwargs):
        """Deterministic stand-in for the trained classifier.

        The published core must run with no local modules present. Shape-based routing keeps the
        cheap shapes cheap; every guard downstream still runs, so privacy and typed decisions are
        unaffected. With the classifier installed this branch is never taken.
        """
        t = (text or "").strip()
        if t and _PURE_CALC.search(t):
            return "local", 0.4          # arithmetic never needs a frontier model
        return "flash", 0.5

# Load .router-env for API keys
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".router-env")
if os.path.exists(_env_path):
    # encoding MUST be explicit: on Windows the default is the ANSI codepage (cp950 here),
    # and any non-ASCII byte in .router-env (e.g. a Chinese comment) raised
    # UnicodeDecodeError at import time -> the proxy died on boot, so :8000 was silently dead.
    for _line in open(_env_path, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ[_k.strip()] = _v.strip()

# Provider keys (NVIDIA_API_KEY, PERPLEXITY_API_KEY, ...) live in the profile .env, NOT
# .router-env. Load every KEY=VALUE line without overriding anything already in the
# environment — a hardcoded single-key read left vision tier calling NVIDIA with no key
# (HTTP 500 on every request) while the key sat in .env all along.
_env_profile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
if os.path.exists(_env_profile):
    import re as _re
    for _line in open(_env_profile, encoding="utf-8"):
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
        if _re.fullmatch(r"[A-Z0-9_]+", _k) and _v and _k not in os.environ:
            os.environ[_k] = _v

# ── VRAM guard ─────────────────────────────────────────────────────
# A 6 GB GPU: the local model needs ~3.4GB VRAM. If another GPU workload
# is using most of the card, loading the local model would silently fall
# back to CPU (slow). Fail-closed for forced-local (private) traffic; for
# ordinary local-classified queries, degrade to flash instead.
LOCAL_VRAM_USED_MAX_MB = 4500
# LOCAL MODEL = NON-THINKING INSTRUCT (measured 2026-09-22). A reasoning distill spends the
# entire Jev token cap inside its "Thinking Process:" preamble: the local model with cap 320 emitted
# 912 chars of CoT, done_reason=length, i.e. ZERO answer. gemma3:4b answers the same prompt in
# 1.6 s / 60 tokens / done=stop. The cap only works on a model that does not think out loud.
_LOCAL_MODEL_NAME        = os.environ.get("ROUTER_LOCAL_MODEL", "gemma3:4b")
# The local engine is an OpenAI-compatible Ollama endpoint. Configurable so the published core can
# run beside the engine instead of on it (a container, another host) without editing source.
_OLLAMA_URL              = os.environ.get("ROUTER_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
# Local VISION model. gemma3:4b is itself multimodal (Ollama reports capabilities
# ["completion","vision"]), but the dedicated VL distill is the one measured correct on image
# questions (11/11, 0.4 s), so image traffic on the local tier uses it. Env-overridable so a
# different machine does not need a code edit.
_LOCAL_VISION_MODEL = os.environ.get(
    "ROUTER_LOCAL_VISION_MODEL", "hf.co/unsloth/Qwen3-VL-4B-Instruct-GGUF:Q4_K_M")
_VRAM_ERR = None


def _img_parts(msg) -> list:
    """Content parts of a message (a bare string content has none)."""
    c = (msg or {}).get("content")
    return [p for p in c if isinstance(p, dict)] if isinstance(c, list) else []


def _has_image(messages) -> bool:
    """True when the payload actually carries an image.

    An image is not something a text tier may answer. Without this, a short simple prompt
    ("what is in this image?") classified as `local`, and the local call stringified the image
    into the prompt as base64, so the model described text it could not see.
    """
    for m in (messages or []):
        for p in _img_parts(m):
            if p.get("type") in ("image", "image_url", "input_image"):
                return True
        c = (m or {}).get("content")
        if isinstance(c, str) and "data:image/" in c:
            return True
    return False


def _split_multimodal(msg) -> tuple:
    """(text, [b64 images]) for one message.

    Ollama takes images in its own `images` field — a json.dumps()'d content list is just text
    to it, which is exactly how a vision request silently became a hallucination.
    """
    text, imgs = [], []
    for p in _img_parts(msg):
        t = p.get("type")
        if t in ("image", "image_url", "input_image"):
            u = p.get("image_url")
            u = u.get("url") if isinstance(u, dict) else (u if isinstance(u, str) else "")
            u = str(u or p.get("data") or "")
            if u.startswith("data:") and "," in u:
                u = u.split(",", 1)[1]          # Ollama wants raw base64, not a data: URL
            elif not u and p.get("data"):
                u = str(p["data"])
            if u:
                imgs.append(u)
        elif t == "text":
            text.append(str(p.get("text", "")))
    return "\n".join(text), imgs


def _local_model_for(payload) -> str:
    """The model the local tier must use for THIS payload."""
    return _LOCAL_VISION_MODEL if _has_image((payload or {}).get("messages")) else _LOCAL_MODEL_NAME
def _gpu_vram_used_mb() -> int:
    """VRAM used (MB). Return -1 when nvidia-smi is unusable (let Ollama decide).

    The reason is kept in _VRAM_ERR and printed by /healthz: a silent -1 silently
    DISABLES the VRAM guard, and looks identical to "no GPU pressure".
    """
    global _VRAM_ERR
    exe = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    try:
        out = subprocess.run(
            [exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout
        _VRAM_ERR = None
        return int(out.strip().splitlines()[0].strip())
    except Exception as e:
        _VRAM_ERR = f"{type(e).__name__}: {e}"
        return -1

# ── Trace, counters, session pin (added 2026-09-22) ───────────────────
# Why: the router could not answer "did routing make me faster or more expensive?" — there was no
# per-tier cost/latency record and no cache-hit accounting. Cache matters most: DeepSeek bills a
# prefix-cache HIT at $0.003/M vs $0.15/M for a MISS (off-peak) — a 50x difference on input.
_TRACE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "router-trace.jsonl")
_STATS = {"by_tier": {}, "cache": {"prompt_tokens": 0, "cached_tokens": 0, "hits": 0, "misses": 0},
          "pins": 0, "jev_guards": 0, "jev_fail": 0, "jev_calls": 0}
# One global lock for the shared mutable state (_STATS, _SESSION_PIN, _LEG_COOLDOWN, trace writes).
# The server is threaded (2026-09-23), so unsynchronised read-modify-write would lose counters and
# could let two requests race the same leg. Critical sections stay short — never hold it over I/O.
_LOCK = threading.Lock()


def _trace(row: dict) -> None:
    """Append one JSONL row per dispatch. Never raise — telemetry must not break serving."""
    try:
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with _LOCK:
            os.makedirs(os.path.dirname(_TRACE_PATH), exist_ok=True)
            with open(_TRACE_PATH, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


def _bump(tier, ms, usage) -> dict:
    with _LOCK:
        t = _STATS["by_tier"].setdefault(tier, {"n": 0, "ms_sum": 0.0, "ms_max": 0.0,
                                                "prompt_tokens": 0, "cached_tokens": 0,
                                                "completion_tokens": 0})
        t["n"] += 1
        t["ms_sum"] += ms
        t["ms_max"] = max(t["ms_max"], ms)
        det = (usage or {}).get("prompt_tokens_details") or {}
        pt = int((usage or {}).get("prompt_tokens") or 0)
        cached = int(det.get("cached_tokens") or 0)
        ct = int((usage or {}).get("completion_tokens") or 0)
        t["prompt_tokens"] += pt
        t["cached_tokens"] += cached
        t["completion_tokens"] += ct
        c = _STATS["cache"]
        c["prompt_tokens"] += pt
        c["cached_tokens"] += cached
        if pt:
            c["hits" if cached >= pt * 0.5 else "misses"] += 1
        return {"prompt_tokens": pt, "cached_tokens": cached, "completion_tokens": ct,
                "cache_hit_rate": round(cached / pt, 3) if pt else None}


def _health_stats() -> dict:
    """Compact self-describing counters for /healthz (and the arena's baseline)."""
    tiers = {}
    for t, v in _STATS["by_tier"].items():
        n = v["n"] or 1
        tiers[t] = {"n": v["n"], "ms_avg": round(v["ms_sum"] / n, 1), "ms_max": round(v["ms_max"], 1),
                    "prompt_tokens": v["prompt_tokens"], "cached_tokens": v["cached_tokens"],
                    "completion_tokens": v["completion_tokens"]}
    c = _STATS["cache"]
    return {"tiers": tiers, "pins": _STATS["pins"], "jev_guards": _STATS["jev_guards"],
            "jev_fail": _STATS["jev_fail"], "jev_calls": _STATS["jev_calls"],
            "session_pins_live": len(_SESSION_PIN),
            "cache": {**c, "hit_rate": round(c["cached_tokens"] / c["prompt_tokens"], 3)
                      if c["prompt_tokens"] else None},
            "trace_path": _TRACE_PATH}


_SESSION_PIN = {}      # {session_key: (tier, model, ts)} — prefix-cache affinity
_PIN_TTL = 7200


def _sess_key(payload: dict) -> str:
    """Key a conversation by its FIRST USER message (+ the system prompt head).

    Must be stable while the conversation GROWS (every turn re-sends the full history, and a key
    over "the first two messages" changes on turn 3, which silently disabled the pin) and unique
    per session (a system-prompt-only key would collide across conversations).
    """
    try:
        msgs = payload.get("messages") or []
        sys_head = first_user = ""
        for m in msgs:
            c = m.get("content")
            c = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
            if m.get("role") == "system" and not sys_head:
                sys_head = c[:200]
            if m.get("role") == "user" and not first_user:
                first_user = c[:400]
                break
        return hashlib.sha1((sys_head + "|" + first_user).encode("utf-8", "ignore")).hexdigest()[:16]
    except Exception:
        return ""


def _tier_model(tier: str) -> str:
    cfg = TIERS.get(tier) or {}
    legs = cfg.get("chain") or [cfg]
    return legs[0].get("model") or cfg.get("model") or ""


def _modality(tier: str) -> str:
    return "vision" if tier == "vision" else "text"


def _looks_like_question(text: str) -> bool:
    t = text.strip()
    return t.endswith(("?", "？")) or bool(re.search(
        r"(嗎|呢|咩|幾多|幾時|邊個|係咪|係唔係|\bwhat\b|\bhow\b|\bwhy\b|\bwhen\b|\bwho\b|\bwhich\b)",
        t, re.I))


def _ollama_up() -> bool:
    try:
        urlopen(_OLLAMA_URL + "/api/tags", timeout=3).read()
        return True
    except Exception:
        return False

def _local_model_loaded(name: str = "") -> bool:
    """True when that local model is already resident in Ollama (the VRAM gate is about
    *loading* under contention — a resident model is fine even if VRAM is full)."""
    try:
        out = urlopen(_OLLAMA_URL + "/api/ps", timeout=5).read()
        return (name or _LOCAL_MODEL_NAME).encode() in out
    except Exception:
        return False

# ── Tier configs ─────────────────────────────────────────────────────
# opencode has two legs: GO = monthly subscription (tried first), ZEN = pay-per-use (fallback once GO quota runs out)
_OC_GO = "https://opencode.ai/zen/go/v1/chat/completions"
_OC_ZEN = "https://opencode.ai/zen/v1/chat/completions"
# measured 2026-09-20: GO without x-opencode-session → HTTP 400 MissingSessionID; sending the header works.
_OC_HDRS = {"x-opencode-session": "hermes-router"}

def _leg(url, model, key_env, kind="opencode"):
    return {"url": url, "model": model, "api_key_env": key_env, "kind": kind}

_GO_FLASH = _leg(_OC_GO, "deepseek-v4.1-flash", "OPENCODE_GO_API_KEY")
_ZEN_FLASH = _leg(_OC_ZEN, "deepseek-v4.1-flash", "OPENCODE_ZEN_API_KEY")

TIERS = {
    # (1) PRIVATE-FIRST — local 4B. private/PII traffic is fail-closed and never goes to the cloud.
    "local": {
        "url": _OLLAMA_URL + "/api/generate",
        "model": _LOCAL_MODEL_NAME,
        "provider": "ollama",
        "note": "private-first；non-thinking instruct（cap 才有效）；VRAM 緊張時普通請求降 flash，forced-local fail-closed",
    },
    # (2) DEFAULT — DeepSeek v4.1 flash. GO subscription first → ZEN once the quota is out (same model id).
    "flash": {
        "chain": [_GO_FLASH, _ZEN_FLASH],
        "note": "default；go(月費) → zen fallback，同一個 model id（deepseek-v4.1-flash）",
    },
    # (6) META — the classifier's "asks about routing / own capability" class; no capability of its own, behaves as default.
    "meta": {
        "chain": [_GO_FLASH, _ZEN_FLASH],
        "note": "唔係獨立能力，只係 classifier class → 同 flash 同一條鏈",
    },
    # pro/premium removed (2026-09-20): DeepSeek v4.1 flash is capable enough, so a costly tier is
    # not worth keeping. The classifier still emits "pro"/"premium" → no DISPATCH entry → automatic
    # fallback to the flash chain, zero extra cost and no surprise. Add a chain here to restore one.
    # (3) VISION — three legs, and the order is deliberate, not arbitrary:
    #   (1) go     deepseek-v4-flash-vision-exp → the same model Hermes auxiliary.vision uses
    #      (identical OCR/document/chart quality, so the two never disagree)
    #   (2) zen    same model → images still work once the quota is gone
    #   (3) nvidia nemotron-3-nano-omni → free backup, still works if the first two die
    # note: local vision (Ollama gemma3:4b / qwen3.5:4b / gemma-4-E2B) is for fully offline use only.
    "vision": {
        "chain": [_leg(_OC_GO, "deepseek-v4-flash-vision-exp", "OPENCODE_GO_API_KEY"),
                  _leg(_OC_ZEN, "deepseek-v4-flash-vision-exp", "OPENCODE_ZEN_API_KEY"),
                  _leg("https://integrate.api.nvidia.com/v1/chat/completions",
                       "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "NVIDIA_API_KEY",
                       kind="nvidia")],
        "note": "go/zen = deepseek-v4-flash-vision-exp（同 Hermes aux vision 一致）, nvidia = 免費後備",
    },
    # (4) VOICE — local edge-tts.
    #    honest note: this tier returns only a placeholder string, never an audio file;
    #    real speech needs the built-in Hermes TTS (text_to_speech tool / config.yaml tts section).
    "voice": {
        "url": None,  # handled locally
        "model": "edge-tts",
        "provider": "local-tts",
        "note": "本地 edge-tts placeholder（唔回音檔）",
    },
    # (7) RESEARCH — Perplexity. Every call carries a search-context floor (~$0.005–0.014), so it
    #    opens only when live external data or fact verification is genuinely needed (see the do_POST gate).
    "research": {
        "url": "https://api.perplexity.ai/chat/completions",
        "model": "sonar-pro",
        "reason_model": "sonar-reasoning-pro",
        "api_key_env": "PERPLEXITY_API_KEY",
        "provider": "perplexity",
        "note": "sonar-pro 預設（平、有 citation）；判斷／長查詢升 sonar-reasoning-pro",
    },
}
# note: the "video" tier was removed (2026-09-20). Video analysis needs the built-in Hermes
#     video_analyze (Gemini, ≤50MB): the router accepts text chat-completions payloads only and
#     cannot carry video; generation needs a separate API. A "video" class still falls back to flash.

def _get_api_key(tier_cfg: dict) -> str:
    env_var = tier_cfg.get("api_key_env", "")
    return os.environ.get(env_var, "")

# ── Jev: decide how long the answer should be → fixes the local 4B's verbosity ──
# measured (2026-09-21): the local model is a reasoning distill, so an "explain in one sentence"
# question produced 1,688 tokens / 4,054 chars = 25 s; Ollama itself runs at 68.6 tok/s, meaning
# the slowness was over-generation, not a slow runtime. With a cap: 120 tokens → 1.93s, 60 → 1.04s.
# So one Jev choice question (~0.4s, $0.00003) classifies the length bucket → sets num_predict.
# ⚠️ Jev is a cloud service → forced-local (private/PII) traffic must never be handed to it for
#    classification; private requests use the default cap (_JEV_DEFAULT) and leak nothing.
_JEV_LEN = {"one-line": 96, "short": 320, "detailed": 1200}
_JEV_DEFAULT = 384


def _jev_key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY", "")
    if k:
        return k
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
        with open(p, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip().startswith("OPENROUTER_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _jev_len_class(text: str) -> str:
    """Return 'one-line' | 'short' | 'detailed'; on failure or a missing key → 'short' (safe default)."""
    key = _jev_key()
    if not key:
        return "short"
    body = {"model": "typesafe/jev-1.13", "state": text[:1500],
            "questions": {"len": {"type": "choice",
                                  "instructions": "這條請求期望嘅答案長度係邊一類？",
                                  "criteria": {
                                      "one-line": "一句話、單一數字、是／否、單一名詞",
                                      "short": "幾句到一段（約 100-300 字）",
                                      "detailed": "需要詳細解釋、步驟、程式碼或長文分析"}}}}
    try:
        req = Request("https://openrouter.ai/api/alpha/decisions", json.dumps(body).encode(),
                      {"Content-Type": "application/json", "Authorization": "Bearer " + key})
        d = json.loads(urlopen(req, timeout=20).read())
        return ((d.get("answers") or {}).get("len") or {}).get("choice") or "short"
    except Exception:
        return "short"


# ── Jev guards (2026-09-22) ──────────────────────────────────────────
# Measured on 9 real queries: Jev's two Noul answers are well-calibrated where the keyword guard
# was brittle (the population question came back world_knowledge=0.96 while the tier CHOICE was
# only 0.29 confidence; the fact check 0.97/0.93; coding <=0.16). Cost $0.00002, 0.3-0.6 s.
# It runs ONLY for question-shaped queries the classifier sent to the weak local/meta tier, so a
# plain request pays neither the cost nor the latency.
_JEV_GUARD_ON = True


def _jev_guards(text: str):
    """-> (needs_world_knowledge, needs_citations); (None, None) when unavailable."""
    key = _jev_key()
    if not key:
        return None, None
    body = {"model": "typesafe/jev-1.13", "state": text[:1500],
            "questions": {
                "wk": {"type": "noul",
                       "instructions": "答呢條問題係咪需要準確嘅現實世界事實（數字、年份、人物、價格）？"},
                "cit": {"type": "noul",
                        "instructions": "用戶係咪要求出處、核實或者最新資料？"}}}
    try:
        req = Request("https://openrouter.ai/api/alpha/decisions", json.dumps(body).encode(),
                      {"Content-Type": "application/json", "Authorization": "Bearer " + key})
        d = json.loads(urlopen(req, timeout=20).read())
        a = d.get("answers") or {}
        return (a.get("wk") or {}).get("noul"), (a.get("cit") or {}).get("noul")
    except Exception:
        return None, None


# ── Jev merged call (2026-09-23) ─────────────────────────────────────
# Both Jev jobs run on the SAME request class (local/meta, not forced-local), so two separate
# POSTs were paying two round-trips (~0.3-0.5 s each) on the tier that is supposed to be the
# fast one. Measured: a warm local answer takes 1.4-2.3 s, so the second round-trip was a
# 30-70% latency tax on the fastest tier. One request now answers every question needed.
# Instructions are in English: English is the best-served language for this model, and the
# world-knowledge question must explicitly exclude computation — it scored 0.9 on "what is 2+2"
# and escalated pure arithmetic to a paid cloud tier.
_PURE_CALC = re.compile(
    r"^\s*(?=.*\d)(?=.*[+\-*/×÷^%])"
    r"(?:what(?:'s| is)|calculate|compute|solve|how much is|幾多|多少)?\s*"
    r"[\d\s.+\-*/()×÷^%]+[\s=?]*(?:equals)?[\s=?]*$", re.I)


def _jev_decide(text: str, want_len: bool = False, want_guards: bool = False) -> dict:
    """One Jev request for every question needed -> {'len':.., 'wk':.., 'cit':..}.

    Missing/failed answers are simply absent from the dict, so callers fall back to their own
    defaults. Never raises. Cloud call: never pass forced-local (private) text.
    """
    key = _jev_key()
    if not key or not (want_len or want_guards):
        return {}
    q = {}
    if want_len:
        q["len"] = {"type": "choice",
                    "instructions": "How long should the answer to this request be?",
                    "criteria": {
                        "one-line": "a single sentence, one number, yes/no, or a single name",
                        "short": "a few sentences up to one paragraph",
                        "detailed": "needs detailed explanation, steps, code, or long analysis"}}
    if want_guards:
        q["wk"] = {"type": "noul",
                   "instructions": ("Does answering this question accurately require real-world "
                                    "facts (numbers, dates, people, prices)? Pure arithmetic or "
                                    "computation that needs no external facts does NOT count.")}
        q["cit"] = {"type": "noul",
                    "instructions": ("Is the user explicitly asking for sources, verification, "
                                     "or the latest information?")}
    body = {"model": "typesafe/jev-1.13", "state": text[:1500], "questions": q}
    try:
        req = Request("https://openrouter.ai/api/alpha/decisions", json.dumps(body).encode(),
                      {"Content-Type": "application/json", "Authorization": "Bearer " + key})
        d = json.loads(urlopen(req, timeout=20).read())
        a = d.get("answers") or {}
        out = {}
        if want_len:
            out["len"] = (a.get("len") or {}).get("choice")
        if want_guards:
            out["wk"] = (a.get("wk") or {}).get("noul")
            out["cit"] = (a.get("cit") or {}).get("noul")
        with _LOCK:
            _STATS["jev_calls"] += 1
        return out
    except Exception:
        with _LOCK:
            _STATS["jev_calls"] += 1
        return {}


_THINK_HDR_RE = re.compile(r"^\s*(thinking process|thinking|reasoning|思考過程|分析過程)\s*[:：]", re.I)
_FINAL_MARK_RE = re.compile(r"(?im)^\s*\**\s*(final answer|answer|結論|答案)\s*\**\s*[:：]")


def _strip_think(content: str):
    """Drop a leading chain-of-thought preamble -> (text, stripped?).

    Belt-and-braces: the local tier now uses a non-thinking model, but any reasoning model
    put on this tier would otherwise return ONLY its preamble (the cap cuts it mid-thought).
    """
    if not _THINK_HDR_RE.match(content):
        return content, False
    last = None
    for last in _FINAL_MARK_RE.finditer(content):
        pass
    if last:
        rest = content[last.end():].strip()
        if rest:
            return rest, True
    lines, seen_blank = content.splitlines(), False
    for ln in lines[1:]:
        s = ln.strip()
        if not s:
            seen_blank = True
            continue
        if seen_blank and not re.match(r"^(\d+[.)]|[-*•]|\*\*)", s):
            return s, True
    return content, True


def _call_ollama(payload: dict, tier: str) -> dict:
    """Call Ollama /api/generate. Handles thinking field for reasoning models.

    Output cap precedence: caller-specified > forced-local default > Jev length decision.
    """
    cfg = TIERS[tier]
    last = payload["messages"][-1]
    last_msg = last.get("content")
    if isinstance(last_msg, str):
        text, images = last_msg, []
    else:
        text, images = _split_multimodal(last)
        if not text.strip():
            # No text part at all: keep the caller's payload visible rather than sending an
            # empty prompt (an empty prompt made a vision model answer about nothing).
            text = json.dumps([p for p in last_msg if isinstance(p, dict) and p.get("type") == "text"]
                              or last_msg)[:2000]
    model = _local_model_for(payload)
    if payload.get("max_tokens"):
        npred, len_class = int(payload["max_tokens"]), "caller"
    elif payload.get("_forced_local"):
        npred, len_class = _JEV_DEFAULT, "forced-local(default)"
    else:
        _pre = payload.get("_jev") or {}
        len_class = _pre.get("len") or _jev_len_class(text[:1500])
        npred = _JEV_LEN.get(len_class, _JEV_DEFAULT)
    # FLOOR (measured 2026-09-22): below ~128 tokens the answer is cut mid-sentence even on a
    # non-thinking model (cap 96 -> answer truncated mid-sentence, done_reason=length).
    npred = max(npred, 160)
    llm_payload = {
        "model": model,
        "prompt": text,
        **({"images": images} if images else {}),
        "stream": False,
        "keep_alive": "3m",  # 3m: VRAM frees when idle. Was 30m — that plus the 6-min keepalive
                             # cron prewarm held most of the card's VRAM permanently (measured
                             # 2026-09-22: 5593MiB used idle vs 551MiB after unload) and starved
                             # games/capture. Cold start costs 27s (measured) — acceptable for a
                             # tier that only serves private/short prompts.
        "options": {"num_predict": npred},
    }
    req = Request(cfg["url"], json.dumps(llm_payload).encode(),
                  {"Content-Type": "application/json"})
    resp = json.loads(urlopen(req, timeout=180).read())  # 180s: cold-start headroom
    content = resp.get("response", "") or resp.get("thinking", "") or ""
    content, think_stripped = _strip_think(content)
    return {"choices": [{"message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "model": model,
            "x-local-vision": bool(images),
            "x-len-class": len_class, "x-num-predict": npred,
            "x-think-stripped": think_stripped,
            "x-done": resp.get("done_reason"),
            "usage": {"prompt_tokens": resp.get("prompt_eval_count"),
                      "completion_tokens": resp.get("eval_count"),
                      "prompt_tokens_details": {"cached_tokens": 0}}}

# ── Legs & chain ─────────────────────────────────────────────────────
# a tier can be a chain (several legs, tried in order). a leg = opencode or nvidia.
_LEG_COOLDOWN = {}          # {key|url: until_ts}
_QUOTA_HINTS = ("quota", "insufficient", "credit", "balance", "rate limit",
                "too many requests", "usage limit", "exceeded", "missing session")
COOLDOWN_QUOTA = 900        # quota exhausted: skip that leg for 15 minutes
COOLDOWN_ERROR = 60         # other errors: brief skip

def _leg_key(leg: dict) -> str:
    return leg["api_key_env"] + "|" + leg["url"]

def _looks_like_quota(msg: str) -> bool:
    m = msg.lower()
    return any(h in m for h in _QUOTA_HINTS)

def _call_leg(payload: dict, leg: dict, timeout: int = 120) -> dict:
    # Never forward internal bookkeeping keys upstream. Providers reject unknown parameters —
    # measured 2026-09-23: the vision leg returned HTTP 400 "Unsupported parameter(s):
    # `_forced_local`", which broke the ENTIRE vision tier (every image request failed, and the
    # legs then sat in cooldown). Keys prefixed with "_" are ours: _forced_local, _jev.
    payload = {k: v for k, v in payload.items() if not k.startswith("_")}
    key = os.environ.get(leg["api_key_env"], "")
    if not key:
        raise RuntimeError(f"{leg['api_key_env']} not set")
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + key,
               "User-Agent": "OpenAI/Python",
               "Accept": "application/json"}
    if leg.get("kind") == "opencode":
        headers.update(_OC_HDRS)          # GO without x-opencode-session → 400
    body = dict(payload, model=leg["model"])
    req = Request(leg["url"], json.dumps(body).encode(), headers)
    try:
        resp = json.loads(urlopen(req, timeout=timeout).read())
    except HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode(errors="replace")[:200]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} {detail}")
    msg = resp["choices"][0]["message"] if resp.get("choices") else None
    if msg is None:
        raise RuntimeError(f"no choices in response from {leg['model']} (HTTP 200)")
    content = msg.get("content") or msg.get("reasoning_content", "")
    tool_calls = msg.get("tool_calls")
    if not str(content).strip() and not tool_calls:
        # HTTP 200 with EMPTY content is a FAILURE, not a success (fixed 2026-09-23): without this
        # the caller receives a blank answer and the chain never tries the next leg.
        raise RuntimeError(f"empty content from {leg['model']} (HTTP 200)")
    # leg label (go/zen/nvidia) — shows at a glance whether the subscription leg was used
    url = leg["url"] or ""
    label = ("go" if "/go/" in url else "zen" if "opencode.ai" in url
             else "nvidia" if "nvidia" in url else "direct")
    out_msg = {"role": "assistant", "content": content}
    if tool_calls:
        out_msg["tool_calls"] = tool_calls      # keep tool calls; never drop them silently
    return {"choices": [{"message": out_msg,
                         "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "usage": resp.get("usage", {}),
            "model": leg["model"],
            "leg": label}

def _call_chain(payload: dict, tier: str) -> dict:
    """Try each leg in order: GO (subscription) first, then ZEN when the quota dies, then the free backup (nvidia for vision)."""
    cfg = TIERS[tier]
    legs = cfg.get("chain") or [cfg]
    last = None
    for leg in legs:
        k = _leg_key(leg)
        with _LOCK:
            if _LEG_COOLDOWN.get(k, 0) > time.time():
                continue
        try:
            return _call_leg(payload, leg)
        except Exception as e:
            last = e
            # A request-shaped error (HTTP 400/422, a validation rejection) means THIS payload
            # was unacceptable — the leg is healthy. Cooldown is for legs that are DOWN. Without
            # this distinction one unserviceable request (measured 2026-09-23: an image the
            # provider could not decode) put the flash legs in a 60 s cooldown and made every
            # later flash request return 502.
            _es = str(e)
            _req_shaped = any(t in _es for t in (
                "400", "422", "Unsupported parameter", "Validation", "Bad Request",
                "invalid_request", "Failed to load image", "Failed to decoding"))
            with _LOCK:
                if _req_shaped:
                    _LEG_COOLDOWN.pop(k, None)
                else:
                    _LEG_COOLDOWN[k] = time.time() + (
                        COOLDOWN_QUOTA if _looks_like_quota(_es) else COOLDOWN_ERROR)
    raise last or RuntimeError(f"all legs failed for tier {tier}")

def _call_local_tts(payload: dict, tier: str = "voice") -> dict:
    """Handle TTS locally via edge-tts.
    Signature MUST stay (payload, tier): DISPATCH calls handler(body, tier) for every tier —
    a one-arg handler made the whole voice tier raise TypeError and then 502 on fallback."""
    last_msg = payload["messages"][-1]["content"]
    text = last_msg if isinstance(last_msg, str) else last_msg[-1].get("text", "")
    # Return instruction for TTS — actual TTS happens via Hermes TTS tool
    return {"choices": [{"message": {"role": "assistant",
                           "content": f"[TTS would process: {text[:100]}...]"},
                         "finish_reason": "stop"}],
            "model": "edge-tts"}

# ── Research tier (Perplexity) ────────────────────────
# defaults to sonar-pro (cheap, always cites); judgement/long queries upgrade to sonar-reasoning-pro (CoT is costly).
# EMPTY-PROOF (lessons from pplx-review.py): the CoT model burns all of max_tokens thinking, then returns
# 200 OK with empty content → keep a max_tokens floor, retry once with a bigger cap, then drop to sonar-pro.
_PPLX_REASON_RE = re.compile(
    r"\b(compare|which is better|pros and cons|evaluate|review|difference|impact|why)\b"
    r"|邊個好|應該揀|評估|比較|影響", re.I)

def _pick_pplx_model(cfg: dict, text: str) -> str:
    words = len(re.findall(r"\w+", text))
    zh = len(re.findall(r"[\u4e00-\u9fff]", text))
    if (words > 40 or zh > 120) and _PPLX_REASON_RE.search(text):
        return cfg.get("reason_model", cfg["model"])
    return cfg["model"]

def _pplx_once(cfg: dict, key: str, payload: dict, model: str, max_tokens: int):
    body = dict(payload, model=model)
    body["max_tokens"] = max_tokens
    req = Request(cfg["url"], json.dumps(body).encode(),
                  {"Content-Type": "application/json",
                   "Authorization": "Bearer " + key})
    resp = json.loads(urlopen(req, timeout=180).read())
    msg = resp["choices"][0]["message"]
    return (msg.get("content") or msg.get("reasoning_content") or "").strip(), resp

def _call_pplx(payload: dict, tier: str = "research") -> dict:
    """Call Perplexity Sonar (OpenAI-compatible) + citations. Never returns empty silently."""
    cfg = TIERS.get(tier) or TIERS["research"]
    key = _get_api_key(cfg)
    if not key:
        raise ValueError("PERPLEXITY_API_KEY not set")
    text = str(payload.get("messages", [{}])[-1].get("content", ""))
    model = _pick_pplx_model(cfg, text)
    floor = 4096 if "reasoning" in model else 2048
    content, resp = _pplx_once(cfg, key, payload, model, floor)
    if not content:
        content, resp = _pplx_once(cfg, key, payload, model, 8192)
        model += "(retry-fat-cap)"
    if not content:
        content, resp = _pplx_once(cfg, key, payload, cfg["model"], 2048)
        model = cfg["model"] + "(degraded)"
    out = {"choices": [{"message": {"role": "assistant", "content": content},
                        "finish_reason": "stop"}],
           "usage": resp.get("usage", {}),
           "model": model}
    if resp.get("citations"):
        out["citations"] = resp["citations"]
    return out

DISPATCH = {
    "local": _call_ollama,
    "flash": _call_chain,
    "meta": _call_chain,      # classifier class; same chain as default
    "vision": _call_chain,    # go → zen → nvidia (free)
    "voice": _call_local_tts,
    "research": _call_pplx,
    "pplx": _call_pplx,       # legacy name, kept for compatibility
    # note: the classifier still emits "pro"/"premium"/"video" classes → no key here → do_POST
    # switches straight to the default tier (no exception fallback, no wasted round-trip).
}

class RouterHandler(BaseHTTPRequestHandler):
    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        # Minimal health endpoint for start scripts / cron keepalive.
        # tier_models = which model each tier uses, in chain order.
        if self.path == "/healthz":
            self._json(200, {"ok": True, "tiers": list(TIERS.keys()),
                             "tier_models": {t: [l["model"] for l in (c.get("chain") or [c])]
                                             for t, c in TIERS.items()},
                             "ollama_up": _ollama_up(),
                             "local_model": _LOCAL_MODEL_NAME,
                             "gpu_vram_used_mb": _gpu_vram_used_mb(),
                             "gpu_vram_error": _VRAM_ERR,
                             "stats": _health_stats()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path not in ("/v1/chat/completions", "/v1/chat/completions/render"):
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        query = body.get("messages", [{}])[-1]
        query_text = query.get("content", "")
        if isinstance(query_text, list):
            # multimodal message: extract text part
            for part in query_text:
                if part.get("type") == "text":
                    query_text = part["text"]
                    break
            else:
                query_text = str(query_text)

        # Classify query
        t_req = time.time()
        start = t_req
        tier, confidence = route_query(str(query_text))
        elapsed = round((time.time() - start) * 1000, 1)
        tier_source = "classifier"     # classifier | explicit | guard | pin
        guard_hits = []                # which guard fired (proves the decision after the fact)
        pinned_from = None

        # ── PRIVATE-FIRST GUARD: sensitive content MUST stay local ──
        # The sklearn classifier doesn't know PII/secrets. If the query smells like
        # private/sensitive data (API keys, credentials, secrets, personal redaction,
        # confidential docs), force tier=local so it NEVER leaves this machine.
        # Check the raw text AND any attached image/data parts.
        sens_txt = str(query_text).lower()
        sens_parts = []
        if isinstance(query.get("content"), list):
            for part in query.get("content"):
                if isinstance(part, dict):
                    sens_parts.append(str(part.get("text", "")).lower())
                    if part.get("type") in ("image", "image_url"):
                        sens_txt += " image-content"  # treat image as potentially private
        sens_blob = (sens_txt + " " + " ".join(sens_parts)).lower()
        # STRONG: phrases that mean a secret and nothing else -> plain substring match.
        PRIVATE_KW = (
            "api key", "apikey", "api_key", "access key", "private key",
            "aws_access", "client_secret", "bearer ", "private data",
            "discord token", "telegram token", "bot token", "access token",
            "refresh token", "my key", "my password", "my token", "my secret",
            "don't send", "don't put on cloud", "local only", "stay local",
            "not on server", "redact", "confidential", "pii", "passwd",
        )
        # AMBIGUOUS words need a possessive / assignment context, or a key SHAPE.
        # Bare "token" matched the ordinary word in "usage tokens" and forced a whole review
        # request onto the local 4B (measured 2026-09-22); bare "password" would capture
        # "write a script to hash passwords". Both are engineering text, not secrets.
        PRIVATE_RE = (
            r"\b(my|our|the|this|that|his|her)\s+(api\s+)?(key|token|secret|password|credential)\b",
            r"\b(key|token|secret|password|credential)s?\s*[:=]\s*\S",
            r"\bsk-[A-Za-z0-9_\-]{8,}", r"\bghp_[A-Za-z0-9]{10,}", r"\bgho_[A-Za-z0-9]{10,}",
            r"\bxox[baprs]-[A-Za-z0-9\-]{8,}", r"\bAKIA[0-9A-Z]{12,}",
            r"\bnvapi-[A-Za-z0-9_\-]{8,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
            # STRUCTURED PII — the gap Presidio's spike exposed: today a HK ID card number,
            # mainland ID or a phone number would go to the cloud. Context-gated so ordinary
            # long numbers do not fail-close (the guard blocks cloud quality, so precision matters).
            # Source: scripts/presidio-spike.py (2026-09-22) — pattern-only mode, 3-31 ms.
            r"(?:身份證|身份証|id card|hkid|identity card)[^\n]{0,20}?\b[a-z]{1,2}\s?\d{6}\b(?:\(?[0-9a]\)?)?",
            r"\b\d{17}[\dXx]\b",
            r"(?:電話|手機|phone|mobile|whatsapp|聯絡)[^\n]{0,20}?(?:\+?852[\s-]?)?\d{4}[\s-]?\d{4}\b",
            r"(?:信用卡|card number|卡號|credit card)[^\n]{0,20}?\b(?:\d[ -]?){13,16}\b",
        )
        has_sensitive = (any(k in sens_blob for k in PRIVATE_KW)
                         or any(re.search(p, sens_blob) for p in PRIVATE_RE))
        # body_tier must be defined here (it's also used later by PPLX pre-route)
        body_tier = (body.get("tier") or (self.headers.get("x-tier") or "").strip()).lower()
        _img_req = _has_image(body.get("messages"))
        result_forced_local = False
        if has_sensitive and body_tier not in ("local",):
            tier = "local"
            confidence = 1.0
            # attach a flag so callers know it was forced local
            result_forced_local = True

        # ── EXPLICIT TIER (body.tier / x-tier) ───────────────────────────
        # Audit 2026-09-21: body_tier was consulted ONLY by the research gate, so `tier=flash`
        # was silently answered by the local 4B. Honour a named tier for every real tier.
        # Order: PII guard (above) > explicit tier > hint gates (below).
        if not result_forced_local and body_tier in TIERS:
            tier = body_tier
            confidence = 1.0
            tier_source = "explicit"

        # ── IMAGE GUARD: a vision request never goes to a text tier ──────
        # measured 2026-09-23: a real 512x512 PNG was classified `local` (a short, simple prompt),
        # and the local call stringified the image into the prompt — so the answer was invented
        # from base64. Images go to the vision tier. An explicit `tier=local` (or the privacy
        # guard) still keeps them home, where they are now served by the local VL model.
        if _img_req and not result_forced_local and body_tier not in ("local", "vision"):
            tier, confidence, tier_source = "vision", max(confidence, 0.9), "guard:image"
            guard_hits.append("image:->vision")

        # ── FACTUAL GUARD: real-world facts never go to the local 4B ──────
        # A 4B cannot know facts and will invent them (audit: a "what is Hong Kong's population?" question -> local).
        # Short factual interrogatives go to flash (capable, cheap). Explicit fact-check
        # wording still escalates to research (paid) through the gate below.
        # Jev decides the two questions the keyword list was guessing at.
        _q_pre = str(query_text).lower()
        _is_q = _looks_like_question(str(query_text))
        _calc = bool(_PURE_CALC.match(str(query_text)))
        _jev_ok = (_JEV_GUARD_ON and not result_forced_local and not body_tier)
        if _jev_ok and tier in ("local", "meta") and _is_q and not _calc:
            jv = _jev_decide(str(query_text)[:1500], want_len=(tier == "local"), want_guards=True)
            body["_jev"] = jv            # the same call also caps the local answer
            jw, jc = jv.get("wk"), jv.get("cit")
            if jw is None and jc is None:
                _STATS["jev_fail"] += 1
            else:
                _STATS["jev_guards"] += 1
                guard_hits.append("jev(wk=%s,cit=%s)" % (
                    "?" if jw is None else round(jw, 2), "?" if jc is None else round(jc, 2)))
                if (jw or 0) > 0.7:
                    tier, confidence, tier_source = "flash", max(confidence, 0.8), "guard:jev_world_knowledge"
                    guard_hits.append("jev:needs_world_knowledge")
                if (jc or 0) > 0.7:
                    tier, confidence, tier_source = "research", max(confidence, 0.85), "guard:jev_citations"
                    guard_hits.append("jev:needs_citations")
        elif _jev_ok and tier == "local" and not _calc:
            # Not question-shaped, but the local answer still needs a length cap -> one Jev call,
            # no guard questions.
            body["_jev"] = _jev_decide(str(query_text)[:1500], want_len=True, want_guards=False)
        elif _calc:
            # Pure arithmetic: the answer is one line by construction, so neither question needs a
            # cloud round-trip. Keep it entirely local, free, and instant.
            body["_jev"] = {"len": "one-line"}
            guard_hits.append("pure_calc:no_escalation")

        FACTUAL_Q = (
            r"幾多|幾時|邊年|哪年|哪一年|幾錢|價格|人口|邊個係|係邊個",
            r"\bhow (many|much|old|long|far|big)\b", r"\bwhat year\b",
            r"\bwhen (did|was|is)\b", r"\bwho (is|was|invented)\b",
            r"\bwhat is the (population|price|cost|capital)\b",
        )
        FACT_EXEMPT = ("def ", "python", "script", "code", "function", "sql", "regex", "ffmpeg",
                       "json", "csv", "腳本", "程式", "代碼", "compile", "debug")
        _q0 = str(query_text).lower()
        _short = (len(re.findall(r"[\u4e00-\u9fff]", _q0)) <= 40
                  and len(re.findall(r"\w+", _q0)) <= 25)
        if (not result_forced_local and not body_tier and _short and not guard_hits
                and any(re.search(p, _q0) for p in FACTUAL_Q)
                and not any(k in _q0 for k in FACT_EXEMPT)):
            tier = "flash"
            confidence = max(confidence, 0.6)
            tier_source = "guard:factual_regex"   # fallback path: Jev was unavailable/not run
            guard_hits.append("factual_regex")

        # ── RESEARCH GATE (Perplexity) ────────────────────
        # every call carries a search-context floor (~$0.005–0.014), so the gate must be precise:
        #  (1) explicit: body.tier / x-tier = research (the old name pplx is still accepted) → go straight there.
        #  (2) automatic hint: hijack only when (a) the classifier would use a paid opencode tier, and
        #      (b) the text hits a "verify a specific fact" or "needs live/latest data" phrase, or
        #      (c) it is a long judgement/comparison question (>120 CJK chars or >40 English words).
        #  (3) coding / writing / translation / local-document summarisation never triggers it (CODING_EXEMPT).
        # the old version matched the substrings "analy" + "review", far too broad → even code review paid for Perplexity.
        FACT_PATTERNS = (
            r"\bfact[- ]?check\b", r"\bverify\b", r"\bis (it|this) true\b",
            r"求證", r"核實", r"查證", r"是否屬實", r"有冇根據", r"係咪真",
            r"\blatest\b", r"\bcurrent (price|status)\b", r"\bas of (today|now)\b",
            r"\bbreaking\b", r"最新消息", r"現價", r"即時資料",
            r"\bwith sources\b", r"\bcite\b", r"\bper sources\b", r"資料來源", r"附出處",
        )
        JUDGEMENT_PATTERNS = (
            r"\bwhich is better\b", r"\bcompare\b.{0,60}\b(vs|versus)\b",
            r"\bpros and cons\b", r"邊個好", r"應該揀", r"比較.{0,20}(好處|優劣)",
        )
        CODING_EXEMPT = ("def ", "python", "script", "code", "function", "sql",
                         "regex", "compile", "debug", "bug", "腳本", "程式", "代碼")
        q = str(query_text).lower()
        _words = len(re.findall(r"\w+", q))
        _zh = len(re.findall(r"[\u4e00-\u9fff]", q))
        hit_fact = any(re.search(p, q) for p in FACT_PATTERNS)
        hit_judge = ((_words > 40 or _zh > 120)
                     and any(re.search(p, q) for p in JUDGEMENT_PATTERNS)
                     and not any(k in q for k in CODING_EXEMPT))
        # safety order: forced-local (private) always wins — even an explicit research request
        # cannot override it, otherwise PII would leave through Perplexity.
        if result_forced_local:
            pass
        elif body_tier in ("research", "pplx"):
            tier = "research"
            confidence = 1.0
        elif not body_tier and not _img_req and (
                (tier in ("pro", "premium", "flash") and (hit_fact or hit_judge))
                # explicit verification / live-data wording overrides even a local classification:
                # a local 4B cannot verify facts and invents them; length-heuristic judgement queries do not override local.
                or (tier == "local" and hit_fact)):
            tier = "research"
            confidence = max(confidence, 0.7)

        # ── DEV-TASK GUARD: the 3 modality flags are crude keyword matches, so an
        # audio/video-flavoured CODING request ("ffmpeg extract audio track", "SRT align") was classified
        # voice/video and got back the TTS placeholder instead of an answer (or a 502 when
        # the handler signature broke). Dev markers win: those tiers cannot answer them.
        dev_kw = ("python", "script", "code", "function", "sql", "regex", "ffmpeg", "srt",
                  "subtitle", "compile", "debug", "bug", " api", "csv", "json",
                  "腳本", "程式", "代碼", "字幕", "對齊")
        if tier in ("voice", "video") and any(k in q for k in dev_kw):
            tier = "flash"
            confidence = max(confidence, 0.5)

        # ── SESSION MODEL PIN (prefix-cache affinity, LiteLLM-style) ──────
        # Prefix cache is keyed by (prefix, model): hit $0.003/M vs miss $0.15/M (50x, measured
        # 2026-09-22). Switching the MODEL re-bills a whole long context at miss price, so once a
        # session has been served by a cloud model it keeps that model unless the caller is
        # explicit, the classifier is confident (>=0.9), or the modality changed.
        skey = _sess_key(body)
        with _LOCK:
            _pin = _SESSION_PIN.get(skey)
        if (_pin and time.time() - _pin[2] < _PIN_TTL and not body_tier and not result_forced_local
                and _pin[0] in TIERS and _pin[1] != _tier_model(tier)
                and confidence < 0.9 and _modality(_pin[0]) == _modality(tier)):
            pinned_from, tier = tier, _pin[0]
            confidence = max(confidence, 0.7)
            tier_source = "pin"
            guard_hits.append("pin:%s->%s" % (pinned_from, tier))
            with _LOCK:
                _STATS["pins"] += 1

        # Dispatch
        handler = DISPATCH.get(tier)
        if handler is None:
            tier = "flash"  # fallback (e.g. a "video" class: that tier was removed, so use default)
            handler = _call_chain

        # ── VRAM gate for local tier ──
        # Only matters when the model is NOT resident yet (first local request
        # after boot / after the 30m keep-alive expired). If another GPU workload is
        # VRAM at that moment, loading local would silently CPU-run (slow) or
        # OOM. Fail-closed for forced-local; degrade to flash for ordinary local.
        # An IMAGE request skips this gate on purpose. The gate's trade-off (do not load a model
        # under VRAM contention, because it may silently CPU-run) is about SPEED; for an image the
        # trade-off is different — a slow local vision answer is still a CORRECT one, whereas
        # degrading the request would hand a picture to a text tier, which is the bug this guard
        # exists to prevent. Measured 2026-09-23: with a text model resident (VRAM 5902 MB > 4500)
        # `tier=local` + image was degraded to flash, i.e. straight back to a text model.
        if tier == "local" and not _img_req and not _local_model_loaded(_local_model_for(body)):
            vram = _gpu_vram_used_mb()
            if vram > LOCAL_VRAM_USED_MAX_MB:
                if result_forced_local:
                    # Make the error actionable: the usual cause is a STALE local model holding
                    # VRAM (e.g. a model no tier uses any more) with the current one not resident.
                    return self._json(503, {"error": "local tier busy (GPU VRAM full); failing closed "
                                            "— NO cloud fallback for private request",
                                            "hint": "free VRAM (ollama: unload models the tiers no longer use), "
                                                    "or prewarm %s; threshold=%dMB used=%dMB"
                                                    % (_local_model_for(body), LOCAL_VRAM_USED_MAX_MB, vram),
                                            "x-route": tier, "x-forced-local": True,
                                            "x-source": tier_source, "x-guard": guard_hits or None})
                tier = "flash"
                tier_source = "guard:vram"
                guard_hits.append("vram:%dMB>%dMB" % (vram, LOCAL_VRAM_USED_MAX_MB))
                handler = _call_chain

        try:
            body["_forced_local"] = result_forced_local   # tells _call_ollama it must not hand this to Jev (cloud)
            result = handler(body, tier)
        except Exception as e:
            # If tier fails, try flash as fallback — EXCEPT forced-local:
            # private/sensitive traffic must NEVER go to the cloud.
            if result_forced_local:
                return self._json(503, {"error": f"local: {e}. Forced-local request: NOT falling back to cloud.",
                                        "x-route": tier, "x-forced-local": True,
                                        "x-source": tier_source, "x-guard": guard_hits or None})
            try:
                result = _call_chain(body, "flash")
                tier = "flash(fallback)"
            except Exception as e2:
                return self._json(502, {"error": f"{tier}: {e}, flash fallback: {e2}",
                                        "x-route": tier, "x-forced-local": result_forced_local,
                                        "x-source": tier_source, "x-guard": guard_hits or None})

        result["x-route"] = tier
        result["x-leg"] = result.get("leg")          # go / zen / nvidia — shows at a glance whether the subscription leg was used
        result["x-confidence"] = round(confidence, 3)
        result["x-ms"] = elapsed
        result["x-forced-local"] = result_forced_local
        # ── counters + trace (2026-09-22) ──
        total_ms = round((time.time() - t_req) * 1000, 1)
        u = result.get("usage") or {}
        cinfo = _bump(tier, total_ms, u)
        if skey:
            with _LOCK:
                _SESSION_PIN[skey] = (tier, result.get("model") or _tier_model(tier), time.time())
                if len(_SESSION_PIN) > 800:      # cheap bound: drop the oldest third
                    for k in sorted(_SESSION_PIN, key=lambda x: _SESSION_PIN[x][2])[:260]:
                        _SESSION_PIN.pop(k, None)
        result["x-pinned"] = bool(pinned_from)
        result["x-source"] = tier_source
        result["x-guard"] = guard_hits or None
        result["x-cache"] = cinfo
        result["x-ms-total"] = total_ms
        _trace({"ts": round(time.time(), 1), "tier": tier, "leg": result.get("leg"),
                "model": result.get("model"), "ms_total": total_ms, "classify_ms": elapsed,
                "conf": round(confidence, 3), "source": tier_source,
                "forced_local": result_forced_local, "pinned_from": pinned_from,
                "guard": guard_hits, "len_class": result.get("x-len-class"), **cinfo})
        self._json(200, result)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    # ThreadingHTTPServer: the old single-threaded HTTPServer serialised EVERY request, so one slow
    # local generation (measured 12s) or a cloud call (up to 120s) blocked all others. Shared state
    # is guarded by _LOCK. (fixed 2026-09-23)
    # allow_reuse_address=False: on Windows the stdlib default (SO_REUSEADDR=1) lets a SECOND
    # instance bind the same port silently — two routers then serve interleaved requests with
    # divergent stats/cooldown state, and a stale-code instance looks like "my fix did nothing"
    # (observed 2026-09-23: two PIDs LISTENING on :8000). Fail loudly instead.
    ThreadingHTTPServer.allow_reuse_address = False
    server = ThreadingHTTPServer(("127.0.0.1", port), RouterHandler)
    server.daemon_threads = True
    tiers_avail = [k for k, v in TIERS.items()]
    print(f"🚀 Router v3 on :{port}")
    print(f"   Tiers: {', '.join(tiers_avail)}")
    print(f"   Default: flash = go(月費) → zen fallback (deepseek-v4.1-flash)")
    server.serve_forever()
