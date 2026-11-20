"""Async client for Slack incoming webhooks."""

import asyncio
import logging
import random
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SlackError(Exception):
    """Raised when posting a message to Slack fails."""


def _is_transient(exc: httpx.HTTPError) -> bool:
    """Whether a failure is worth retrying (5xx, timeouts, connection errors)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TimeoutException | httpx.TransportError)


class SlackWebhookClient:
    """Posts Block Kit payloads to a Slack incoming webhook URL."""

    def __init__(
        self,
        webhook_url: str,
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.2,
        backoff_max_seconds: float = 5.0,
    ) -> None:
        self._webhook_url = webhook_url
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._backoff_max_seconds = backoff_max_seconds

    async def post(self, message: dict[str, Any]) -> None:
        """Post a message payload to the webhook.

        Raises ``SlackError`` on transport/HTTP failures and when Slack
        rejects the payload (the webhook API answers ``200 ok`` only on
        success; every other body is an error description). Transient
        failures (5xx responses, timeouts, connection errors) are retried
        with exponential backoff and jitter; permanent failures (4xx,
        rejected payloads) are not retried.
        """
        attempt = 0
        while True:
            try:
                resp = await self._client.post(self._webhook_url, json=message)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                if _is_transient(exc) and attempt < self._max_retries:
                    delay = self._backoff_delay(attempt)
                    attempt += 1
                    logger.warning(
                        "slack webhook request failed, retrying attempt=%d/%d in %.2fs: %s",
                        attempt,
                        self._max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise SlackError(f"slack webhook request failed: {exc}") from exc
            if resp.text.strip() != "ok":
                raise SlackError(f"slack webhook rejected the message: {resp.text.strip()}")
            return

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with jitter, capped at ``backoff_max_seconds``."""
        base = min(self._backoff_base_seconds * (2**attempt), self._backoff_max_seconds)
        return base * (0.5 + random.random() / 2)

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
