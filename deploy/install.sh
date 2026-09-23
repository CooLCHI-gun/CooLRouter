#!/usr/bin/env sh
# CooLRouter — one-command local install (Linux / macOS).
#
#   ./deploy/install.sh                 install into ./coolrouter-run and start it
#   ./deploy/install.sh --systemd       also install a systemd --user unit
#
# Idempotent: re-running reuses the existing .env and restarts nothing that is already healthy.
# Do not pipe this script's output if you background it further; it detaches the daemon itself.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUN=${COOLROUTER_HOME:-$ROOT/coolrouter-run}
PORT=${COOLROUTER_PORT:-8000}

PY=$(command -v python3 || command -v python || true)
[ -n "$PY" ] || { echo "no python3/python on PATH — install Python 3.9+ first"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || { echo "Python 3.9+ required (found $PY)"; exit 1; }

mkdir -p "$RUN/logs"
cp "$ROOT/router/router-proxy.py" "$RUN/router-proxy.py"
[ -f "$RUN/.env" ] || { cp "$ROOT/deploy/.env.example" "$RUN/.env"; echo "wrote $RUN/.env — add your keys there"; }

if curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    echo "already healthy on :$PORT"
else
    # Detach properly: the daemon must not inherit this shell's stdout, or a caller that pipes
    # the installer (`sh install.sh | tail`) blocks forever waiting for EOF (measured 2026-09-23).
    if command -v setsid >/dev/null 2>&1; then LAUNCH="setsid"; else LAUNCH="nohup"; fi
    ( cd "$RUN" && $LAUNCH "$PY" -u router-proxy.py "$PORT" >> logs/router.log 2>&1 </dev/null &
      echo $! > "$RUN/router.pid" )
    i=0
    while [ $i -lt 20 ]; do
        curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break
        i=$((i + 1)); sleep 1
    done
    curl -sf "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 \
        || { echo "router did not come up — see $RUN/logs/router.log"; exit 1; }
    echo "router listening on :$PORT (pid $(cat "$RUN/router.pid"))"
fi

curl -s "http://127.0.0.1:$PORT/healthz" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print("  ok:", d.get("ok"), "| tiers:", ", ".join(d.get("tiers", []))); print("  local engine reachable:", d.get("ollama_up"))'

if [ "${1:-}" = "--systemd" ]; then
    UNIT="$HOME/.config/systemd/user/coolrouter.service"
    mkdir -p "$(dirname "$UNIT")"
    sed -e "s|@RUN@|$RUN|g" -e "s|@PORT@|$PORT|g" "$ROOT/deploy/coolrouter.service" > "$UNIT"
    systemctl --user daemon-reload && systemctl --user enable --now coolrouter.service
    echo "systemd --user unit installed: $UNIT"
fi

cat <<'EOT'

Next: point any OpenAI-compatible client at it.

  curl -s http://127.0.0.1:8000/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"what is 2+2"}]}' | head -c 400

The response carries the routing decision alongside the answer (see docs/router-architecture.md).
EOT
