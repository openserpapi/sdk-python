from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import httpx
import pytest
import respx

from openserp import (
    AsyncOpenSERP,
    CaptchaError,
    CloudOnlyError,
    ExtractResult,
    OpenSERP,
    OssOnlyError,
    RateLimitError,
    SearchEnvelope,
)

SEARCH_BODY = {
    "query": {
        "text": "openserp",
        "lang": "EN",
        "region": "US",
        "engines_requested": ["google"],
    },
    "meta": {
        "request_id": "req_123",
        "requested_at": "2026-05-24T00:00:00Z",
        "took_ms": 12,
        "engines_failed": [],
        "version": "2.1",
    },
    "results": [
        {
            "id": "s_1",
            "rank": 1,
            "type": "organic",
            "title": "OpenSERP",
            "url": "https://openserp.org",
            "display_url": "openserp.org",
            "snippet": "Search API",
            "domain": "openserp.org",
            "favicon": "https://openserp.org/favicon.ico",
            "position": {"absolute": 1},
            "engine": "google",
        }
    ],
    "pagination": {
        "page": 1,
        "has_more": False,
        "next_start": 11,
    },
}

EXTRACT_BODY = {
    "url": "https://openserp.org",
    "title": "OpenSERP",
    "description": "Search API",
    "markdown": "# OpenSERP\n\nSearch API",
    "text": "OpenSERP\n\nSearch API",
    "headings": [{"level": 1, "text": "OpenSERP"}],
    "links": [{"text": "Docs", "url": "https://openserp.org/docs"}],
    "canonical": "https://openserp.org",
    "lang": "en",
    "schema_org": [{"@type": "WebSite", "name": "OpenSERP"}],
    "og_tags": {"og:title": "OpenSERP"},
    "meta": {
        "mode_used": "llms_txt",
        "fetched_at": "2026-06-01T00:00:00Z",
        "bytes": 1024,
        "took_ms": 34,
    },
}


@respx.mock
def test_uses_oss_mode_by_default() -> None:
    route = respx.get("http://localhost:7000/google/search").mock(
        return_value=httpx.Response(
            200,
            json=SEARCH_BODY,
            headers={
                "X-Request-ID": "req_123",
                "X-Engine-Used": "google",
                "X-Cache": "hit",
                "X-Fallback-Engine": "bing",
            },
        )
    )

    client = OpenSERP()
    response = client.search(engine="google", text="openserp", limit=10, region="US")

    assert not isinstance(response, str)
    assert response.results[0].title == "OpenSERP"
    assert client.backend == "oss"
    assert client.last_response is not None
    assert client.last_response.request_id == "req_123"
    assert client.last_response.cache == "hit"
    assert client.last_response.fallback_engine == "bing"
    assert client.last_response.credits is None

    request = route.calls.last.request
    assert request.url.params["text"] == "openserp"
    assert request.url.params["limit"] == "10"
    assert request.url.params["region"] == "US"
    assert "authorization" not in request.headers


@respx.mock
def test_uses_cloud_base_url_and_bearer_auth_when_api_key_is_present() -> None:
    route = respx.get("https://api.openserp.org/v1/google/search").mock(
        return_value=httpx.Response(
            200,
            json=SEARCH_BODY,
            headers={
                "X-Credits-Used": "1",
                "X-Credits-Remaining": "4249",
                "X-Engine-Used": "google",
            },
        )
    )

    client = OpenSERP(api_key="osk_live_test")
    client.search(engine="google", text="openserp")

    assert client.base_url == "https://api.openserp.org/v1"
    assert client.backend == "cloud"
    assert client.last_response is not None
    assert client.last_response.credits is not None
    assert client.last_response.credits.used == 1
    assert client.last_response.credits.remaining == 4249
    assert client.last_response.engine_used == "google"
    assert route.calls.last.request.headers["authorization"] == "Bearer osk_live_test"


@respx.mock
def test_keeps_explicit_base_url_and_still_sends_api_key() -> None:
    route = respx.get("http://localhost:7000/google/search").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )

    client = OpenSERP(api_key="local_key", base_url="http://localhost:7000/")
    client.search(engine="google", text="openserp")

    assert client.base_url == "http://localhost:7000"
    assert client.backend == "cloud"
    assert route.calls.last.request.headers["authorization"] == "Bearer local_key"


