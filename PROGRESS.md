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

### Phase 2 — RAG Pipeline (Night 2) ✅
- [x] Runbook loader: read Markdown runbooks, chunk by section
- [x] Embedding provider (sentence-transformers, local; deterministic hash
      embedder as the offline default)
- [x] ChromaDB collection: index runbooks at startup
- [x] Retrieval service: alert → top-k runbook excerpts
- [x] Sample runbooks for common K8s alerts (CrashLoopBackOff, OOMKilled,
      ImagePullBackOff, high CPU, node NotReady)
- [x] Tests: chunking, retrieval ranking (mocked embeddings where needed)

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
- Scaffolded the project: `pyproject.toml`, `src/sre_copilot` layout, pytest,
  ruff.
- Implemented settings (`config.py`), Alertmanager models (`models.py`),
  the in-process `AlertPipeline` (`pipeline.py`), `GET /healthz`, and
  `POST /api/v1/alerts`.
- Test suite: 12 tests across config, models, health and ingestion —
  all passing (`pytest`), lint clean (`ruff check` + `ruff format --check`).

### Night 2
- Built the RAG pipeline (`src/sre_copilot/rag/`):
  - `loader.py` — reads `runbooks/*.md`, chunks by `#`/`##` section
    (preamble becomes an `overview` chunk).
  - `embeddings.py` — ChromaDB-compatible embedding functions:
    `HashEmbeddingFunction` (deterministic, offline, the default backend;
    splits CamelCase identifiers like `KubePodCrashLooping` into tokens) and
    `SentenceTransformerEmbeddingFunction` (real local model, lazy import).
    Backend selected via `SRE_COPILOT_EMBEDDING_BACKEND`.
  - `store.py` — `RunbookStore` over a ChromaDB collection (persistent in
    prod via `SRE_COPILOT_CHROMA_PERSIST_DIR`, ephemeral client in tests),
    cosine space, upsert + top-k query returning `RetrievalHit`s.
  - `retriever.py` — `RunbookRetriever` composes the query from alertname /
    severity / namespace / pod / summary, indexes runbooks at startup when
    the collection is empty.
- Wrote 5 sample runbooks in `runbooks/` (CrashLoopBackOff, OOMKilled,
  ImagePullBackOff, high CPU, node NotReady).
- Wired retrieval into `AlertPipeline.process()` and the webhook ack:
  `detail.runbooks` now maps each fingerprint to its top-k hits
  (runbook, section, score).
- Gotchas hit: ChromaDB 1.5 requires embedding functions to implement
  `name()`/`get_config()`/`build_from_config()` (subclass its
  `EmbeddingFunction`), its wrapper returns numpy arrays (test equality
  needs normalization), and `EphemeralClient` shares process-wide state
  (tests use distinct collection names).
- Test suite: 33 tests, all passing; lint clean.

## Resume Point (Night 3)

Start **Phase 3 — Metrics Correlation**:
1. Create `src/sre_copilot/metrics/` with a Prometheus HTTP API client
   (`/api/v1/query_range`, async httpx) and a correlation service that
   extracts pod/namespace labels from the alert and pulls recent metrics
   (CPU, memory, restarts).
2. Wire the correlation stage into `AlertPipeline` behind settings
   (`SRE_COPILOT_PROMETHEUS_URL`), degrading gracefully when Prometheus is
   unreachable.
3. Tests with mocked Prometheus responses (httpx MockTransport or respx-style
   monkeypatching) — no live Prometheus in CI.
