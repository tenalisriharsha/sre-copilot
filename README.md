# sre-copilot

An AI on-call assistant for Kubernetes incidents. It ingests Prometheus
Alertmanager alerts via webhook, retrieves matching runbooks with a RAG
pipeline (ChromaDB + embeddings), correlates with recent metrics, and posts a
diagnosis plus suggested remediation steps to Slack.

## Project Status

**In active development** — built in public, one phase per night.
See [PROGRESS.md](PROGRESS.md) for the vision, architecture, phased build
plan, and the current resume point.

Current phase: **Phase 1 — Scaffold & Core Foundation** ✅

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
- `POST /api/v1/alerts` — Alertmanager webhook receiver