@respx.mock
def test_supports_mega_convenience_helpers() -> None:
    route = respx.get("http://localhost:7000/mega/search").mock(
        return_value=httpx.Response(200, json={**SEARCH_BODY, "clusters": []})
    )

    client = OpenSERP()
    response = client.fast_search(text="openserp", engines=["google", "bing"])

    assert not isinstance(response, str)
    assert response.clusters == []
    assert route.calls.last.request.url.params["mode"] == "fast"
    assert route.calls.last.request.url.params["engines"] == "google,bing"


@respx.mock
def test_search_supports_embedded_extraction_params_and_result_model() -> None:
    body = cast(dict[str, Any], deepcopy(SEARCH_BODY))
    body["results"][0]["extracted"] = {
        "format": "markdown",
        "content": "# OpenSERP",
        "title": "OpenSERP",
        "mode_used": "llms_txt",
        "fetched_at": "2026-06-01T00:00:00Z",
    }
    route = respx.get("http://localhost:7000/google/search").mock(
        return_value=httpx.Response(200, json=body)
    )

    client = OpenSERP()
    response = client.search(
        engine="google",
        text="openserp",
        extract=2,
        extract_mode="fast",
        min_runes=500,
    )

    assert not isinstance(response, str)
    assert response.results[0].extracted is not None
    assert response.results[0].extracted.mode_used == "llms_txt"
    assert response.results[0].extracted.content == "# OpenSERP"

    request = route.calls.last.request
    assert request.url.params["extract"] == "2"
    assert request.url.params["extract_mode"] == "fast"
    assert request.url.params["min_runes"] == "500"


@respx.mock
def test_extract_fetches_url_content_and_forwards_all_flags() -> None:
    route = respx.get("https://api.openserp.org/v1/extract").mock(
        return_value=httpx.Response(
            200,
            json=EXTRACT_BODY,
            headers={"X-Credits-Used": "1", "X-Credits-Remaining": "99"},
        )
    )

    client = OpenSERP(api_key="osk_live_test")
    response = client.extract(
        url="https://openserp.org",
        mode="fast",
        min_runes=800,
        clean=False,
        use_llms_txt=True,
        lang="en",
        proxy_url="http://proxy.example:8080",
    )

    assert isinstance(response, ExtractResult)
    assert response.meta is not None
    assert response.meta.mode_used == "llms_txt"
    assert response.headings[0].text == "OpenSERP"
    assert response.links[0].url == "https://openserp.org/docs"
    assert client.last_response is not None
    assert client.last_response.credits is not None
    assert client.last_response.credits.used == 1

    request = route.calls.last.request
    assert request.url.params["url"] == "https://openserp.org"
    assert request.url.params["mode"] == "fast"
    assert request.url.params["min_runes"] == "800"
    assert request.url.params["clean"] == "false"
    assert request.url.params["use_llms_txt"] == "true"
    assert request.url.params["lang"] == "en"
    assert "proxy_url" not in request.url.params
    assert request.headers["x-proxy-url"] == "http://proxy.example:8080"


@respx.mock
def test_extract_returns_text_for_non_json_formats() -> None:
    route = respx.get("http://localhost:7000/extract").mock(
        return_value=httpx.Response(
            200,
            text="# OpenSERP",
            headers={"Content-Type": "text/markdown"},
        )
    )

    client = OpenSERP()
    response = client.extract(url="https://openserp.org", format="markdown")

    assert response == "# OpenSERP"
    assert route.calls.last.request.url.params["format"] == "markdown"


@respx.mock
def test_sends_oss_proxy_controls_as_headers() -> None:
    route = respx.get("http://localhost:7000/bing/search").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )

    client = OpenSERP()
    client.search(
        engine="bing",
        text="openserp",
        use_proxy="us",
        proxy_url="http://proxy.example:8080",
        proxy_session_id="sid-123",
        tenant="tenant-a",
    )

    request = route.calls.last.request
    assert "proxy_url" not in request.url.params
    assert request.headers["x-use-proxy"] == "us"
    assert request.headers["x-proxy-url"] == "http://proxy.example:8080"
    assert request.headers["x-proxy-session-id"] == "sid-123"
    assert request.headers["x-tenant"] == "tenant-a"


