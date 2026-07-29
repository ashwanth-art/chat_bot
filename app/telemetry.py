import hashlib
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import Any

MAX_TRACES = 500
TRACE_TTL_SECONDS = 60 * 60

_traces: OrderedDict[str, dict[str, Any]] = OrderedDict()
_lock = RLock()


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


def get_trace(request_id: str) -> dict[str, Any] | None:
    with _lock:
        _prune(time.monotonic())
        trace = _traces.get(request_id)
        if not trace:
            return None
        result = deepcopy(trace)
        result.pop("_created_monotonic", None)
        return result
