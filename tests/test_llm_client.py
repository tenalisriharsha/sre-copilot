"""Tests for the OpenAI-compatible LLM client (mocked transport)."""

import json

import httpx
import pytest

from sre_copilot.llm.client import LLMError, OpenAICompatibleClient


def completion_payload(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def make_client(handler, **kwargs) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="http://llm.test/v1",
        api_key="test-key",
        model="test-model",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_complete_json_returns_message_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion_payload('{"likely_cause": "oom"}'))

    client = make_client(handler)
    content = await client.complete_json(system="sys", user="usr")
    assert content == '{"likely_cause": "oom"}'


async def test_complete_json_sends_chat_completion_request():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=completion_payload("{}"))

    client = make_client(handler)
    await client.complete_json(system="be terse", user="diagnose this")

    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]
    assert seen["body"]["messages"][0]["content"] == "be terse"
    assert seen["body"]["messages"][1]["content"] == "diagnose this"


async def test_complete_json_raises_on_http_error():
    client = make_client(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(LLMError, match="LLM request failed"):
        await client.complete_json(system="s", user="u")


async def test_complete_json_raises_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = make_client(handler)
    with pytest.raises(LLMError, match="LLM request failed"):
        await client.complete_json(system="s", user="u")


async def test_complete_json_raises_on_malformed_payload():
    client = make_client(lambda request: httpx.Response(200, json={"choices": []}))
    with pytest.raises(LLMError, match="malformed chat completion response"):
        await client.complete_json(system="s", user="u")


async def test_complete_json_raises_on_non_text_content():
    payload = {"choices": [{"message": {"role": "assistant", "content": None}}]}
    client = make_client(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(LLMError, match="content is not text"):
        await client.complete_json(system="s", user="u")


async def test_complete_json_raises_on_non_json_body():
    """A 200 with a non-JSON body (e.g. a gateway's HTML page) is an LLMError."""
    client = make_client(lambda request: httpx.Response(200, text="<html>gateway</html>"))
    with pytest.raises(LLMError, match="malformed chat completion response"):
        await client.complete_json(system="s", user="u")
