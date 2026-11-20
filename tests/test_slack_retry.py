"""Regression tests for issue #4: retry failed Slack deliveries with backoff.

A transient Slack failure (5xx, timeout) must not be given up on after a
single attempt. These tests run the real ``SlackWebhookClient`` against a
flaky fake Slack webhook (via ``httpx.MockTransport``) that fails a couple of
times before accepting the request, exactly like a real webhook endpoint
recovering from a blip would.
"""

import asyncio
from datetime import UTC, datetime

import httpx

from sre_copilot.models import Alert, WebhookPayload
from sre_copilot.pipeline import AlertPipeline
from sre_copilot.slack.client import SlackWebhookClient
from sre_copilot.slack.notifier import SlackNotifier

WEBHOOK_URL = "https://hooks.slack.com/services/T00/B00/xxx"


def make_alert() -> Alert:
    return Alert(
        status="firing",
        labels={"alertname": "KubePodCrashLooping", "severity": "critical"},
        annotations={"summary": "pod crash looping"},
        startsAt=datetime(2026, 7, 31, 2, 14, 3, tzinfo=UTC),
        fingerprint="test-fingerprint",
    )


async def test_pipeline_retries_transient_5xx_then_delivers():
    """A flaky Slack webhook that 500s twice then accepts must still deliver."""
    requests: list[httpx.Request] = []

    def flaky_slack(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) <= 2:
            return httpx.Response(500, text="internal_error")
        return httpx.Response(200, text="ok")

    client = SlackWebhookClient(WEBHOOK_URL, transport=httpx.MockTransport(flaky_slack))
    pipeline = AlertPipeline(notifier=SlackNotifier(client=client))

    await asyncio.wait_for(
        pipeline.process(WebhookPayload(status="firing", alerts=[make_alert()])),
        timeout=20,
    )

    assert len(requests) >= 3, "the transient 500s should have been retried"
    assert pipeline.slack_for("test-fingerprint") is True


async def test_pipeline_retries_on_timeout_then_delivers():
    """A Slack webhook that times out once then responds must still deliver."""
    requests: list[httpx.Request] = []

    def flaky_slack(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(200, text="ok")

    client = SlackWebhookClient(WEBHOOK_URL, transport=httpx.MockTransport(flaky_slack))
    pipeline = AlertPipeline(notifier=SlackNotifier(client=client))

    await asyncio.wait_for(
        pipeline.process(WebhookPayload(status="firing", alerts=[make_alert()])),
        timeout=20,
    )

    assert len(requests) >= 2, "the timeout should have been retried"
    assert pipeline.slack_for("test-fingerprint") is True
