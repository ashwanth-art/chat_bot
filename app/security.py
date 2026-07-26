import hashlib
import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings


def stable_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A Bearer API key is required.",
        )
    return authorization.removeprefix("Bearer ").strip()


def require_chatbot_key(authorization: str | None = Header(default=None)) -> None:
    if not secrets.compare_digest(_extract_bearer(authorization), get_settings().chatbot_api_key):
        raise HTTPException(status_code=403, detail="Invalid chatbot API key.")


def require_audit_key(authorization: str | None = Header(default=None)) -> None:
    if not secrets.compare_digest(
        _extract_bearer(authorization), get_settings().cloud_audit_api_key
    ):
        raise HTTPException(status_code=403, detail="Invalid read-only audit API key.")


def require_monitoring_key(authorization: str | None = Header(default=None)) -> None:
    if not secrets.compare_digest(
        _extract_bearer(authorization), get_settings().monitoring_api_key
    ):
        raise HTTPException(status_code=403, detail="Invalid monitoring API key.")
