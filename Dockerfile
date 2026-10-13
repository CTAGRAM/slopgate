FROM node:24-slim AS node

FROM python:3.12-slim
# Node and an unmodified anti-slop checkout let the arena run anti-slop as a contender.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && git clone --depth 1 https://github.com/peakoss/anti-slop /opt/anti-slop
ENV ANTISLOP_DIR=/opt/anti-slop UV_COMPILE_BYTECODE=1

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY slopgate ./slopgate
RUN uv sync --frozen --no-dev
COPY eval/results ./eval/results

EXPOSE 8080
CMD ["uv", "run", "--no-sync", "uvicorn", "slopgate.server:app", "--host", "0.0.0.0", "--port", "8080"]
