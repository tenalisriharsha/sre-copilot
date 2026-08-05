"""Alertmanager webhook ingestion endpoint."""

from typing import Any

from fastapi import APIRouter, Request, status

from sre_copilot.metrics.models import MetricsSnapshot
from sre_copilot.models import AlertAck, WebhookPayload
from sre_copilot.pipeline import AlertPipeline

router = APIRouter(prefix="/api/v1", tags=["alerts"])


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


@router.post("/alerts", status_code=status.HTTP_202_ACCEPTED)
async def receive_alerts(payload: WebhookPayload, request: Request) -> AlertAck:
    """Receive an Alertmanager webhook and enqueue its alerts for processing."""
    pipeline: AlertPipeline = request.app.state.pipeline
    fingerprints = await pipeline.process(payload)
    return AlertAck(
        received=len(fingerprints),
        fingerprints=fingerprints,
        detail={
            "receiver": payload.receiver,
            "group_status": payload.status,
            "runbooks": {
                fingerprint: [
                    {
                        "runbook": hit.chunk.runbook,
                        "section": hit.chunk.section,
                        "score": round(hit.score, 4),
                    }
                    for hit in pipeline.retrieval_for(fingerprint)
                ]
                for fingerprint in fingerprints
            },
            "metrics": {
                fingerprint: _metrics_summary(pipeline.metrics_for(fingerprint))
                for fingerprint in fingerprints
            },
            "diagnosis": {
                fingerprint: (
                    diagnosis.model_dump()
                    if (diagnosis := pipeline.diagnosis_for(fingerprint))
                    else None
                )
                for fingerprint in fingerprints
            },
            "slack": {
                fingerprint: (
                    {"delivered": delivered}
                    if (delivered := pipeline.slack_for(fingerprint)) is not None
                    else None
                )
                for fingerprint in fingerprints
            },
        },
    )
