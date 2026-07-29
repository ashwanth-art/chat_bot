import re

INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bignore (all|any|the|your) (previous|prior|above) instructions?\b",
        r"\breveal (the )?(system|developer) prompt\b",
        r"\bprint (your|the) hidden instructions?\b",
        r"\bact as (an? )?(unrestricted|unfiltered|jailbroken)\b",
        r"\bexfiltrat(e|ion)\b",
    )
]

SENSITIVE_EXTRACTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:return|reveal|show|list|print)\b.{0,80}\b"
        r"(?:api keys?|passwords?|bearer tokens?|private credentials?|connection strings?)\b",
        r"\b(?:every|all)\b.{0,40}\b(?:api keys?|passwords?|bearer tokens?|private credentials?)\b",
    )
]

UNSUPPORTED_REALTIME_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:current|live|right now|today'?s?)\b.{0,40}\b(?:weather|temperature|forecast)\b",
        r"\b(?:weather|temperature|forecast)\b.{0,40}\b(?:current|live|right now|today)\b",
    )
]

PII_PATTERNS = [
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[EMAIL REDACTED]"),
    (re.compile(r"\b(?:\+?\d[\d .()-]{8,}\d)\b"), "[PHONE REDACTED]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ID REDACTED]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[CARD REDACTED]"),
]


def contains_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in INJECTION_PATTERNS)


def contains_sensitive_extraction_request(text: str) -> bool:
    return any(pattern.search(text) for pattern in SENSITIVE_EXTRACTION_PATTERNS)


def contains_unsupported_realtime_request(text: str) -> bool:
    return any(pattern.search(text) for pattern in UNSUPPORTED_REALTIME_PATTERNS)


def redact_pii(text: str) -> str:
    for pattern, replacement in PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def chunk_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    """Split normalized text into bounded, overlapping chunks."""
    clean = " ".join(text.replace("\x00", " ").split())
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + size)
        if end < len(clean):
            boundary = clean.rfind(" ", start, end)
            if boundary > start + size // 2:
                end = boundary
        chunks.append(clean[start:end].strip())
        if end >= len(clean):
            break
        start = max(start + 1, end - overlap)
    return chunks
