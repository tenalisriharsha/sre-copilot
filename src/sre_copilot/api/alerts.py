"""Alertmanager webhook ingestion endpoint."""

from fastapi import APIRouter, Request, status

from sre_copilot.models import AlertAck, WebhookPayload
from sre_copilot.pipeline import AlertPipeline

router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.post("/alerts", status_code=status.HTTP_202_ACCEPTED)
async def receive_alerts(payload: WebhookPayload, request: Request) -> AlertAck:
    """Receive an Alertmanager webhook and enqueue its alerts for processing."""
    pipeline: AlertPipeline = request.app.state.pipeline
    fingerprints = await pipeline.process(payload)
    return AlertAck(
        received=len(fingerprints),
        fingerprints=fingerprints,
        detail={"receiver": payload.receiver, "group_status": payload.status},
    )
