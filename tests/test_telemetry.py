from app.telemetry import (
    NOTABLE_STATUSES,
    complete_trace,
    get_trace,
    metric_series,
    notable_events,
    record_outcome,
    record_stage,
    start_trace,
)


def test_request_trace_is_sanitized_and_correlated():
    request_id = "trace-test-123456"
    start_trace(request_id, "tenant-with-sensitive-name")
    record_stage(
        request_id,
        name="retrieval",
        status="pass",
        summary="Tenant-filtered retrieval completed.",
        duration_ms=12,
        metrics={"chunks": 3, "top_score": 0.91},
    )
    complete_trace(request_id, status="success", duration_ms=20)

    trace = get_trace(request_id)
    assert trace is not None
    assert trace["request_id"] == request_id
    assert trace["tenant_fingerprint"] != "tenant-with-sensitive-name"
    assert trace["status"] == "success"
    assert trace["duration_ms"] == 20
    assert trace["stages"][0]["name"] == "retrieval"
    assert trace["stages"][0]["metrics"]["chunks"] == 3
    assert "_created_monotonic" not in trace


def test_outcomes_bucket_into_a_series_a_monitor_can_read_a_trend_from():
    before = metric_series()["buckets"]
    seen_before = sum(bucket["requests"] for bucket in before)

    record_outcome(status="success", duration_ms=120, endpoint="chat", request_id="s-1")
    record_outcome(status="success", duration_ms=280, endpoint="chat", request_id="s-2")
    record_outcome(
        status="blocked",
        duration_ms=8,
        endpoint="chat",
        request_id="s-3",
        reason="prompt_injection",
    )

    series = metric_series()
    assert series["bucket_seconds"] == 60
    assert series["contains_prompt_or_response"] is False
    totals = {
        "requests": sum(bucket["requests"] for bucket in series["buckets"]),
        "successes": sum(bucket["successes"] for bucket in series["buckets"]),
        "blocks": sum(bucket["guardrail_blocks"] for bucket in series["buckets"]),
    }
    assert totals["requests"] == seen_before + 3
    assert totals["successes"] >= 2
    assert totals["blocks"] >= 1
    latest = series["buckets"][-1]
    assert latest["mean_duration_ms"] > 0
    assert latest["max_duration_ms"] >= latest["mean_duration_ms"]


def test_only_notable_outcomes_become_events_and_they_carry_no_prompt():
    record_outcome(status="success", duration_ms=90, endpoint="chat", request_id="e-success")
    record_outcome(
        status="dependency_error",
        duration_ms=1400,
        endpoint="chat",
        request_id="e-error",
        reason="APIError",
    )

    feed = notable_events()
    assert feed["contains_prompt_or_response"] is False
    assert set(feed["kinds_tracked"]) == NOTABLE_STATUSES
    ids = [event["request_id"] for event in feed["events"]]
    assert "e-error" in ids, "a dependency error is notable and must be kept"
    assert "e-success" not in ids, "a successful request is the baseline, not an event"
    error = next(event for event in feed["events"] if event["request_id"] == "e-error")
    assert error["reason"] == "APIError"
    assert error["duration_ms"] == 1400
    assert "_created_monotonic" not in error
    # Newest first, so a monitor reading the head sees what just happened.
    assert feed["events"][0]["request_id"] == "e-error"
