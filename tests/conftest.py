"""Hermetic settings for the test suite.

The evidence surfaces read configuration, so the suite has to supply a complete
settings object. These values are throwaway fixtures: they never reach a network
call, and the audit-adapter tests assert that no key material is ever returned.
Environment variables take precedence over a local `.env`, so a developer's real
configuration cannot leak into a test result.
"""

import pytest

from app.config import get_settings
from app.limits import reset_for_tests

FIXTURE_ENV = {
    "APP_ENV": "test",
    "CHATBOT_API_KEY": "0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d",
    "CLOUD_AUDIT_API_KEY": "1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e",
    "MONITORING_API_KEY": "2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f",
    "OPENAI_API_KEY": "sk-test-0000000000000000000000000000",
    "MONGODB_URI": "mongodb://localhost:27017/test-fixture-database",
    "ALLOW_ORIGINS": "http://localhost:8000",
}


@pytest.fixture(autouse=True)
def _fixture_settings(monkeypatch):
    for name, value in FIXTURE_ENV.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    reset_for_tests()
    yield
    get_settings.cache_clear()
    reset_for_tests()
