from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar, cast

import httpx
from pydantic import BaseModel

from .backend import infer_backend, resolve_base_url
from .debug import DebugEvent, DebugReporter, DebugSetting, dump_headers, resolve_debug
from .errors import CloudOnlyError, OssOnlyError, TimeoutError, error_from_response
from .models import (
    Backend,
    BatchExtractItem,
    BatchExtractMeta,
    BatchExtractResult,
    CacheStats,
    CircuitBreakerStatsResponse,
    CloudAccount,
    CreditInfo,
    Engine,
    EnginesCapabilities,
    EnginesStatus,
    ExtractMode,
    ExtractResult,
    HealthStatus,
    ImageEnvelope,
    LastResponse,
    MegaEnginesResponse,
    MegaSearchEnvelope,
    Pricing,
    ProxyStats,
    ReadinessStatus,
    ResponseFormat,
    SearchEnvelope,
    StatsResponse,
)

QueryValue = str | int | float | bool | list[str] | tuple[str, ...] | None
RetryHook = Callable[[Exception, int], bool]
ModelT = TypeVar("ModelT", bound=BaseModel)

_PROXY_HEADER_MAP: dict[str, str] = {
    "use_proxy": "X-Use-Proxy",
    "proxy_url": "X-Proxy-URL",
    "proxy_country": "X-Proxy-Country",
    "proxy_class": "X-Proxy-Class",
    "proxy_provider": "X-Proxy-Provider",
    "proxy_session_id": "X-Proxy-Session-ID",
    "tenant": "X-Tenant",
}


