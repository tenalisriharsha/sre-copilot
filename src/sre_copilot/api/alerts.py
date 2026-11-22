"""Alertmanager webhook ingestion endpoint."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from sre_copilot.llm.models import Diagnosis
from sre_copilot.metrics.models import MetricsSnapshot
from sre_copilot.models import AlertAck, AlertStatus, WebhookPayload
from sre_copilot.pipeline import AlertPipeline
from sre_copilot.rag.documents import RetrievalHit

router = APIRouter(prefix="/api/v1", tags=["alerts"])

_OUTCOME_RANK = {"scheduled": 2, "deferred": 1, "duplicate": 0}


def _metrics_summary(snapshot: MetricsSnapshot | None) -> dict[str, Any] | None:
    """Compact JSON view of a snapshot for the webhook ack (None if disabled)."""
    if snapshot is None:
        return None
    return {
        "window_minutes": snapshot.window_minutes,
        "error": snapshot.error,
        "series": [
            {
                "name": series.name,
                "points": len(series.points),
                "latest": series.latest_value,
            }
            for series in snapshot.series
        ],
    }


def _runbooks_summary(hits: list[RetrievalHit]) -> list[dict[str, Any]]:
    return [
        {
            "runbook": hit.chunk.runbook,
            "section": hit.chunk.section,
            "score": round(hit.score, 4),
        }
        for hit in hits
    ]


def _diagnosis_summary(diagnosis: Diagnosis | None) -> dict[str, Any] | None:
    return diagnosis.model_dump() if diagnosis else None


def _slack_summary(delivered: bool | None) -> dict[str, Any] | None:
    return {"delivered": delivered} if delivered is not None else None


@router.post("/alerts", status_code=status.HTTP_202_ACCEPTED)
async def receive_alerts(payload: WebhookPayload, request: Request) -> AlertAck:
    """Receive an Alertmanager webhook and enqueue its alerts for processing."""
    pipeline: AlertPipeline = request.app.state.pipeline
    submissions = pipeline.submit(payload)
    deferred = [s.fingerprint for s in submissions if s.outcome == "deferred"]
    if deferred:
        # Alertmanager retries on 5xx. Alerts already scheduled from this
        # group are deduplicated on the retry, so only the deferred ones run.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "pipeline at capacity, retry later", "deferred": deferred},
        )
    fingerprints = [s.fingerprint for s in submissions]
    # A batch can contain more than one alert for the same fingerprint; keep
    # the most informative outcome (scheduled beats deferred/duplicate)
    # instead of letting a later submission silently overwrite an earlier one.
    processing: dict[str, str] = {}
    runbooks: dict[str, list[dict[str, Any]]] = {}
    for s in submissions:
        if (
            s.fingerprint not in processing
            or _OUTCOME_RANK[s.outcome] > _OUTCOME_RANK[processing[s.fingerprint]]
        ):
            processing[s.fingerprint] = s.outcome
            runbooks[s.fingerprint] = _runbooks_summary(s.hits)
    # metrics/diagnosis/slack carry whatever has finished for each fingerprint
    # when the ack is sent; for a newly scheduled alert that is usually
    # nothing yet (null). GET /api/v1/alerts/{fingerprint} has the results.
    return AlertAck(
        received=len(fingerprints),
        fingerprints=fingerprints,
        detail={
            "receiver": payload.receiver,
            "group_status": payload.status,
            "processing": processing,
            "runbooks": runbooks,
            "metrics": {fp: _metrics_summary(pipeline.metrics_for(fp)) for fp in fingerprints},
            "diagnosis": {
                fp: _diagnosis_summary(pipeline.diagnosis_for(fp)) for fp in fingerprints
            },
            "slack": {fp: _slack_summary(pipeline.slack_for(fp)) for fp in fingerprints},
        },
    )


@router.get("/alerts/{fingerprint}")
async def get_alert(fingerprint: str, request: Request) -> AlertStatus:
    """Return the processing state and stage results for an alert fingerprint."""
    pipeline: AlertPipeline = request.app.state.pipeline
    record = pipeline.record_for(fingerprint)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown fingerprint")
    return AlertStatus(
        fingerprint=fingerprint,
        state="done" if record.done else "processing",
        runbooks=_runbooks_summary(record.hits),
        metrics=_metrics_summary(record.metrics),
        diagnosis=_diagnosis_summary(record.diagnosis),
        slack=_slack_summary(record.delivered),
    )
