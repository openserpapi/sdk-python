from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Backend = Literal["oss", "cloud"]
Engine = Literal["google", "yandex", "baidu", "bing", "duck", "duckduckgo", "ecosia"]
MegaMode = Literal["balanced", "any", "fast"]
ResponseFormat = Literal["json", "markdown", "text", "ndjson"]
ExtractMode = Literal["auto", "fast", "rendered"]
ExtractModeUsed = Literal["fast", "rendered", "llms_txt"]
ExtractedContentFormat = Literal["markdown", "text"]


class OpenSERPModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class CreditInfo(OpenSERPModel):
    used: int | None = None
    remaining: int | None = None


class LastResponse(OpenSERPModel):
    status: int
    request_id: str | None = None
    credits: CreditInfo | None = None
    engine_used: str | None = None
    fallback_engine: str | None = None
    cache: str | None = None
    proxy_mode: str | None = None
    proxy_tag: str | None = None
    proxy_used: str | None = None
    network_bytes: int | None = None
    browser_profile_id: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class QueryEcho(OpenSERPModel):
    text: str | None = None
    lang: str | None = None
    region: str | None = None
    engines_requested: list[str] = Field(default_factory=list)


class EngineErrorDetail(OpenSERPModel):
    engine: str
    error: str
    message: str | None = None


class ResponseMeta(OpenSERPModel):
    request_id: str | None = None
    requested_at: str | None = None
    took_ms: int | None = None
    engines_failed: list[str] = Field(default_factory=list)
    engine_errors: list[EngineErrorDetail] | None = None
    version: str | None = None


class Pagination(OpenSERPModel):
    page: int | None = None
    has_more: bool | None = None
    next_start: int | None = None


class Position(OpenSERPModel):
    absolute: int | None = None


class DomainInfo(OpenSERPModel):
    tld: str | None = None
    sld: str | None = None
    category: str | None = None


class Classification(OpenSERPModel):
    content_type: str | None = None
    source_hint: str | None = None


class FeatureItem(OpenSERPModel):
    title: str | None = None
    text: str | None = None
    link: str | None = None


class FeatureLink(OpenSERPModel):
    title: str | None = None
    url: str | None = None


class SerpFeature(OpenSERPModel):
    id: str | None = None
    engine: str | None = None
    type: str | None = None
    title: str | None = None
    text: str | None = None
    items: list[FeatureItem] = Field(default_factory=list)
    links: list[FeatureLink] = Field(default_factory=list)
    source_result_ids: list[str] = Field(default_factory=list)
    position: Position | None = None
    confidence: float | None = None
    extracted_at: str | None = None


class SearchResult(OpenSERPModel):
    id: str | None = None
    rank: int | None = None
    type: str | None = None
    title: str | None = None
    url: str | None = None
    display_url: str | None = None
    snippet: str | None = None
    domain: str | None = None
    favicon: str | None = None
    position: Position | None = None
    engine: str | None = None
    domain_info: DomainInfo | None = None
    classification: Classification | None = None
    extracted: ExtractedContent | None = None


class ExtractedContent(OpenSERPModel):
    title: str | None = None
    format: ExtractedContentFormat | str | None = None
    content: str | None = None
    mode_used: ExtractModeUsed | str | None = None
    fetched_at: str | None = None
    error: str | None = None


class ExtractHeading(OpenSERPModel):
    level: int | None = None
    text: str | None = None


class ExtractLink(OpenSERPModel):
    text: str | None = None
    url: str | None = None


class ExtractMeta(OpenSERPModel):
    mode_used: ExtractModeUsed | str | None = None
    fetched_at: str | None = None
    bytes: int | None = None
    took_ms: int | None = None


class ExtractResult(OpenSERPModel):
    url: str | None = None
    title: str | None = None
    description: str | None = None
    markdown: str | None = None
    text: str | None = None
    headings: list[ExtractHeading] = Field(default_factory=list)
    links: list[ExtractLink] = Field(default_factory=list)
    canonical: str | None = None
    lang: str | None = None
    schema_org: list[dict[str, Any]] = Field(default_factory=list)
    og_tags: dict[str, str] = Field(default_factory=dict)
    meta: ExtractMeta | None = None


class BatchExtractItem(OpenSERPModel):
    """One entry of a batch extraction.

    ``error`` is set only when that URL failed; the item is unbilled and the
    rest of the batch is unaffected. On OSS the url/error also live inside
    ``metadata`` - the client lifts them out so both backends look the same.
    """

    url: str | None = None
    page_content: str | None = None
    error: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class BatchExtractMeta(OpenSERPModel):
    requested: int | None = None
    succeeded: int | None = None
    failed: int | None = None


class BatchExtractBilling(OpenSERPModel):
    credits_used: int | None = None
    credits_remaining: int | None = None


class BatchExtractResult(OpenSERPModel):
    billing: BatchExtractBilling | None = None
    results: list[BatchExtractItem] = Field(default_factory=list)
    meta: BatchExtractMeta | None = None


class ImageData(OpenSERPModel):
    url: str | None = None
    thumbnail: str | None = None
    width: int | None = None
    height: int | None = None


class ImageSource(OpenSERPModel):
    page_url: str | None = None
    domain: str | None = None


