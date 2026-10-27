from __future__ import annotations

from .models import OpenSERPModel, ResponseMeta


class ContextSource(OpenSERPModel):
    id: str
    url: str
    title: str
    fetched_at: str
    content_sha256: str


class ContextSpan(OpenSERPModel):
    """End-exclusive UTF-8 byte offsets in the exact extracted Markdown."""

    start: int
    end: int


class ContextCitation(OpenSERPModel):
    id: str
    source_id: str
    excerpt: str
    source_span: ContextSpan
    score: float
    truncated: bool


class ContextFailure(OpenSERPModel):
    stage: str
    code: str
    query: str | None = None
    url: str | None = None


class ContextUsage(OpenSERPModel):
    tokenizer: str
    context_tokens: int
    max_tokens: int
    searches: int
    fetches: int


class ContextBilling(OpenSERPModel):
    credits_used: int
    credits_remaining: int


class ContextResult(OpenSERPModel):
    query: str
    queries: list[str]
    context: str
    sources: list[ContextSource]
    citations: list[ContextCitation]
    failures: list[ContextFailure]
    partial: bool
    truncated: bool
    usage: ContextUsage
    meta: ResponseMeta
    billing: ContextBilling | None = None
