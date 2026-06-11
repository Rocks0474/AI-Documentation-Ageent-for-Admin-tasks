# Single image — deploys to LOCAL, GCP, or AWS via environment variables only.
# Cloud SDKs are optional extras; select them at build time with INSTALL_EXTRAS,
# e.g. `--build-arg INSTALL_EXTRAS=[gcp]` or `[aws]`. No code changes per cloud.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
ARG INSTALL_EXTRAS=""
COPY pyproject.toml README.md ./
COPY adapters ./adapters
COPY agents ./agents
COPY schemas ./schemas
COPY pii_gateway ./pii_gateway
COPY orchestration ./orchestration
COPY config ./config
COPY scripts ./scripts
COPY main.py ./

RUN pip install ".${INSTALL_EXTRAS}"

# Default cloud target; override at runtime (docker-compose / deployment env).
ENV CLOUD_TARGET=LOCAL \
    RUN_MODE=server

CMD ["python", "main.py"]
