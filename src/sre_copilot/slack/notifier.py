"""Slack notification stage: build the Block Kit message and post it."""

import logging
from collections.abc import Sequence

from sre_copilot.config import Settings
from sre_copilot.llm.models import Diagnosis
from sre_copilot.metrics.models import MetricsSnapshot
from sre_copilot.models import Alert
from sre_copilot.rag.documents import RetrievalHit
from sre_copilot.slack.client import SlackWebhookClient
from sre_copilot.slack.messages import build_message

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Posts the per-alert notification built from every pipeline stage."""

    def __init__(self, client: SlackWebhookClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings) -> "SlackNotifier | None":
        """Build a notifier from settings, or None when no webhook is set."""
        if not settings.slack_webhook_url:
            return None
        client = SlackWebhookClient(
            webhook_url=settings.slack_webhook_url,
            timeout=settings.slack_timeout_seconds,
        )
        return cls(client=client)

    async def notify(
        self,
        alert: Alert,
        runbook_hits: Sequence[RetrievalHit],
        snapshot: MetricsSnapshot | None,
        diagnosis: Diagnosis | None,
    ) -> None:
        """Post the alert notification; raises ``SlackError`` on failure."""
        message = build_message(alert, runbook_hits, snapshot, diagnosis)
        await self._client.post(message)
        logger.info(
            "notified slack alert=%s fingerprint=%s status=%s",
            alert.alertname,
            alert.fingerprint,
            alert.status,
        )
