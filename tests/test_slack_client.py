"""Tests for the Slack incoming-webhook client (mocked transport)."""

import json

import httpx
import pytest

from sre_copilot.slack.client import SlackError, SlackWebhookClient

WEBHOOK_URL = "https://hooks.slack.com/services/T00/B00/xxx"


def make_client(handler) -> SlackWebhookClient:
    return SlackWebhookClient(WEBHOOK_URL, transport=httpx.MockTransport(handler))


async def test_post_sends_payload_to_webhook_url():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    client = make_client(handler)
    await client.post({"text": "hello"})

    assert len(requests) == 1
    assert str(requests[0].url) == WEBHOOK_URL
    assert json.loads(requests[0].content) == {"text": "hello"}


async def test_post_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    client = make_client(handler)
    with pytest.raises(SlackError, match="slack webhook request failed"):
        await client.post({"text": "hello"})


async def test_post_raises_on_rejection_body():
    """Slack answers 200 with an error description for invalid payloads."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="invalid_payload")

    client = make_client(handler)
    with pytest.raises(SlackError, match="rejected the message: invalid_payload"):
        await client.post({"text": "hello"})


async def test_post_raises_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = make_client(handler)
    with pytest.raises(SlackError, match="slack webhook request failed"):
        await client.post({"text": "hello"})
