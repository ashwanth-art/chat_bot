from app.config import get_settings
from app.limits import check_and_charge, limits_configuration, limits_usage, reset_for_tests


def test_requests_are_admitted_within_the_ceiling():
    for _ in range(5):
        assert check_and_charge("tenant-a", 100).allowed


def test_the_per_caller_ceiling_refuses_and_reports_retry_after(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "3")
    get_settings.cache_clear()
    reset_for_tests()

    assert check_and_charge("tenant-b", 10).allowed
    assert check_and_charge("tenant-b", 10).allowed
    assert check_and_charge("tenant-b", 10).allowed
    decision = check_and_charge("tenant-b", 10)
    assert not decision.allowed
    assert decision.reason == "rate_limit"
    assert decision.retry_after_seconds >= 1
    assert "3 requests per minute" in decision.detail


def test_the_ceiling_is_per_caller_not_global(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "2")
    get_settings.cache_clear()
    reset_for_tests()

    assert check_and_charge("tenant-c", 10).allowed
    assert check_and_charge("tenant-c", 10).allowed
    assert not check_and_charge("tenant-c", 10).allowed
    # A different caller is unaffected by another caller's exhausted window.
    assert check_and_charge("tenant-d", 10).allowed


def test_the_daily_token_budget_refuses_before_the_model_is_called(monkeypatch):
    monkeypatch.setenv("DAILY_TOKEN_BUDGET", "1000")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "6000")
    get_settings.cache_clear()
    reset_for_tests()

    assert check_and_charge("tenant-e", 700).allowed
    decision = check_and_charge("tenant-e", 700)
    assert not decision.allowed
    assert decision.reason == "token_budget"
    assert limits_usage()["budget_rejections"] == 1
    assert limits_usage()["tokens_charged"] == 700


def test_usage_reports_budget_utilisation():
    check_and_charge("tenant-f", 500)
    usage = limits_usage()
    assert usage["tokens_charged"] >= 500
    assert 0 <= usage["budget_utilisation"] <= 1
    assert usage["requests_charged"] >= 1


def test_configuration_does_not_overstate_enforcement_scope():
    configuration = limits_configuration()
    assert configuration["scope"] == "process"
    assert configuration["distributed_enforcement"] is False
    assert configuration["per_caller"] is True
