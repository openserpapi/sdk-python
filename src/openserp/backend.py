from __future__ import annotations

from urllib.parse import urlparse

from .models import Backend

OSS_BASE_URL = "http://localhost:7000"
CLOUD_BASE_URL = "https://api.openserp.org/v1"


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def resolve_base_url(api_key: str | None = None, base_url: str | None = None) -> str:
    if base_url:
        return normalize_base_url(base_url)
    if api_key:
        return CLOUD_BASE_URL
    return OSS_BASE_URL


def infer_backend(
    api_key: str | None = None,
    base_url: str | None = None,
    backend: Backend | None = None,
) -> Backend:
    if backend:
        return backend

    if base_url:
        try:
            if urlparse(base_url).hostname == "api.openserp.org":
                return "cloud"
        except ValueError:
            if "api.openserp.org" in base_url:
                return "cloud"

    if api_key:
        return "cloud"

    return "oss"