class _BaseOpenSERP:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        backend: Backend | None = None,
        timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
        retry: RetryHook | None = None,
        debug: DebugSetting = None,
    ) -> None:
        self.api_key = api_key
        self._base_url = resolve_base_url(api_key=api_key, base_url=base_url)
        self._backend = infer_backend(api_key=api_key, base_url=base_url, backend=backend)
        self.timeout = timeout
        self.headers = dict(headers or {})
        self.retry = retry
        self.last_response: LastResponse | None = None
        self._debug: DebugReporter = resolve_debug(debug)

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def backend(self) -> Backend:
        return self._backend

    def _assert_cloud(self, method: str) -> None:
        if self.backend != "cloud":
            raise CloudOnlyError(method)

    def _assert_oss(self, method: str) -> None:
        if self.backend != "oss":
            raise OssOnlyError(method)

    def _merged_headers(self, headers: Mapping[str, str] | None = None) -> dict[str, str]:
        merged = {"X-OpenSERP-Client": "sdk-python", **self.headers}
        if self.api_key:
            merged["Authorization"] = f"Bearer {self.api_key}"
        if headers:
            merged.update(headers)
        return merged

    def _build_search_request(
        self,
        params: Mapping[str, Any],
    ) -> tuple[dict[str, QueryValue], dict[str, str], ResponseFormat | None]:
        engines = params.get("engines")
        query: dict[str, QueryValue] = {**params}
        if engines is not None:
            query["engines"] = list(engines)
        clean_query, headers = _split_query_and_headers(query)
        return clean_query, headers, cast(ResponseFormat | None, params.get("format"))

    def _build_parse_request(
        self, format: ResponseFormat | None
    ) -> tuple[dict[str, QueryValue] | None, dict[str, str]]:
        query: dict[str, QueryValue] | None = {"format": format} if format else None
        return query, {"Content-Type": "text/html; charset=utf-8"}

    def _build_extract_request(
        self,
        *,
        url: str,
        mode: ExtractMode | None,
        min_runes: int | None,
        clean: bool | None,
        use_llms_txt: bool | None,
        format: ResponseFormat | None,
        params: Mapping[str, Any],
    ) -> tuple[dict[str, QueryValue], dict[str, str], ResponseFormat | None]:
        query: dict[str, QueryValue] = {
            **params,
            "url": url,
            "mode": mode,
            "min_runes": min_runes,
            "clean": clean,
            "use_llms_txt": use_llms_txt,
            "format": format,
        }
        clean_query, headers = _split_query_and_headers(query)
        return clean_query, headers, format

    def _build_batch_extract_request(
        self,
        *,
        urls: Sequence[str],
        mode: ExtractMode | None,
        min_runes: int | None,
        clean: bool | None,
        use_llms_txt: bool | None,
        lang: str | None,
        region: str | None,
        params: Mapping[str, Any],
    ) -> tuple[str, dict[str, str]]:
        # Proxy/tenant knobs travel as headers on every other endpoint; reuse
        # that split so batch behaves the same. Everything else is body JSON.
        _, headers = _split_query_and_headers(dict(params))
        body: dict[str, Any] = {
            "urls": list(urls),
            "mode": mode,
            "min_runes": min_runes,
            "clean": clean,
            "use_llms_txt": use_llms_txt,
            "lang": lang,
            "region": region,
        }
        payload = {key: value for key, value in body.items() if value is not None}
        headers = {**headers, "Content-Type": "application/json"}
        return json.dumps(payload), headers

    def _set_last_response(self, response: httpx.Response) -> None:
        headers = {key.lower(): value for key, value in response.headers.items()}
        credits_used = _int_header(response.headers, "x-credits-used")
        credits_remaining = _int_header(response.headers, "x-credits-remaining")
        credits = (
            CreditInfo(used=credits_used, remaining=credits_remaining)
            if credits_used is not None or credits_remaining is not None
            else None
        )
        self.last_response = LastResponse(
            status=response.status_code,
            request_id=response.headers.get("x-request-id"),
            credits=credits,
            engine_used=response.headers.get("x-engine-used"),
            fallback_engine=response.headers.get("x-fallback-engine"),
            cache=response.headers.get("x-cache"),
            proxy_mode=response.headers.get("x-proxy-mode"),
            proxy_tag=response.headers.get("x-proxy-tag"),
            proxy_used=response.headers.get("x-proxy-used"),
            network_bytes=_int_header(response.headers, "x-network-bytes"),
            browser_profile_id=response.headers.get("x-browser-profile-id"),
            headers=headers,
        )

    def _handle_response(self, response: httpx.Response, format: ResponseFormat | None) -> Any:
        self._set_last_response(response)
        body = _read_body(response, format)
        if response.is_error:
            raise error_from_response(
                response.status_code, body, response.headers.get("x-request-id")
            )
        return body

    def _debug_request(
        self, method: str, url: str, headers: Mapping[str, str]
    ) -> None:
        if self._debug.level == "off":
            return
        self._debug.emit(
            DebugEvent(
                type="request",
                method=method,
                url=url,
                headers=dump_headers(headers) if self._debug.level == "verbose" else None,
            )
        )

    def _debug_response(
        self, method: str, url: str, response: httpx.Response, started: float
    ) -> None:
        if self._debug.level == "off":
            return
        self._debug.emit(
            DebugEvent(
                type="response",
                method=method,
                url=url,
                status=response.status_code,
                engine_used=response.headers.get("x-engine-used"),
                request_id=response.headers.get("x-request-id"),
                duration_ms=_elapsed_ms(started),
                headers=dump_headers(response.headers)
                if self._debug.level == "verbose"
                else None,
            )
        )

    def _debug_error(
        self, method: str, url: str, error: BaseException, started: float
    ) -> None:
        if self._debug.level == "off":
            return
        self._debug.emit(
            DebugEvent(
                type="error",
                method=method,
                url=url,
                duration_ms=_elapsed_ms(started),
                error=error,
            )
        )


