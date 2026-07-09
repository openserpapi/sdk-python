from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

DebugLevel = Literal["off", "info", "verbose"]

# A debug setting may be a bool, a level string, or a callable sink that
# receives structured DebugEvent objects.
DebugSetting = bool | Literal["info", "verbose"] | Callable[["DebugEvent"], None] | None


@dataclass(frozen=True)
class DebugEvent:
    """A single request/response lifecycle event emitted when debug is on."""

    type: Literal["request", "response", "error"]
    method: str
    url: str
    status: int | None = None
    engine_used: str | None = None
    request_id: str | None = None
    duration_ms: int | None = None
    error: BaseException | None = None
    # Present only at "verbose" level. Authorization is redacted.
    headers: Mapping[str, str] | None = None


@dataclass(frozen=True)
class DebugReporter:
    """Resolved debug behaviour: the active level and where events go."""

    level: DebugLevel
    _emit: Callable[[DebugEvent], None]

    def emit(self, event: DebugEvent) -> None:
        if self.level == "off":
            return
        self._emit(event)


_OFF = DebugReporter(level="off", _emit=lambda _event: None)


def resolve_debug(setting: DebugSetting) -> DebugReporter:
    """Resolve the effective debug behaviour from the client setting.

    Falls back to the OPENSERP_DEBUG env var (``1``/``true``/``verbose``) when
    *setting* is None, so debugging can be toggled without code changes.
    """
    if setting is None:
        setting = _env_debug()

    if not setting:
        return _OFF

    if callable(setting):
        # A custom sink always sees verbose detail; it decides what to keep.
        return DebugReporter(level="verbose", _emit=_guard(setting))

    level: DebugLevel = "verbose" if setting == "verbose" else "info"
    return DebugReporter(level=level, _emit=_console_sink)


def _env_debug() -> bool | Literal["verbose"] | None:
    value = os.environ.get("OPENSERP_DEBUG")
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized == "verbose":
        return "verbose"
    if normalized in ("1", "true"):
        return True
    return None


def _guard(sink: Callable[[DebugEvent], None]) -> Callable[[DebugEvent], None]:
    """Wrap a user sink so a broken logger never breaks the actual request."""

    def wrapped(event: DebugEvent) -> None:
        # A broken user logger must never break the actual request.
        with contextlib.suppress(Exception):
            sink(event)

    return wrapped


def _console_sink(event: DebugEvent) -> None:
    if event.type == "request":
        print(f"[openserp] → {event.method} {event.url}", file=sys.stderr)
        if event.headers:
            print(f"[openserp]   headers: {dict(event.headers)}", file=sys.stderr)
    elif event.type == "response":
        engine = f" engine={event.engine_used}" if event.engine_used else ""
        req_id = f" request-id={event.request_id}" if event.request_id else ""
        print(
            f"[openserp] ← {event.status} {event.method} {event.url} "
            f"({event.duration_ms}ms){engine}{req_id}",
            file=sys.stderr,
        )
        if event.headers:
            print(f"[openserp]   headers: {dict(event.headers)}", file=sys.stderr)
    elif event.type == "error":
        print(
            f"[openserp] ✕ {event.method} {event.url} "
            f"({event.duration_ms}ms): {event.error!r}",
            file=sys.stderr,
        )


def dump_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    """Snapshot headers into a plain dict, redacting Authorization."""
    out: dict[str, str] = {}
    for key, value in headers.items():
        out[key] = "Bearer ***" if key.lower() == "authorization" else str(value)
    return out
