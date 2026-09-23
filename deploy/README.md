# Deploying CooLRouter

The routing core is a single Python file with no third-party dependencies:
[`router/router-proxy.py`](../router/router-proxy.py). Deployment is therefore "run it" — everything
in this directory is a convenience wrapper around that one command.

| Path | Command | Good for |
|:--|:--|:--|
| Local script | `sh deploy/install.sh` | Linux / macOS, single host |
| Local script | `./deploy/install.ps1` | Windows |
| Container | `docker compose -f deploy/docker-compose.yml up --build` | isolation, remote hosts |
| Hermes Agent | paste [`hermes/config-snippet.yaml`](hermes/config-snippet.yaml) | serving an agent through it |

## 1. Local install

```sh
git clone https://github.com/CooLCHI-gun/CooLRouter
cd CooLRouter
cp deploy/.env.example .env     # add only the keys you actually have
sh deploy/install.sh            # installs into ./coolrouter-run, starts it, verifies /healthz
```

The script is idempotent: it reuses an existing `.env`, and if something is already answering on the
port it leaves it alone. It installs nothing outside `COOLROUTER_HOME` (default `./coolrouter-run`),
detaches the daemon so it survives the shell, and then reports what it found:

```
router listening on :8000 (pid 4821)
  ok: True | tiers: local, flash, meta, vision, voice, research
  local engine reachable: True
```

Add `--systemd` to install a `systemd --user` unit from
[`coolrouter.service`](coolrouter.service). On Windows, `./deploy/install.ps1` does the same job and
`-Startup` registers it to start at logon.

## 2. Container

```sh
cp deploy/.env.example .env
docker compose -f deploy/docker-compose.yml up --build
```

One constraint worth stating plainly: the local tier talks to an Ollama endpoint. Inside a container
`127.0.0.1` is the container itself, so the compose file points `ROUTER_OLLAMA_URL` at
`host.docker.internal` to reach an Ollama running on the host. Without that, the container serves
the cloud tiers only — it will still run, it will simply never choose the local one.

## 3. Hermes Agent

The router speaks the OpenAI chat-completions API, so it is wired in as an ordinary provider — no
plugin and no code change. Paste [`hermes/config-snippet.yaml`](hermes/config-snippet.yaml) into
`config.yaml` and point a model at it:

```sh
hermes config set model.default coolrouter/deepseek-v4.1-flash
```

[`hermes-plugin/coolrouter-health/`](hermes-plugin/coolrouter-health/) is optional and separate: an
observer-only plugin that logs a warning when the router stops answering, so a silent fall back to
cloud providers does not go unnoticed. It never injects text into the prompt.

## What the response carries

The routing decision travels in the response **body**, as extra top-level keys beside the standard
OpenAI fields:

`x-route` · `x-leg` · `x-confidence` · `x-ms` · `x-ms-total` · `x-guard` · `x-source` ·
`x-forced-local` · `x-local-vision` · `x-len-class` · `x-num-predict` · `x-pinned` ·
`x-think-stripped` · `x-cache` · `x-done`

The full contract, including the failure modes, is in
[`docs/router-architecture.md`](../docs/router-architecture.md).

## Configuration

Six environment variables are read; everything else is a constant in the source.

| Variable | Effect when set | Effect when absent |
|:--|:--|:--|
| `OPENCODE_ZEN_API_KEY` | primary subscription leg answers | leg skipped |
| `OPENCODE_GO_API_KEY` | fallback subscription leg answers | leg skipped |
| `NVIDIA_API_KEY` | free backup leg for the vision tier | leg skipped |
| `PERPLEXITY_API_KEY` | research tier answers | research tier returns an error |
| `OPENROUTER_API_KEY` | classifier escalation check runs | check skipped |
| `ROUTER_OLLAMA_URL` | local engine is looked for there | `http://127.0.0.1:11434` |
| `ROUTER_LOCAL_MODEL` | that model serves the local tier | `gemma3:4b` |
| `ROUTER_LOCAL_VISION_MODEL` | that model serves local image requests | a Qwen3-VL GGUF tag |

The VRAM threshold that decides whether the local tier may be loaded is still a constant
(`LOCAL_VRAM_USED_MAX_MB`, 4500) — edit the source if your card differs.

## Verification

```sh
curl -s http://127.0.0.1:8000/healthz            # liveness + tier map + VRAM state
python3 router/router-conformance.py             # 11 routing rows, end to end
python3 router/test-router-p0.py                 # 7 regression rows for the fixed defects
```

The conformance suite asserts behaviour, not configuration: it sends real requests and checks the
routing decision and the answer that comes back. Run it after any change to the core.

## What is not in this repository

- **The trained intent classifier.** The core runs without it, using a deterministic
  shape-based fallback; routing stays correct, the cheap-task optimisation is coarser.
- **Local state.** The trace log, session pins and stats are runtime artefacts, written beside the
  process (`../logs/`), not shipped.
- **Secrets.** No key, no endpoint credential, no personal configuration. `.env` is yours.
