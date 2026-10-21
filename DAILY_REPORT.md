# sre-copilot — Final Report

## What it is

An AI on-call assistant for Kubernetes incidents. It receives Prometheus
Alertmanager webhooks, retrieves matching runbook excerpts through a RAG
pipeline, correlates the alert with recent Prometheus metrics, asks an LLM
for a diagnosis and remediation steps, and posts the result to Slack —
end to end, with every network stage degrading gracefully instead of
failing the webhook.

## What was built

**Phase 1 — Foundation.** FastAPI app factory, `pydantic-settings`
configuration (every setting is an `SRE_COPILOT_*` env var), Alertmanager
webhook payload models, `GET /healthz`, `POST /api/v1/alerts`.

**Phase 2 — Runbook RAG.** Markdown runbooks (CrashLoopBackOff, OOMKilled,
ImagePullBackOff, high CPU, node NotReady) chunked by section and indexed
into ChromaDB at startup. Two embedding backends: a deterministic offline
hash embedder (default, used in tests) and a real `sentence-transformers`
backend behind an optional extra. Retrieval composes a query from the
alert's name/severity/namespace/pod/summary and returns top-k scored
excerpts.

**Phase 3 — Metrics correlation.** An async Prometheus HTTP API client
builds a PromQL selector from the alert's labels and range-queries CPU,
memory, and restarts over a trailing window. Degrades to an empty snapshot
with the error recorded if Prometheus is unreachable or the alert lacks
identifying labels.

**Phase 4 — LLM diagnosis.** A provider-agnostic client for OpenAI-compatible
`/chat/completions` APIs in JSON mode. A prompt builder assembles the alert,
runbook excerpts, and metrics summary; the response is validated against a
`Diagnosis` schema (cause, confidence, ordered remediation steps). Opt-in:
disabled entirely when no API key is configured.

**Phase 5 — Slack notification.** Builds a Block Kit message (color-coded by
severity, header, context line, diagnosis, top runbook excerpt, metrics
summary) and posts it to an incoming webhook. Opt-in: disabled when no
webhook URL is configured.

**Review follow-up.** The three network stages (metrics, LLM, Slack) were
moved to background tasks with bounded concurrency so Alertmanager's webhook
gets a fast ack; added retry dedupe per (fingerprint, status, startsAt), a
`GET /api/v1/alerts/{fingerprint}` status endpoint, backpressure (`503` once
too many alerts are pending), and TTL/size-bounded in-memory state.

**Phase 6 — Deployment.** A multi-stage Dockerfile (non-root, healthcheck)
and a Helm chart (Deployment/Service/ConfigMap/Secret/HPA). The chart
defaults to a single replica because retry-dedupe state lives in process
memory.

## Test results

131 tests passing, `ruff check` and `ruff format --check` clean. Every
external dependency — ChromaDB embeddings, Prometheus, the LLM API, Slack —
is faked or mocked (`httpx.MockTransport`, fake client protocols); no live
network calls happen in CI. The Docker image and Helm chart were verified by
actually building/running the image and rendering the chart with `helm lint`
and `helm template` (see PROGRESS.md's Night 6 entry), not just by reading
the files.

## Known limitations

- **Single-process state.** Retry dedupe, per-alert results, and the
  pending-alert queue live in memory. A restart forgets them, and running
  more than one replica without shared state (e.g. Redis) means a retry
  routed to a different pod isn't recognized as a duplicate.
- **No persistent runbook index across restarts in Docker/Helm.** The chart
  mounts an `emptyDir` for ChromaDB's data; it's rebuilt from the bundled
  runbooks at every startup, which is fine for a handful of Markdown files
  but wouldn't scale to a large runbook corpus without a real volume.
- **Single LLM provider shape.** Only OpenAI-compatible `/chat/completions`
  JSON mode is implemented; other providers would need a new `LLMClient`
  implementation.
- **No authentication on the webhook.** `POST /api/v1/alerts` trusts
  whatever hits it; a real deployment needs a network policy, mTLS, or a
  shared secret in front of it.
- **No live LLM/Slack/Prometheus smoke test.** Everything is verified
  against fakes; nothing in this repo confirms the prompt actually produces
  a good diagnosis from a real model, or that a real Slack workspace renders
  the Block Kit payload as intended.

## Future ideas

- Shared state (Redis) for dedupe and per-alert results, to allow multiple
  replicas and an HPA with `maxReplicas > 1`.
- A persistent volume for the ChromaDB index in the Helm chart, for larger
  runbook sets.
- A feedback loop: let an on-call engineer mark a diagnosis as helpful or
  not, and use that signal to re-rank runbook retrieval over time.
- Additional LLM provider adapters (e.g. Anthropic's native API) alongside
  the OpenAI-compatible client.
- A lightweight auth layer (shared-secret header or mTLS) in front of the
  webhook for real deployments.
