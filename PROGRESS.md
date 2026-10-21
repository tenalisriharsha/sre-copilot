# sre-copilot — Build Progress

STATUS: COMPLETE

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

### Phase 4 — LLM Diagnosis (Night 4) ✅
- [x] LLM client interface + OpenAI-compatible implementation
- [x] Prompt builder: alert + runbook excerpts + metrics summary
- [x] Diagnosis service returning structured output (cause, remediation steps)
- [x] Tests with fully mocked LLM calls

### Phase 5 — Slack Notification (Night 5) ✅
- [x] Slack client (webhook + Block Kit message builder)
- [x] End-to-end pipeline wiring: alert → RAG → metrics → LLM → Slack
- [x] Tests: message formatting, mocked Slack API

### Phase 6 — Deployment & Polish (Night 6) ✅
- [x] Multi-stage Dockerfile
- [x] Helm chart (Deployment, Service, ConfigMap, Secret, HPA)
- [x] CI workflow (GitHub Actions: lint + tests, Docker build, Helm lint/template)
- [x] README quickstart, architecture diagram, demo instructions

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

### Night 4
- Built the LLM diagnosis stage (`src/sre_copilot/llm/`):
  - `models.py` — `Diagnosis` Pydantic model: `likely_cause`,
    `confidence` (low/medium/high), `remediation_steps`.
  - `client.py` — `LLMClient` protocol (`complete_json(system, user) -> str`,
    the minimal seam tests fake) and `OpenAICompatibleClient`, an async httpx
    wrapper for OpenAI-compatible `/chat/completions` APIs in JSON mode
    (`response_format: json_object`, bearer auth, temperature 0.2). All
    transport/HTTP/malformed-payload failures raise `LLMError`.
  - `prompts.py` — `build_messages(alert, hits, snapshot)` → (system, user);
    the system prompt pins the Diagnosis JSON schema, the user prompt embeds
    the alert (labels + annotations as JSON), runbook excerpts (title,
    section, score, text) and a per-series metrics summary. Missing runbooks,
    disabled metrics and metrics errors each degrade to an explicit sentence.
  - `diagnosis.py` — `DiagnosisService` builds the prompt, calls the client
    and validates the response with `Diagnosis.model_validate_json`;
    LLM/validation failures re-raise as `LLMError`. `from_settings()` returns
    `None` when `SRE_COPILOT_LLM_API_KEY` is unset — diagnosis is opt-in.
- Wired the diagnoser into `AlertPipeline` (`diagnosis_for(fingerprint)`),
  `create_app` and the webhook ack: `detail.diagnosis` maps each fingerprint
  to the structured diagnosis or `null`. An `LLMError` is logged and recorded
  as "no diagnosis" — the alert is still accepted and queued.
- New settings: `SRE_COPILOT_LLM_BASE_URL` (`https://api.openai.com/v1`),
  `SRE_COPILOT_LLM_TIMEOUT_SECONDS` (30).
- Gotcha hit: httpx normalizes `base_url` with a trailing slash — compare
  `str(client.base_url)` in tests, not the `URL` object against a string.
- Test suite: 68 tests, all passing; lint + format clean. LLM tests use
  `httpx.MockTransport` for the client and a `FakeLLMClient` implementing the
  protocol for the service/pipeline — no live LLM calls in CI.

