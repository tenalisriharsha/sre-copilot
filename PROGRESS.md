# sre-copilot — Build Progress

STATUS: IN_PROGRESS

## Vision

An AI on-call assistant for Kubernetes incidents. It ingests Prometheus
Alertmanager alerts via webhook, retrieves matching runbooks through a RAG
pipeline (ChromaDB + embeddings), correlates the alert with recent metrics,
and posts a diagnosis plus suggested remediation steps to Slack.

The goal is to cut mean-time-to-acknowledge: instead of an engineer waking
up and grepping dashboards, the first Slack message already contains the
likely cause, the relevant runbook excerpt, and concrete next steps.

## Architecture

```
Alertmanager ──webhook──▶ FastAPI service (sre-copilot)
                              │
                              ├─ 1. Ingestion: validate + normalize Alertmanager payload
                              ├─ 2. Retrieval: embed alert → query ChromaDB runbook store
                              ├─ 3. Correlation: query Prometheus HTTP API for recent metrics
                              ├─ 4. Diagnosis: LLM (pluggable provider, mocked in tests)
                              │      alert + runbook excerpts + metrics → diagnosis + remediation
                              └─ 5. Notification: post structured message to Slack (Block Kit)
```

Components:

- **Backend**: FastAPI (async, typed, auto OpenAPI docs), Python 3.12+.
- **Config**: `pydantic-settings`, 12-factor via env vars.
- **RAG store**: ChromaDB (embedded mode) + sentence-transformers embeddings.
  Runbooks are Markdown files chunked and indexed at startup.
- **Metrics correlation**: Prometheus HTTP API (`/api/v1/query_range`).
- **LLM**: provider-agnostic client interface (OpenAI-compatible), fully
  mocked in tests — no live LLM calls in CI.
- **Slack**: incoming webhook / `chat.postMessage` with Block Kit payloads.
- **Deploy**: Helm chart for Kubernetes, container image built from a
  multi-stage Dockerfile.

## Phased Build Plan

### Phase 1 — Scaffold & Core Foundation (Night 1) ✅
- [x] Project scaffold: `pyproject.toml`, package layout (`src/sre_copilot`),
      pytest setup, lint config
- [x] Settings module (`pydantic-settings`) with env-based configuration
- [x] Alertmanager webhook payload models (Pydantic v2)
- [x] `GET /healthz` liveness endpoint
- [x] `POST /api/v1/alerts` webhook ingestion endpoint (validate, normalize,
      enqueue for processing)
- [x] Tests for all of the above (pytest + httpx AsyncClient)

### Phase 2 — RAG Pipeline (Night 2)
- [ ] Runbook loader: read Markdown runbooks, chunk by section
- [ ] Embedding provider (sentence-transformers, local)
- [ ] ChromaDB collection: index runbooks at startup
- [ ] Retrieval service: alert → top-k runbook excerpts
- [ ] Sample runbooks for common K8s alerts (CrashLoopBackOff, OOMKilled, etc.)
- [ ] Tests: chunking, retrieval ranking (mocked embeddings where needed)

### Phase 3 — Metrics Correlation (Night 3)
- [ ] Prometheus HTTP API client (query_range, label extraction from alert)
- [ ] Correlation service: pull recent metrics for the alerting pod/namespace
- [ ] Tests with mocked Prometheus responses

### Phase 4 — LLM Diagnosis (Night 4)
- [ ] LLM client interface + OpenAI-compatible implementation
- [ ] Prompt builder: alert + runbook excerpts + metrics summary
- [ ] Diagnosis service returning structured output (cause, remediation steps)
- [ ] Tests with fully mocked LLM calls

### Phase 5 — Slack Notification (Night 5)
- [ ] Slack client (webhook + Block Kit message builder)
- [ ] End-to-end pipeline wiring: alert → RAG → metrics → LLM → Slack
- [ ] Tests: message formatting, mocked Slack API

### Phase 6 — Deployment & Polish (Night 6)
- [ ] Multi-stage Dockerfile
- [ ] Helm chart (Deployment, Service, ConfigMap, Secret, HPA)
- [ ] CI workflow (GitHub Actions: lint + tests)
- [ ] README quickstart, architecture diagram, demo instructions

## Log

### Night 1
- Designed architecture (above), created PROGRESS.md and README.md.
- Scaffolded the project: `pyproject.toml`, `src/sre_copilot` layout, pytest.
- Implemented settings, Alertmanager models, `/healthz`, and the
  `POST /api/v1/alerts` ingestion endpoint with an in-process alert queue.
- All tests passing (pytest).

## Resume Point (Night 2)

Start **Phase 2 — RAG Pipeline**:
1. Add `chromadb` + `sentence-transformers` deps to `pyproject.toml`.
2. Create `src/sre_copilot/rag/` (loader, chunker, store, retriever).
3. Add `runbooks/` dir with 3–5 sample Markdown runbooks.
4. Wire retrieval into the alert pipeline in `api/alerts.py`.
5. Tests for chunker + retriever (mock embeddings where heavy).
