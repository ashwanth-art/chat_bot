import hashlib
import time
from collections import OrderedDict, deque
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import Any

MAX_TRACES = 500
TRACE_TTL_SECONDS = 60 * 60

# A monitor asking "what changed since last time?" cannot answer from a cumulative
# counter, so completed requests are also bucketed by minute. The window is short and
# capped on purpose: this is a trend surface for monitoring, not a log store, and it
# holds no prompt, no response and no tenant identifier beyond the fingerprint.
SERIES_BUCKET_SECONDS = 60
MAX_SERIES_BUCKETS = 120

# Notable events only — a block, a refusal, a dependency error, a limit rejection.
# A successful request is not an event; it is the baseline.
MAX_EVENTS = 200
EVENT_TTL_SECONDS = 6 * 60 * 60

_traces: OrderedDict[str, dict[str, Any]] = OrderedDict()
_series: OrderedDict[int, dict[str, Any]] = OrderedDict()
_events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
_lock = RLock()

# The same status vocabulary the chatbot_requests_total counter uses, so a bucket and a
# scrape of /metrics can never disagree about what happened.
NOTABLE_STATUSES = {"blocked", "bounded_refusal", "dependency_error", "rate_limited"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _tenant_fingerprint(tenant_id: str) -> str:
    return hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:12]


def _prune(now_monotonic: float) -> None:
    expired = [
        request_id
        for request_id, trace in _traces.items()
        if now_monotonic - float(trace["_created_monotonic"]) > TRACE_TTL_SECONDS
    ]
    for request_id in expired:
        _traces.pop(request_id, None)
    while len(_traces) > MAX_TRACES:
        _traces.popitem(last=False)


def start_trace(request_id: str, tenant_id: str) -> None:
    now_monotonic = time.monotonic()
    with _lock:
        _prune(now_monotonic)
        _traces[request_id] = {
            "schema_version": "1.0",
            "request_id": request_id,
            "tenant_fingerprint": _tenant_fingerprint(tenant_id),
            "status": "running",
            "started_at": _now(),
            "completed_at": None,
            "duration_ms": None,
            "stages": [],
            "_created_monotonic": now_monotonic,
        }


def record_stage(
    request_id: str,
    *,
    name: str,
    status: str,
    summary: str,
    duration_ms: int,
    metrics: dict[str, int | float | bool | str] | None = None,
) -> None:
    with _lock:
        trace = _traces.get(request_id)
        if not trace:
            return
        trace["stages"].append(
            {
                "name": name,
                "status": status,
                "summary": summary,
                "duration_ms": max(0, int(duration_ms)),
                "recorded_at": _now(),
                "metrics": metrics or {},
            }
        )
        _traces.move_to_end(request_id)


def complete_trace(request_id: str, *, status: str, duration_ms: int) -> None:
    with _lock:
        trace = _traces.get(request_id)
        if not trace:
            return
        trace["status"] = status
        trace["completed_at"] = _now()
        trace["duration_ms"] = max(0, int(duration_ms))
        _traces.move_to_end(request_id)


def _bucket_start(epoch_seconds: float) -> int:
    return int(epoch_seconds // SERIES_BUCKET_SECONDS) * SERIES_BUCKET_SECONDS


def record_outcome(
    *,
    status: str,
    duration_ms: int,
    endpoint: str,
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Bucket one finished request, and keep it as an event if it was notable.

    Called once per request from the request path. Failing to record must never fail
    the request, so everything here is arithmetic on in-memory structures.
    """
    now = time.time()
    bucket_key = _bucket_start(now)
    with _lock:
        bucket = _series.get(bucket_key)
        if bucket is None:
            bucket = {
                "bucket_start": datetime.fromtimestamp(bucket_key, UTC).isoformat(),
                "requests": 0,
                "successes": 0,
                "guardrail_blocks": 0,
                "bounded_refusals": 0,
                "dependency_errors": 0,
                "limit_rejections": 0,
                "duration_ms_total": 0,
                "duration_ms_max": 0,
            }
            _series[bucket_key] = bucket
        bucket["requests"] += 1
        bucket["duration_ms_total"] += max(0, int(duration_ms))
        bucket["duration_ms_max"] = max(bucket["duration_ms_max"], max(0, int(duration_ms)))
        counted = {
            "success": "successes",
            "blocked": "guardrail_blocks",
            "bounded_refusal": "bounded_refusals",
            "dependency_error": "dependency_errors",
            "rate_limited": "limit_rejections",
        }.get(status)
        if counted:
            bucket[counted] += 1
        while len(_series) > MAX_SERIES_BUCKETS:
            _series.popitem(last=False)

        if status in NOTABLE_STATUSES:
            _events.append(
                {
                    "at": _now(),
                    "status": status,
                    "endpoint": endpoint,
                    "reason": reason or status,
                    "request_id": request_id,
                    "duration_ms": max(0, int(duration_ms)),
                    "_created_monotonic": time.monotonic(),
                }
            )


def metric_series() -> dict[str, Any]:
    """Per-minute buckets, oldest first. Empty until the service has served a request."""
    with _lock:
        buckets = []
        for bucket in _series.values():
            requests = int(bucket["requests"])
            buckets.append(
                {
                    "bucket_start": bucket["bucket_start"],
                    "requests": requests,
                    "successes": int(bucket["successes"]),
                    "guardrail_blocks": int(bucket["guardrail_blocks"]),
                    "bounded_refusals": int(bucket["bounded_refusals"]),
                    "dependency_errors": int(bucket["dependency_errors"]),
                    "limit_rejections": int(bucket["limit_rejections"]),
                    "mean_duration_ms": (
                        round(int(bucket["duration_ms_total"]) / requests) if requests else 0
                    ),
                    "max_duration_ms": int(bucket["duration_ms_max"]),
                }
            )
        return {
            "schema_version": "1.0",
            "bucket_seconds": SERIES_BUCKET_SECONDS,
            "buckets_retained": MAX_SERIES_BUCKETS,
            "window_seconds": SERIES_BUCKET_SECONDS * MAX_SERIES_BUCKETS,
            "store": "in-memory, per-process, capped and lost on restart",
            "contains_prompt_or_response": False,
            "buckets": buckets,
        }


def notable_events() -> dict[str, Any]:
    """Recent blocks, refusals, errors and limit rejections. No prompt content."""
    now_monotonic = time.monotonic()
    with _lock:
        live = [
            event
            for event in _events
            if now_monotonic - float(event["_created_monotonic"]) <= EVENT_TTL_SECONDS
        ]
        return {
            "schema_version": "1.0",
            "retention_seconds": EVENT_TTL_SECONDS,
            "capacity": MAX_EVENTS,
            "recorded": len(live),
            "kinds_tracked": sorted(NOTABLE_STATUSES),
            "contains_prompt_or_response": False,
            "events": [
                {key: value for key, value in event.items() if key != "_created_monotonic"}
                for event in reversed(live)
            ],
        }


def get_trace(request_id: str) -> dict[str, Any] | None:
    with _lock:
        _prune(time.monotonic())
        trace = _traces.get(request_id)
        if not trace:
            return None
        result = deepcopy(trace)
        result.pop("_created_monotonic", None)
        return result
