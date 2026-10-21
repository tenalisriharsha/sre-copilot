# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml constraints.txt README.md ./
COPY src ./src

RUN pip install --no-cache-dir --prefix=/install -c constraints.txt .

FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin sre-copilot

COPY --from=builder /install /usr/local

WORKDIR /app
COPY runbooks ./runbooks

ENV SRE_COPILOT_CHROMA_PERSIST_DIR=/app/.chroma \
    SRE_COPILOT_RUNBOOKS_DIR=/app/runbooks \
    PYTHONUNBUFFERED=1

RUN mkdir -p /app/.chroma && chown -R sre-copilot:sre-copilot /app

USER sre-copilot

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=3)" || exit 1

ENTRYPOINT ["uvicorn", "sre_copilot.main:app", "--host", "0.0.0.0", "--port", "8000"]
