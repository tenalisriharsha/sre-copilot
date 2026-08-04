"""Provider-agnostic LLM client interface plus an OpenAI-compatible client."""

from typing import Any, Protocol

import httpx


class LLMError(Exception):
    """Raised when the LLM call fails or returns an unusable response."""


class LLMClient(Protocol):
    """Minimal chat interface the diagnosis service depends on.

    Implementations must return the raw response content, which the caller
    parses as JSON. Tests use a fake implementing this protocol — no live
    LLM calls in CI.
    """

    async def complete_json(self, *, system: str, user: str) -> str:
        """Return the assistant message content for a JSON-mode chat call."""
        ...


class OpenAICompatibleClient:
    """Async client for OpenAI-compatible ``/chat/completions`` APIs."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    async def complete_json(self, *, system: str, user: str) -> str:
        """Call chat completions in JSON mode and return the message content.

        Raises ``LLMError`` on transport/HTTP failures and on responses that
        do not look like a chat completion payload.
        """
        try:
            resp = await self._client.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        payload: dict[str, Any] = resp.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("malformed chat completion response") from exc
        if not isinstance(content, str):
            raise LLMError("chat completion content is not text")
        return content

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