class OpenSERP(_BaseOpenSERP):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        backend: Backend | None = None,
        timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
        retry: RetryHook | None = None,
        debug: DebugSetting = None,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            backend=backend,
            timeout=timeout,
            headers=headers,
            retry=retry,
            debug=debug,
        )
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenSERP:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def search(
        self, *, engine: Engine, min_runes: int | None = None, **params: Any
    ) -> SearchEnvelope | str:
        if min_runes is not None:
            params["min_runes"] = min_runes
        query, headers, format = self._build_search_request(params)
        return self._get_model(SearchEnvelope, f"/{engine}/search", query, headers, format)

    def image(self, *, engine: Engine, **params: Any) -> ImageEnvelope | str:
        query, headers, format = self._build_search_request(params)
        return self._get_model(ImageEnvelope, f"/{engine}/image", query, headers, format)

    def mega_search(
        self, *, min_runes: int | None = None, **params: Any
    ) -> MegaSearchEnvelope | str:
        if min_runes is not None:
            params["min_runes"] = min_runes
        query, headers, format = self._build_search_request(params)
        return self._get_model(MegaSearchEnvelope, "/mega/search", query, headers, format)

    def extract(
        self,
        *,
        url: str,
        mode: ExtractMode | None = None,
        min_runes: int | None = None,
        clean: bool | None = None,
        use_llms_txt: bool | None = None,
        format: ResponseFormat | None = None,
        **params: Any,
    ) -> ExtractResult | str:
        query, headers, format = self._build_extract_request(
            url=url,
            mode=mode,
            min_runes=min_runes,
            clean=clean,
            use_llms_txt=use_llms_txt,
            format=format,
            params=params,
        )
        return self._get_model(ExtractResult, "/extract", query, headers, format)

    def batch_extract(
        self,
        *,
        urls: Sequence[str],
        mode: ExtractMode | None = None,
        min_runes: int | None = None,
        clean: bool | None = None,
        use_llms_txt: bool | None = None,
        lang: str | None = None,
        region: str | None = None,
        **params: Any,
    ) -> BatchExtractResult:
        """Extract up to 20 URLs in one request.

        Billing matches calling :meth:`extract` once per URL: successful
        extractions bill their mode plus any region surcharge, while failed and
        empty ones are free. A URL that fails becomes an item carrying an
        ``error`` rather than failing the whole call.
        """
        body, headers = self._build_batch_extract_request(
            urls=urls,
            mode=mode,
            min_runes=min_runes,
            clean=clean,
            use_llms_txt=use_llms_txt,
            lang=lang,
            region=region,
            params=params,
        )
        payload = self._send("POST", "/extract/batch", headers=headers, content=body)
        return _normalize_batch_extract(payload)

    def fast_search(self, **params: Any) -> MegaSearchEnvelope | str:
        return self.mega_search(**{**params, "mode": "fast"})

    def any_search(self, **params: Any) -> MegaSearchEnvelope | str:
        return self.mega_search(**{**params, "mode": "any"})

    def mega_image(self, **params: Any) -> ImageEnvelope | str:
        query, headers, format = self._build_search_request(params)
        return self._get_model(ImageEnvelope, "/mega/image", query, headers, format)

    def fast_image(self, **params: Any) -> ImageEnvelope | str:
        return self.mega_image(**{**params, "mode": "fast"})

    def any_image(self, **params: Any) -> ImageEnvelope | str:
        return self.mega_image(**{**params, "mode": "any"})

    def parse_google(
        self, *, html: str, format: ResponseFormat | None = None
    ) -> SearchEnvelope | str:
        self._assert_oss("parse_google")
        return self._parse("/google/parse", html, format)

    def parse_bing(
        self, *, html: str, format: ResponseFormat | None = None
    ) -> SearchEnvelope | str:
        self._assert_oss("parse_bing")
        return self._parse("/bing/parse", html, format)

    def health(self) -> HealthStatus:
        self._assert_oss("health")
        return self._get_json(HealthStatus, "/health")

    def ready(self) -> ReadinessStatus:
        self._assert_oss("ready")
        return self._get_json(ReadinessStatus, "/ready")

    def stats(self) -> StatsResponse:
        self._assert_oss("stats")
        return self._get_json(StatsResponse, "/stats")

    def cache_stats(self) -> CacheStats:
        self._assert_oss("cache_stats")
        return self._get_json(CacheStats, "/stats/cache")

    def proxy_stats(self) -> ProxyStats:
        self._assert_oss("proxy_stats")
        return self._get_json(ProxyStats, "/stats/proxy")

    def circuit_breaker_stats(self) -> CircuitBreakerStatsResponse:
        self._assert_oss("circuit_breaker_stats")
        return self._get_json(CircuitBreakerStatsResponse, "/stats/cb")

    def engines(self) -> MegaEnginesResponse:
        self._assert_oss("engines")
        return self._get_json(MegaEnginesResponse, "/mega/engines")

    def me(self) -> CloudAccount:
        self._assert_cloud("me")
        return self._get_json(CloudAccount, "/me")

    def pricing(self) -> Pricing:
        self._assert_cloud("pricing")
        return self._get_json(Pricing, "/pricing")

    def engines_status(self) -> EnginesStatus:
        self._assert_cloud("engines_status")
        return self._get_json(EnginesStatus, "/engines/status")

    def engines_capabilities(self) -> EnginesCapabilities:
        self._assert_cloud("engines_capabilities")
        return self._get_json(EnginesCapabilities, "/engines/capabilities")

    def _get_json(self, model: type[ModelT], path: str) -> ModelT:
        body = self._send("GET", path)
        return model.model_validate(body)

    def _parse(self, path: str, html: str, format: ResponseFormat | None) -> SearchEnvelope | str:
        query, headers = self._build_parse_request(format)
        body = self._send("POST", path, query=query, headers=headers, content=html, format=format)
        return body if isinstance(body, str) else SearchEnvelope.model_validate(body)

    def _get_model(
        self,
        model: type[ModelT],
        path: str,
        query: Mapping[str, QueryValue] | None = None,
        headers: Mapping[str, str] | None = None,
        format: ResponseFormat | None = None,
    ) -> ModelT | str:
        body = self._send("GET", path, query=query, headers=headers, format=format)
        return body if isinstance(body, str) else model.model_validate(body)

    def _send(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, QueryValue] | None = None,
        headers: Mapping[str, str] | None = None,
        format: ResponseFormat | None = None,
        content: str | None = None,
    ) -> Any:
        merged_headers = self._merged_headers(headers)
        url = httpx.URL(f"{self.base_url}{path}", params=_encode_query(query))
        attempt = 0
        while True:
            started = time.perf_counter()
            try:
                self._debug_request(method, str(url), merged_headers)
                try:
                    response = self._client.request(
                        method,
                        url,
                        headers=merged_headers,
                        content=content,
                    )
                except httpx.TimeoutException as exc:
                    raise TimeoutError(self.timeout) from exc
                self._debug_response(method, str(url), response, started)
                return self._handle_response(response, format)
            except Exception as exc:
                self._debug_error(method, str(url), exc, started)
                if not self.retry or not self.retry(exc, attempt):
                    raise
                attempt += 1