@respx.mock
def test_posts_parser_html_to_oss_only_parse_endpoints() -> None:
    route = respx.post("http://localhost:7000/google/parse").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )

    client = OpenSERP(base_url="http://localhost:7000")
    client.parse_google(html="<html></html>")

    request = route.calls.last.request
    assert "text/html" in request.headers["content-type"]
    assert request.content == b"<html></html>"


def test_gates_endpoint_availability_with_typed_errors() -> None:
    cloud = OpenSERP(api_key="osk_live_test")
    oss = OpenSERP()

    with pytest.raises(OssOnlyError):
        cloud.stats()

    with pytest.raises(CloudOnlyError):
        oss.me()


@respx.mock
def test_authenticated_oss_can_force_backend_mode() -> None:
    respx.get("http://localhost:7000/stats").mock(
        return_value=httpx.Response(
            200,
            json={
                "cache": {"status": False},
                "proxy": {
                    "configured_count": 0,
                    "healthy_count": 0,
                    "unhealthy_count": 0,
                    "request_proxy_url_enabled": False,
                    "lanes": {"active": 0, "evicted_lru": 0, "cookies_dropped": 0},
                    "browser_processes": {
                        "active": 0,
                        "max": 0,
                        "evicted_lru": 0,
                        "evicted_idle": 0,
                    },
                    "tags": {},
                    "entries": [],
                },
                "circuit_breakers": [],
            },
        )
    )

    client = OpenSERP(api_key="local_key", base_url="http://localhost:7000", backend="oss")
    stats = client.stats()

    assert stats.cache.status is False


@respx.mock
def test_maps_rate_limit_and_captcha_errors() -> None:
    route = respx.get("http://localhost:7000/google/search").mock(
        return_value=httpx.Response(
            429,
            json={
                "error": "rate_limited",
                "code": 429,
                "message": "search engine rate limited the request",
            },
        )
    )

    client = OpenSERP()
    with pytest.raises(RateLimitError) as rate_limit:
        client.search(engine="google", text="openserp")
    assert "https://github.com/openserpapi/sdk-python/issues" in str(rate_limit.value)

    route.mock(
        return_value=httpx.Response(
            503,
            json={
                "error": "captcha_detected",
                "code": 503,
                "message": "captcha challenge detected",
            },
        )
    )

    with pytest.raises(CaptchaError):
        client.search(engine="google", text="openserp")


@respx.mock
def test_uses_retry_hook_without_builtin_retry_policy() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"error": "server_error", "code": 500})
        return httpx.Response(200, json=SEARCH_BODY)

    respx.get("http://localhost:7000/google/search").mock(side_effect=handler)
    client = OpenSERP(retry=lambda _err, attempt: attempt == 0)

    client.search(engine="google", text="openserp")

    assert calls == 2


@respx.mock
@pytest.mark.asyncio
async def test_async_client_mirrors_sync_surface() -> None:
    respx.get("https://api.openserp.org/v1/google/search").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )

    async with AsyncOpenSERP(api_key="osk_live_test") as client:
        response = await client.search(engine="google", text="openserp")

    assert not isinstance(response, str)
    assert response.results[0].url == "https://openserp.org"


def test_to_pandas_exports_result_rows() -> None:
    pytest.importorskip("pandas")
    parsed = SearchEnvelope.model_validate(SEARCH_BODY)
    frame = parsed.to_pandas()

    assert list(frame["title"]) == ["OpenSERP"]
    assert list(frame["position_absolute"]) == [1]


def test_search_envelope_parses_serp_features() -> None:
    body = deepcopy(SEARCH_BODY)
    body["serp_features"] = [
        {
            "id": "f_1",
            "engine": "google",
            "type": "ai_summary",
            "text": "OpenSERP is a search API.",
            "links": [{"title": "OpenSERP", "url": "https://openserp.org"}],
            "source_result_ids": ["s_1"],
            "position": {"absolute": 1},
            "confidence": 0.95,
            "extracted_at": "2026-05-24T00:00:00Z",
        }
    ]

    parsed = SearchEnvelope.model_validate(body)

    assert parsed.serp_features[0].type == "ai_summary"
    assert parsed.serp_features[0].links[0].url == "https://openserp.org"
    assert parsed.serp_features[0].source_result_ids == ["s_1"]
