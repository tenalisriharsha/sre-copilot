"""Async client for Slack incoming webhooks."""

from typing import Any

import httpx


class SlackError(Exception):
    """Raised when posting a message to Slack fails."""


class SlackWebhookClient:
    """Posts Block Kit payloads to a Slack incoming webhook URL."""

    def __init__(
        self,
        webhook_url: str,
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._webhook_url = webhook_url
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def post(self, message: dict[str, Any]) -> None:
        """Post a message payload to the webhook.

        Raises ``SlackError`` on transport/HTTP failures and when Slack
        rejects the payload (the webhook API answers ``200 ok`` only on
        success; every other body is an error description).
        """
        try:
            resp = await self._client.post(self._webhook_url, json=message)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SlackError(f"slack webhook request failed: {exc}") from exc
        if resp.text.strip() != "ok":
            raise SlackError(f"slack webhook rejected the message: {resp.text.strip()}")

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
