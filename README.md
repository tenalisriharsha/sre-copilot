# sre-copilot

An AI on-call assistant for Kubernetes incidents. It ingests Prometheus
Alertmanager alerts via webhook, retrieves matching runbooks with a RAG
pipeline (ChromaDB + embeddings), correlates with recent metrics, and posts a
diagnosis plus suggested remediation steps to Slack.

## Project Status

**In active development** — built in public, one phase per night.
See [PROGRESS.md](PROGRESS.md) for the vision, architecture, phased build
plan, and the current resume point.

Current phase: **Phase 3 — Metrics Correlation** ✅

## Stack

- FastAPI + Pydantic v2 (backend, typed config)
- ChromaDB + sentence-transformers (runbook RAG)
- Prometheus HTTP API (metrics correlation)
- Pluggable LLM client, fully mocked in tests
- Slack Block Kit notifications
- Helm chart deployment

## Quickstart (dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
uvicorn sre_copilot.main:app --reload
```

Endpoints so far:

- `GET /healthz` — liveness probe
- `POST /api/v1/alerts` — Alertmanager webhook receiver; each accepted alert
  is matched against the runbook index and correlated with recent Prometheus
  metrics. The response `detail.runbooks` carries the top-k excerpts (runbook,
  section, similarity score) and `detail.metrics` a per-series summary (name,
  point count, latest value) — `null` when correlation is disabled

## Runbook RAG

Markdown runbooks live in [`runbooks/`](runbooks/) (CrashLoopBackOff,
OOMKilled, ImagePullBackOff, high CPU, node NotReady). At startup they are
chunked by section and indexed into a persistent ChromaDB collection
(`SRE_COPILOT_CHROMA_PERSIST_DIR`, default `.chroma/`).

Embedding backend is selectable via `SRE_COPILOT_EMBEDDING_BACKEND`:

- `hash` (default) — deterministic hashing embedder, no model download,
  works offline; used in tests
- `sentence-transformers` — real local embeddings (`SRE_COPILOT_EMBEDDING_MODEL`,
  default `all-MiniLM-L6-v2`)

Retrieval fan-out per alert is controlled by `SRE_COPILOT_RETRIEVAL_TOP_K`
(default 3).

## Metrics correlation

Each alert is correlated with recent Prometheus metrics
(`src/sre_copilot/metrics/`): the correlator builds a PromQL label selector
from the alert's `namespace`/`pod`/`container` labels and runs range queries
for CPU usage, working-set memory, and container restarts over a trailing
window.

Settings:

- `SRE_COPILOT_PROMETHEUS_URL` — base URL of the Prometheus HTTP API
  (default `http://prometheus:9090`); set empty to disable correlation
- `SRE_COPILOT_PROMETHEUS_TIMEOUT_SECONDS` (default 5)
- `SRE_COPILOT_METRICS_WINDOW_MINUTES` (default 30) and
  `SRE_COPILOT_METRICS_STEP_SECONDS` (default 60) — query window and resolution

Correlation degrades gracefully: alerts without identifying labels skip the
queries, and an unreachable Prometheus yields an empty snapshot with the error
recorded — the webhook ack is never blocked by a Prometheus outage.
