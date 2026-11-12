"""OpenAI (or stub) reachability probe with a 60 s cache (DESIGN 4.3)."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import openai

from studio import bootstrap, core_adapter

log = logging.getLogger("studio.openai")

CACHE_SECONDS = 60.0
PROBE_TIMEOUT_S = 5.0


@dataclass
class ProbeResult:
    status: str  # ok | not_configured | invalid_key | unreachable | error
    detail: str | None
    checked_at: datetime


_lock = threading.Lock()
_cached: ProbeResult | None = None
_cached_at: float = 0.0


def invalidate() -> None:
    global _cached
    with _lock:
        _cached = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _probe() -> ProbeResult:
    demo = bootstrap.state.demo_mode
    if not bootstrap.state.openai_configured:
        return ProbeResult("not_configured", "OPENAI_API_KEY is not set.", _now())
    service = "The simulated-answer service (stub)" if demo else "OpenAI"
    try:
        core_adapter.probe_openai(PROBE_TIMEOUT_S)
        return ProbeResult("ok", None, _now())
    except (openai.AuthenticationError, openai.PermissionDeniedError):
        return ProbeResult("invalid_key", f"{service} rejected the API key.", _now())
    except openai.APIConnectionError:
        return ProbeResult("unreachable", f"{service} cannot be reached.", _now())
    except openai.RateLimitError:
        return ProbeResult("error", f"{service} is rate limiting requests or the quota is used up.", _now())
    except openai.APIStatusError as exc:
        return ProbeResult("error", f"{service} answered with HTTP {exc.status_code}.", _now())
    except Exception as exc:  # never leak details (could include headers)
        log.warning("OpenAI probe failed: %s", type(exc).__name__)
        return ProbeResult("error", f"{service} check failed unexpectedly.", _now())


def check(refresh: bool = False) -> ProbeResult:
    global _cached, _cached_at
    with _lock:
        if not refresh and _cached is not None and time.monotonic() - _cached_at < CACHE_SECONDS:
            return _cached
    result = _probe()
    with _lock:
        _cached, _cached_at = result, time.monotonic()
    return result