class AsyncOpenSERP(_BaseOpenSERP):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        backend: Backend | None = None,
        timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
        retry: RetryHook | None = None,
        debug: DebugSetting = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            backend=backend,
            timeout=timeout,
            headers=headers,
            retry=retry,
            debug=debug,
        )
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncOpenSERP:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def search(
        self, *, engine: Engine, min_runes: int | None = None, **params: Any
    ) -> SearchEnvelope | str:
        if min_runes is not None:
            params["min_runes"] = min_runes
        query, headers, format = self._build_search_request(params)
        return await self._get_model(SearchEnvelope, f"/{engine}/search", query, headers, format)

    async def image(self, *, engine: Engine, **params: Any) -> ImageEnvelope | str:
        query, headers, format = self._build_search_request(params)
        return await self._get_model(ImageEnvelope, f"/{engine}/image", query, headers, format)

    async def mega_search(
        self, *, min_runes: int | None = None, **params: Any
    ) -> MegaSearchEnvelope | str:
        if min_runes is not None:
            params["min_runes"] = min_runes
        query, headers, format = self._build_search_request(params)
        return await self._get_model(MegaSearchEnvelope, "/mega/search", query, headers, format)

    async def extract(
        self,
        *,
        url: str,
        mode: ExtractMode | None = None,
        min_runes: int | None = None,
        clean: bool | None = None,
        use_llms_txt: bool | None = None,
        format: ResponseFormat | None = None,
        **params: Any,
    ) -> ExtractResult | str:
        query, headers, format = self._build_extract_request(
            url=url,
            mode=mode,
            min_runes=min_runes,
            clean=clean,
            use_llms_txt=use_llms_txt,
            format=format,
            params=params,
        )
        return await self._get_model(ExtractResult, "/extract", query, headers, format)

    async def batch_extract(
        self,
        *,
        urls: Sequence[str],
        mode: ExtractMode | None = None,
        min_runes: int | None = None,
        clean: bool | None = None,
        use_llms_txt: bool | None = None,
        lang: str | None = None,
        region: str | None = None,
        **params: Any,
    ) -> BatchExtractResult:
        """Extract up to 20 URLs in one request. See :meth:`OpenSERP.batch_extract`."""
        body, headers = self._build_batch_extract_request(
            urls=urls,
            mode=mode,
            min_runes=min_runes,
            clean=clean,
            use_llms_txt=use_llms_txt,
            lang=lang,
            region=region,
            params=params,
        )
        payload = await self._send("POST", "/extract/batch", headers=headers, content=body)
        return _normalize_batch_extract(payload)

    async def fast_search(self, **params: Any) -> MegaSearchEnvelope | str:
        return await self.mega_search(**{**params, "mode": "fast"})

    async def any_search(self, **params: Any) -> MegaSearchEnvelope | str:
        return await self.mega_search(**{**params, "mode": "any"})

    async def mega_image(self, **params: Any) -> ImageEnvelope | str:
        query, headers, format = self._build_search_request(params)
        return await self._get_model(ImageEnvelope, "/mega/image", query, headers, format)

    async def fast_image(self, **params: Any) -> ImageEnvelope | str:
        return await self.mega_image(**{**params, "mode": "fast"})

    async def any_image(self, **params: Any) -> ImageEnvelope | str:
        return await self.mega_image(**{**params, "mode": "any"})

    async def parse_google(
        self, *, html: str, format: ResponseFormat | None = None
    ) -> SearchEnvelope | str:
        self._assert_oss("parse_google")
        return await self._parse("/google/parse", html, format)

    async def parse_bing(
        self, *, html: str, format: ResponseFormat | None = None
    ) -> SearchEnvelope | str:
        self._assert_oss("parse_bing")
        return await self._parse("/bing/parse", html, format)

    async def health(self) -> HealthStatus:
        self._assert_oss("health")
        return await self._get_json(HealthStatus, "/health")

    async def ready(self) -> ReadinessStatus:
        self._assert_oss("ready")
        return await self._get_json(ReadinessStatus, "/ready")

    async def stats(self) -> StatsResponse:
        self._assert_oss("stats")
        return await self._get_json(StatsResponse, "/stats")

    async def cache_stats(self) -> CacheStats:
        self._assert_oss("cache_stats")
        return await self._get_json(CacheStats, "/stats/cache")

    async def proxy_stats(self) -> ProxyStats:
        self._assert_oss("proxy_stats")
        return await self._get_json(ProxyStats, "/stats/proxy")

    async def circuit_breaker_stats(self) -> CircuitBreakerStatsResponse:
        self._assert_oss("circuit_breaker_stats")
        return await self._get_json(CircuitBreakerStatsResponse, "/stats/cb")

    async def engines(self) -> MegaEnginesResponse:
        self._assert_oss("engines")
        return await self._get_json(MegaEnginesResponse, "/mega/engines")

    async def me(self) -> CloudAccount:
        self._assert_cloud("me")
        return await self._get_json(CloudAccount, "/me")

    async def pricing(self) -> Pricing:
        self._assert_cloud("pricing")
        return await self._get_json(Pricing, "/pricing")

    async def engines_status(self) -> EnginesStatus:
        self._assert_cloud("engines_status")
        return await self._get_json(EnginesStatus, "/engines/status")

    async def engines_capabilities(self) -> EnginesCapabilities:
        self._assert_cloud("engines_capabilities")
        return await self._get_json(EnginesCapabilities, "/engines/capabilities")

    async def _get_json(self, model: type[ModelT], path: str) -> ModelT:
        body = await self._send("GET", path)
        return model.model_validate(body)

    async def _parse(
        self, path: str, html: str, format: ResponseFormat | None
    ) -> SearchEnvelope | str:
        query, headers = self._build_parse_request(format)
        body = await self._send(
            "POST", path, query=query, headers=headers, content=html, format=format
        )
        return body if isinstance(body, str) else SearchEnvelope.model_validate(body)

    async def _get_model(
        self,
        model: type[ModelT],
        path: str,
        query: Mapping[str, QueryValue] | None = None,
        headers: Mapping[str, str] | None = None,
        format: ResponseFormat | None = None,
    ) -> ModelT | str:
        body = await self._send("GET", path, query=query, headers=headers, format=format)
        return body if isinstance(body, str) else model.model_validate(body)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, QueryValue] | None = None,
        headers: Mapping[str, str] | None = None,
        format: ResponseFormat | None = None,
        content: str | None = None,
    ) -> Any:
        merged_headers = self._merged_headers(headers)
        url = httpx.URL(f"{self.base_url}{path}", params=_encode_query(query))
        attempt = 0
        while True:
            started = time.perf_counter()
            try:
                self._debug_request(method, str(url), merged_headers)
                try:
                    response = await self._client.request(
                        method,
                        url,
                        headers=merged_headers,
                        content=content,
                    )
                except httpx.TimeoutException as exc:
                    raise TimeoutError(self.timeout) from exc
                self._debug_response(method, str(url), response, started)
                return self._handle_response(response, format)
            except Exception as exc:
                self._debug_error(method, str(url), exc, started)
                if not self.retry or not self.retry(exc, attempt):
                    raise
                attempt += 1


