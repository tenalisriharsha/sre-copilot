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

### Phase 3 — Metrics Correlation (Night 3) ✅
- [x] Prometheus HTTP API client (query_range, label extraction from alert)
- [x] Correlation service: pull recent metrics for the alerting pod/namespace
- [x] Tests with mocked Prometheus responses

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

### Night 3
- Built the metrics correlation stage (`src/sre_copilot/metrics/`):
  - `models.py` — `MetricPoint` / `MetricSeries` (with `latest_value`) /
    `MetricsSnapshot` dataclasses; snapshots carry an `error` field so
    failures degrade gracefully instead of raising.
  - `client.py` — `PrometheusClient`, an async httpx wrapper around
    `/api/v1/query_range` that parses matrix results. Prometheus query errors
    (HTTP 4xx with `"status": "error"` body) raise `PrometheusError`; 5xx and
    transport failures surface as `httpx.HTTPError`.
  - `correlator.py` — `MetricsCorrelator` builds a PromQL selector from the
    alert's `namespace`/`pod`/`container` labels and range-queries CPU rate,
    working-set memory, and restarts (1h increase) over a trailing window
    (default 30m / 60s step). `from_settings()` returns `None` when
    `SRE_COPILOT_PROMETHEUS_URL` is empty — correlation is opt-out via config.
- Wired the correlator into `AlertPipeline` (`metrics_for(fingerprint)`) and
  the webhook ack: `detail.metrics` now maps each fingerprint to a compact
  series summary (name, point count, latest value) or `null` when disabled.
- New settings: `SRE_COPILOT_PROMETHEUS_TIMEOUT_SECONDS` (5),
  `SRE_COPILOT_METRICS_WINDOW_MINUTES` (30), `SRE_COPILOT_METRICS_STEP_SECONDS` (60).
- Gotcha hit: Prometheus reports bad queries as HTTP 400 with a JSON error
  body, so the client must inspect the payload *before* `raise_for_status()`,
  and only when the content-type is JSON.
- Test suite: 48 tests, all passing; lint + format clean. Tests mock
  Prometheus with `httpx.MockTransport` — no live server in CI; the session
  conftest blanks `SRE_COPILOT_PROMETHEUS_URL` so the app fixture stays offline.

## Resume Point (Night 4)

Start **Phase 4 — LLM Diagnosis**:
1. Create `src/sre_copilot/llm/` with a provider-agnostic client interface
   plus an OpenAI-compatible implementation (base URL / API key / model from
   settings: `SRE_COPILOT_LLM_MODEL`, `SRE_COPILOT_LLM_API_KEY` already exist;
   add `SRE_COPILOT_LLM_BASE_URL` and a timeout if needed).
2. Prompt builder: alert + runbook excerpts (from `pipeline.retrieval_for`) +
   metrics summary (from `pipeline.metrics_for`) → structured diagnosis
   (likely cause, remediation steps) with a Pydantic output model.
3. Wire a diagnosis stage into `AlertPipeline` and the webhook ack
   (`detail.diagnosis`), disabled when no LLM API key is configured.
4. Tests with fully mocked LLM calls (fake client implementing the interface)
   — no live LLM calls in CI.