### Night 5
- Built the Slack notification stage (`src/sre_copilot/slack/`):
  - `client.py` — `SlackWebhookClient`, an async httpx wrapper for incoming
    webhooks. Transport/HTTP failures raise `SlackError`, and so does a 200
    whose body is not `ok` (Slack returns error descriptions with a 200).
  - `messages.py` — `build_message(alert, hits, snapshot, diagnosis)` →
    webhook payload: plain-text fallback plus one attachment whose `color`
    sidebar encodes severity (critical→danger, warning→warning,
    resolved→good, else `#439FE0`). Blocks: header (status + alertname,
    truncated to Slack's 150-char limit, icon included), context line
    (severity/namespace/pod/fingerprint), summary annotation, diagnosis
    (cause, confidence, numbered remediation steps), top runbook excerpt
    (title, section, score; truncated to 600 chars) and a per-series metrics
    summary. Missing diagnosis/runbooks/metrics and metrics errors each
    degrade to an explicit fallback sentence.
  - `notifier.py` — `SlackNotifier` builds the message and posts it;
    `from_settings()` returns `None` when `SRE_COPILOT_SLACK_WEBHOOK_URL` is
    unset — the stage is opt-in.
- Wired the notifier into `AlertPipeline` (final stage, after diagnosis),
  `create_app` and the webhook ack: `detail.slack` maps each fingerprint to
  `{"delivered": true|false}` or `null` when disabled. A `SlackError` is
  logged and recorded as `delivered: false` — ingestion is never blocked.
- New setting: `SRE_COPILOT_SLACK_TIMEOUT_SECONDS` (5).
- Gotchas hit: httpx serializes `json=` compactly (assert parsed JSON in
  tests, not raw bytes), Slack header blocks cap at 150 chars including the
  emoji code, and context blocks have `elements` instead of `text` (guard
  block traversal in tests).
- Test suite: 92 tests, all passing; lint + format clean. Slack tests use
  `httpx.MockTransport` for the client and a `FakeSlackClient` for the
  notifier/pipeline — no live Slack calls in CI. This completes the
  end-to-end pipeline: alert → RAG → metrics → LLM → Slack.

### Review follow-up
- The slow stages (metrics, LLM, Slack) now run in background tasks with
  bounded concurrency; the webhook acks after runbook retrieval. Retried
  deliveries are deduplicated per (fingerprint, status, startsAt), and
  per-alert state is bounded by a TTL and a size cap. New endpoint:
  `GET /api/v1/alerts/{fingerprint}`. See README "Background processing".
- `sentence-transformers` moved to the optional `embeddings` extra;
  `constraints.txt` pins the dependency tree and CI installs from it.

### Night 6
- Built the deployment stage (Phase 6, final phase):
  - `Dockerfile` — multi-stage build: a `builder` stage installs the package
    with `pip install -c constraints.txt .` into `/install`, a slim
    `python:3.12-slim` `runtime` stage copies that tree, runs as a non-root
    user (`sre-copilot`, uid 10001), bakes in `runbooks/`, and starts
    `uvicorn sre_copilot.main:app`. A `HEALTHCHECK` hits `/healthz`.
    `.dockerignore` keeps the build context small.
  - `chart/sre-copilot/` — Helm chart: `Deployment` (ConfigMap + Secret env
    vars, liveness/readiness probes on `/healthz`, an `emptyDir` for
    `/app/.chroma`), `Service`, `ConfigMap` (non-secret settings),
    `Secret` (LLM API key, Slack webhook URL; `secret.existingSecret` to
    bring your own instead) and an opt-in `HorizontalPodAutoscaler`.
    `replicaCount` and `autoscaling.maxReplicas` default to 1, since
    retry-dedupe state is per-process (documented in the chart's `NOTES.txt`
    and the README).
  - CI (`.github/workflows/ci.yml`): added a `docker` job (buildx build, no
    push) and a `helm` job (`helm lint` + `helm template`) alongside the
    existing lint/test job.
  - README: architecture diagram (moved from this file), a "Deployment"
    section (Docker + Helm usage), and a "Demo" section with a copy-pasteable
    curl example.
- Verified for real, not just by reading the YAML: built the Docker image,
  ran it (`docker run -p 8000:8000 -e SRE_COPILOT_PROMETHEUS_URL=`), confirmed
  `/healthz` and a full `POST /api/v1/alerts` round trip work and that the
  container's `HEALTHCHECK` reports `healthy`; rendered the Helm chart with
  `helm lint` and `helm template` under default values and under
  `autoscaling.enabled=true` + `secret.existingSecret` to check both
  conditional branches. Docker and Helm aren't invoked from the test suite
  (CI installs them in dedicated jobs instead), so `tests/test_deployment.py`
  adds structural assertions (multi-stage, non-root, `HEALTHCHECK`, chart
  values/templates) that run in the regular `pytest` job.
- New dev dependency: `pyyaml` (for `test_deployment.py`); regenerated
  `constraints.txt` with `uv pip compile`.
- Test suite: 131 tests, all passing; lint + format clean.

This completes the planned build. See `DAILY_REPORT.md` for the project
summary.

## Build history (moved from README)

Built one phase per night, Phase 1 through Phase 6 above.
