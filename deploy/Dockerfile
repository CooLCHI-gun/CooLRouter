# CooLRouter — container image for the routing core.
#
# The core is standard-library Python plus one optional local module, so the image stays thin.
# Note: the local tier talks to an Ollama endpoint (ROUTER_OLLAMA_URL). Inside a container
# 127.0.0.1 is the container itself, so set ROUTER_OLLAMA_URL to a reachable host — e.g.
# http://host.docker.internal:11434 with the compose file in this directory.
FROM python:3.12-slim

WORKDIR /app
COPY router/router-proxy.py /app/router-proxy.py

# The core writes its trace to ../logs and reads ../.env relative to the source file.
RUN mkdir -p /logs
COPY deploy/.env.example /.env

EXPOSE 8000
ENV PYTHONUNBUFFERED=1
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4).status==200 else 1)"

CMD ["python", "-u", "/app/router-proxy.py", "8000"]
