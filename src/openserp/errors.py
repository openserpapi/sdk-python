from __future__ import annotations

from typing import Any

API_KEYS_URL = "https://openserp.org/dashboard/keys"
SUPPORT_HINT = (
    "OpenSERP docs: https://openserp.org/docs | "
    "GitHub issues: https://github.com/openserpapi/sdk-python/issues"
)


class SERPError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
        meta: dict[str, Any] | None = None,
        response: Any = None,
    ) -> None:
        super().__init__(_with_support_hint(message))
        self.status = status
        self.code = code
        self.reason = reason
        self.request_id = request_id
        self.meta = meta
        self.response = response


class RateLimitError(SERPError):
    pass


class CaptchaError(SERPError):
    pass


class InsufficientCreditsError(SERPError):
    """Raised on 402 when the account is out of credits.

    ``topup_url`` points at the dashboard page that accepts card and crypto
    payments, so an integration can surface a working link instead of a bare
    error string.
    """

    def __init__(
        self,
        message: str,
        *,
        topup_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.topup_url = topup_url


class CloudOnlyError(SERPError):
    def __init__(self, method: str) -> None:
        super().__init__(
            f"{method} is only available against OpenSERP Cloud. "
            "Configure api_key/base_url for https://api.openserp.org/v1 "
            f'or set backend="cloud". Get an API key: {API_KEYS_URL}'
        )


class OssOnlyError(SERPError):
    def __init__(self, method: str) -> None:
        super().__init__(
            f"{method} is only available against a self-hosted OpenSERP server. "
            'Configure base_url for your OSS server or set backend="oss".'
        )


class TimeoutError(SERPError):
    def __init__(self, timeout: float) -> None:
        super().__init__(
            f"OpenSERP request timed out after {timeout:g}s",
            code="request_timeout",
        )


def error_from_response(
    status: int,
    body: Any,
    request_id: str | None = None,
) -> SERPError:
    data = body if isinstance(body, dict) else {}
    code = data.get("error")
    message = data.get("message") or f"OpenSERP request failed with status {status}"
    options = {
        "status": status,
        "code": code,
        "reason": data.get("reason"),
        "request_id": data.get("request_id") or request_id,
        "meta": data.get("meta"),
        "response": body,
    }

    if status == 429 or code == "rate_limited":
        return RateLimitError(message, **options)

    if code == "captcha_detected":
        return CaptchaError(message, **options)

    if status == 402 or code == "insufficient_credits":
        topup_url = data.get("topup_url")
        return InsufficientCreditsError(
            message,
            topup_url=topup_url if isinstance(topup_url, str) else None,
            **options,
        )

    return SERPError(message, **options)


def _with_support_hint(message: str) -> str:
    if "github.com/openserpapi/sdk-python" in message or "openserp.org/docs" in message:
        return message
    separator = "" if message.endswith(".") else "."
    return f"{message}{separator} {SUPPORT_HINT}"
