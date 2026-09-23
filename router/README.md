# router/ — the routing core

`router-proxy.py` is the implementation behind the tiered routing described in the root README.
It is a single file of Python standard library code (`http.server` + `urllib`, plus PyYAML), ~865
lines, with no framework and no daemon.

Deep documentation: [`../docs/router-architecture.md`](../docs/router-architecture.md) — architecture
diagram, component structure, the 13-stage decision chain, tier table, response contract, guards,
and the known failure modes.

## Run

```bash
python3 router/router-proxy.py 8000
# → listens on http://127.0.0.1:8000/v1  (OpenAI-compatible)
```

It binds `127.0.0.1` only. It is a personal gateway, not a public endpoint.

## Configuration

Endpoints, model names and the environment-variable *names* are a table in the source (`TIERS`).
Secret **values** are read from the environment (or a gitignored env file loaded at startup) and
never appear in the code — this was a real incident: an early copy of this file carried a hardcoded
key as an `os.environ.get(...)` default, and that copy leaked into a skill directory. A secret must
never be the default value of anything; the code should fail closed instead.

| Variable | Used by |
|---|---|
| `OPENCODE_GO_API_KEY` | default tier, leg 1 (subscription) |
| `OPENCODE_ZEN_API_KEY` | default tier, leg 2 (metered) |
| `PERPLEXITY_API_KEY` | research tier (cited search) |
| `NVIDIA_API_KEY` | vision tier, leg 3 (free rescue) |
| `OPENROUTER_API_KEY` | typed-decision guards (optional; guards are skipped without it) |

## External dependency: the classifier

The proxy imports one function from a sibling module:

```python
from memory_enhancer import route_query
tier, confidence = route_query(text)      # tier: str, confidence: float 0..1
```

That classifier — a trained logistic-regression model over embedding vectors plus three modality
flags — belongs to the private profile this proxy was extracted from and is not published here. Any
module satisfying the signature above works: return one of the tier names in `TIERS`, and a
confidence you are willing to have quoted in `x-confidence`.

If the classifier is unavailable, the proxy does not crash — it degrades to a legacy centroid
fallback, and the tell is visible in the response: confidence drops to roughly `0.12–0.20` instead
of `≥ 0.8`. That silent downgrade is documented in the architecture notes because it is exactly the
kind of failure that looks like "routing is working" while every request is being misrouted.

## Local tier

Expects an OpenAI-compatible local runtime (the reference setup uses Ollama on `127.0.0.1:11434`).
The local model must be a **non-thinking** instruct model: with a reasoning-distilled model the
generation cap is consumed inside the chain-of-thought and the answer comes back empty.
