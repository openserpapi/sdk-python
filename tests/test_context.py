from __future__ import annotations

import json

import httpx
import pytest

from openserp import AsyncOpenSERP, CloudOnlyError, ContextResult, OpenSERP, SERPError

EVIDENCE = {
    "query": "replication",
    "queries": ["replication"],
    "context": "[c1] Evidence",
    "sources": [
        {
            "id": "s1",
            "url": "https://example.com",
            "title": "Docs",
            "fetched_at": "2026-10-27T00:00:00Z",
            "content_sha256": "abc",
        }
    ],
    "citations": [
        {
            "id": "c1",
            "source_id": "s1",
            "excerpt": "Evidence",
            "source_span": {"start": 42, "end": 50},
            "score": 0.8,
            "truncated": False,
        }
    ],
    "failures": [],
    "partial": True,
    "truncated": False,
    "usage": {
        "tokenizer": "cl100k_base",
        "context_tokens": 7,
        "max_tokens": 500,
        "searches": 1,
        "fetches": 1,
    },
    "meta": {"request_id": "req-context", "took_ms": 30},
    "billing": {"credits_used": 3, "credits_remaining": 97},
}


def test_context_posts_typed_json_and_preserves_billing() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.openserp.org/v1/context"
        assert request.method == "POST"
        assert json.loads(request.content) == {
            "query": "replication",
            "queries": ["DDL"],
            "engines": ["google"],
            "extract_mode": "fast",
            "max_tokens": 500,
        }
        assert request.extensions["timeout"]["read"] == 100.0
        assert request.headers["Authorization"] == "Bearer osk_live_test"
        return httpx.Response(200, json=EVIDENCE, headers={"X-Credits-Used": "3"})

    with (
        httpx.Client(transport=httpx.MockTransport(handle)) as transport,
        OpenSERP(api_key="osk_live_test", client=transport) as client,
    ):
        result = client.context(
            query="replication",
            queries=["DDL"],
            engines=["google"],
            extract_mode="fast",
            max_tokens=500,
        )
        assert isinstance(result, ContextResult)
        assert result.citations[0].source_span.start == 42
        assert result.partial
        assert result.billing is not None and result.billing.credits_used == 3
        assert client.last_response is not None and client.last_response.credits is not None
        assert client.last_response.credits.used == 3


@pytest.mark.asyncio
async def test_async_context_and_explicit_timeout() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"]["read"] == 12.0
        return httpx.Response(200, json=EVIDENCE)

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport,
        AsyncOpenSERP(api_key="osk_live_test", client=transport) as client,
    ):
        result = await client.context(query="replication", timeout=12.0)
        assert result.context == EVIDENCE["context"]


def test_context_is_cloud_only() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("self-hosted server must not be called")

    with (
        httpx.Client(transport=httpx.MockTransport(handle)) as transport,
        OpenSERP(base_url="http://localhost:7000", client=transport) as client,
        pytest.raises(CloudOnlyError),
    ):
        client.context(query="replication")


def test_context_error_is_not_retried() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            404, json={"error": "not_found", "code": 404, "message": "Not found."}
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handle)) as transport,
        OpenSERP(api_key="osk_live_test", client=transport, retry=lambda *_: True) as client,
        pytest.raises(SERPError) as error,
    ):
        client.context(query="replication")
    assert error.value.status == 404
    assert calls == 1