def _normalize_batch_extract(payload: Any) -> BatchExtractResult:
    """Normalize both batch response shapes into one model.

    OSS answers with a bare array of ``{page_content, metadata}`` (its Open
    WebUI loader contract) while the cloud wraps that in an envelope so per-URL
    billing has somewhere to be reported. Callers should not have to care.
    """
    if isinstance(payload, dict):
        return BatchExtractResult.model_validate(payload)

    items = payload if isinstance(payload, list) else []
    results: list[BatchExtractItem] = []
    for entry in items:
        metadata = entry.get("metadata") or {} if isinstance(entry, dict) else {}
        results.append(
            BatchExtractItem(
                url=metadata.get("source"),
                page_content=entry.get("page_content") if isinstance(entry, dict) else None,
                error=metadata.get("error") or None,
                metadata=metadata,
            )
        )
    failed = sum(1 for item in results if item.error)
    return BatchExtractResult(
        results=results,
        meta=BatchExtractMeta(
            requested=len(results),
            succeeded=len(results) - failed,
            failed=failed,
        ),
    )


def _split_query_and_headers(
    query: Mapping[str, QueryValue],
) -> tuple[dict[str, QueryValue], dict[str, str]]:
    clean_query: dict[str, QueryValue] = {}
    headers: dict[str, str] = {}
    for key, value in query.items():
        if value is None:
            continue
        header_name = _PROXY_HEADER_MAP.get(key)
        if header_name is not None:
            headers[header_name] = _encode_value(value)
        else:
            clean_query[key] = value
    return clean_query, headers


def _encode_query(query: Mapping[str, QueryValue] | None) -> dict[str, str]:
    if not query:
        return {}
    return {key: _encode_value(value) for key, value in query.items() if value is not None}


def _encode_value(value: QueryValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | tuple):
        return ",".join(str(item) for item in value)
    return str(value)


def _read_body(response: httpx.Response, format: ResponseFormat | None = None) -> Any:
    if response.status_code == 204:
        return None
    if format and format != "json":
        return response.text
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    text = response.text
    if not text:
        return None
    try:
        return response.json()
    except ValueError:
        return text


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _int_header(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None