class ImageResult(OpenSERPModel):
    id: str | None = None
    rank: int | None = None
    type: str | None = None
    title: str | None = None
    image: ImageData | None = None
    source: ImageSource | None = None
    engine: str | None = None


class ClusterOccurrence(OpenSERPModel):
    engine: str | None = None
    rank: int | None = None
    result_id: str | None = None


class Cluster(OpenSERPModel):
    id: str | None = None
    canonical_url: str | None = None
    domain: str | None = None
    title: str | None = None
    occurrences: list[ClusterOccurrence] = Field(default_factory=list)
    engines_count: int | None = None
    best_rank: int | None = None
    score: float | None = None


class Envelope(OpenSERPModel):
    query: QueryEcho | None = None
    meta: ResponseMeta | None = None
    pagination: Pagination | None = None
    credits: CreditInfo | None = None

    def to_pandas(self) -> Any:
        try:
            import pandas as pd  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover
            raise ImportError("Install pandas support with: pip install openserp[pandas]") from exc

        return pd.DataFrame(self._result_records())

    def _result_records(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class SearchEnvelope(Envelope):
    results: list[SearchResult] = Field(default_factory=list)
    serp_features: list[SerpFeature] = Field(default_factory=list)

    def _result_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for item in self.results:
            record = item.model_dump(mode="json")
            if item.position:
                record["position_absolute"] = item.position.absolute
            records.append(record)
        return records


class MegaSearchEnvelope(SearchEnvelope):
    clusters: list[Cluster] | None = None


class ImageEnvelope(Envelope):
    results: list[ImageResult] = Field(default_factory=list)

    def _result_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for item in self.results:
            record = item.model_dump(mode="json")
            if item.image:
                record["image_url"] = item.image.url
                record["thumbnail"] = item.image.thumbnail
                record["width"] = item.image.width
                record["height"] = item.image.height
            if item.source:
                record["page_url"] = item.source.page_url
                record["domain"] = item.source.domain
            records.append(record)
        return records


class ErrorResponse(OpenSERPModel):
    error: str
    code: int
    request_id: str | None = None
    message: str | None = None
    reason: str | None = None
    meta: dict[str, Any] | None = None


class EngineHealth(OpenSERPModel):
    name: str
    initialized: bool
    status: str


class HealthStatus(OpenSERPModel):
    status: str
    uptime: str | None = None
    engines: list[EngineHealth] = Field(default_factory=list)
    system: dict[str, Any] = Field(default_factory=dict)


class ReadinessStatus(OpenSERPModel):
    status: str


class CacheStats(OpenSERPModel):
    status: bool
    entries: int | None = None
    hits: int | None = None
    misses: int | None = None
    bypasses: int | None = None
    evictions: int | None = None
    ttl_seconds: int | None = None
    max_size: int | None = None


class ProxyStats(OpenSERPModel):
    configured_count: int | None = None
    healthy_count: int | None = None
    unhealthy_count: int | None = None
    request_proxy_url_enabled: bool | None = None
    lanes: dict[str, Any] | None = None
    browser_processes: dict[str, Any] | None = None
    tags: dict[str, Any] = Field(default_factory=dict)
    entries: list[dict[str, Any]] = Field(default_factory=list)
    engines: dict[str, Any] | None = None


class CircuitBreakerStat(OpenSERPModel):
    engine: str
    state: str
    failure_count: int
    last_changed: str
    retry_in: int | None = None
    avg_response_ms: int | None = None


class CircuitBreakerStatsResponse(OpenSERPModel):
    circuit_breakers: list[CircuitBreakerStat] = Field(default_factory=list)


class StatsResponse(CircuitBreakerStatsResponse):
    cache: CacheStats
    proxy: ProxyStats


class MegaEngineInfo(OpenSERPModel):
    name: str
    initialized: bool
    circuit_state: str | None = None


class MegaEnginesResponse(OpenSERPModel):
    engines: list[MegaEngineInfo] = Field(default_factory=list)
    total: int


class CloudAccount(OpenSERPModel):
    id: str | None = None
    email: str | None = None
    created_at: str | None = None
    credits_remaining: int | None = None
    plan: str | None = None


class Price(OpenSERPModel):
    credits: int | None = None
    price_usd: float | None = None


class Pricing(OpenSERPModel):
    credit_price_usd: float | None = None
    search: Price | None = None
    extract: Price | None = None
    mega_search: Price | None = None
    image_search: Price | None = None
    any_search: Price | None = None
    fast_search: Price | None = None
    any_image: Price | None = None
    fast_image: Price | None = None


class EngineStatus(OpenSERPModel):
    status: str | None = None
    latency_ms: int | None = None


class EnginesStatus(OpenSERPModel):
    overall: str | None = None
    engines: dict[str, EngineStatus] | None = None


class EngineCapability(OpenSERPModel):
    web: bool | None = None
    image: bool | None = None
    fallback_web: bool | None = None
    fallback_image: bool | None = None


class ModeCapability(OpenSERPModel):
    web: bool | None = None
    image: bool | None = None


class EnginesCapabilities(OpenSERPModel):
    engines: dict[str, EngineCapability] | None = None
    modes: dict[str, ModeCapability] | None = None
