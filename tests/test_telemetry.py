from app.telemetry import complete_trace, get_trace, record_stage, start_trace


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
