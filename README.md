# sre-copilot

An AI on-call assistant for Kubernetes incidents. It ingests Prometheus
Alertmanager alerts via webhook, retrieves matching runbooks with a RAG
pipeline (ChromaDB + embeddings), correlates with recent metrics, and posts a
diagnosis plus suggested remediation steps to Slack.

## Project Status

**In active development** — built in public, one phase per night.
See [PROGRESS.md](PROGRESS.md) for the vision, architecture, phased build
plan, and the current resume point.

Current phase: **Phase 2 — RAG Pipeline** ✅

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
  is matched against the runbook index and the response `detail.runbooks`
  carries the top-k excerpts (runbook, section, similarity score)

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
