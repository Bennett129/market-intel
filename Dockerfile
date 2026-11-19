FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
ENV MI_CACHE_DIR=/data/cache
VOLUME /data
EXPOSE 8001
# Hosting platforms pass the port in $PORT; locally it is 8001.
CMD ["sh", "-c", "exec uv run --no-dev uvicorn --factory market_intel.api.app:create_app --host 0.0.0.0 --port ${PORT:-8001}"]
