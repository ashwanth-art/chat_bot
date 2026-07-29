"""Per-caller request limits and a daily token budget.

Both are enforced in-process. That is honest for a single-instance free-tier
deployment and is reported as such through the audit adapter: an assessor that
reads `scope: "process"` knows this does not survive horizontal scaling.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from app.config import get_settings

_LOCK = threading.RLock()
_WINDOW_SECONDS = 60.0


@dataclass
class _Budget:
    day: str = ""
    tokens_charged: int = 0
    requests_charged: int = 0
    rejections: int = 0


@dataclass
class _State:
    calls: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    budget: _Budget = field(default_factory=_Budget)
    rate_rejections: int = 0


_STATE = _State()


def _today(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _prune(bucket: deque[float], now: float) -> None:
    cutoff = now - _WINDOW_SECONDS
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    reason: str = ""
    retry_after_seconds: int = 0
    detail: str = ""


def check_and_charge(caller_key: str, estimated_tokens: int) -> LimitDecision:
    """Admit or reject one request, charging the rate window and token budget."""
    settings = get_settings()
    now = time.time()
    with _LOCK:
        budget = _STATE.budget
        today = _today(now)
        if budget.day != today:
            _STATE.budget = _Budget(day=today)
            budget = _STATE.budget

        if settings.rate_limit_enabled:
            bucket = _STATE.calls[caller_key]
            _prune(bucket, now)
            allowance = settings.rate_limit_requests_per_minute
            if len(bucket) >= allowance:
                _STATE.rate_rejections += 1
                retry_after = max(1, int(_WINDOW_SECONDS - (now - bucket[0])))
                return LimitDecision(
                    allowed=False,
                    reason="rate_limit",
                    retry_after_seconds=retry_after,
                    detail=(
                        f"The per-caller limit of {allowance} requests per minute was reached."
                    ),
                )
            bucket.append(now)

        if budget.tokens_charged + estimated_tokens > settings.daily_token_budget:
            budget.rejections += 1
            return LimitDecision(
                allowed=False,
                reason="token_budget",
                retry_after_seconds=3600,
                detail="The daily token budget for this deployment is exhausted.",
            )
        budget.tokens_charged += estimated_tokens
        budget.requests_charged += 1
        return LimitDecision(allowed=True)


def limits_configuration() -> dict:
    """The configured ceilings, for the read-only audit adapter."""
    settings = get_settings()
    return {
        "enabled": settings.rate_limit_enabled,
        "scope": "process",
        "requests_per_minute": settings.rate_limit_requests_per_minute,
        "burst": settings.rate_limit_burst,
        "per_caller": True,
        "keyed_on": "tenant identifier",
        "request_timeout_seconds": settings.request_timeout_seconds,
        "max_output_tokens_ceiling": 2048,
        "max_context_chars": settings.max_context_chars,
        "daily_token_budget": settings.daily_token_budget,
        "distributed_enforcement": False,
    }


def limits_usage() -> dict:
    """Live counters, for the monitoring adapter."""
    with _LOCK:
        budget = _STATE.budget
        settings = get_settings()
        charged = budget.tokens_charged
        return {
            "day": budget.day or _today(time.time()),
            "tokens_charged": charged,
            "daily_token_budget": settings.daily_token_budget,
            "budget_utilisation": round(charged / settings.daily_token_budget, 4)
            if settings.daily_token_budget
            else None,
            "requests_charged": budget.requests_charged,
            "rate_limit_rejections": _STATE.rate_rejections,
            "budget_rejections": budget.rejections,
            "tracked_callers": len(_STATE.calls),
        }


def reset_for_tests() -> None:
    global _STATE
    with _LOCK:
        _STATE = _State()
