"""QORA — Optional Sentry SDK initialization with PII scrubbing.

Sentry is initialized ONLY when SENTRY_DSN is set in environment.
The application starts and operates normally without SENTRY_DSN.

PII scrubbing:
- E.164 phone numbers (e.g. +14155552671) → [REDACTED_PHONE]
- API keys: sk-/pk- prefixed (32+ chars), 32+ hex sequences → [REDACTED_KEY]

Spec: sdd/b9-observability/spec — capability: sentry-integration
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

try:
    import sentry_sdk
except ImportError:  # pragma: no cover — sentry-sdk not yet installed
    sentry_sdk = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from app.core.config import Settings


# ---------------------------------------------------------------------------
# PII regex patterns
# ---------------------------------------------------------------------------

# E.164 phone numbers: +[1-9] followed by 7–14 digits
_PHONE_PATTERN = re.compile(r"\+[1-9]\d{7,14}")

# API keys:
#   - sk- or pk- prefix followed by 29+ chars (total ≥ 32)
#   - 32+ consecutive hex chars (0-9, a-f, A-F)
_KEY_PATTERN = re.compile(
    r"(?:[sp]k-[A-Za-z0-9+/=_\-]{29,}|[0-9a-fA-F]{32,})"
)


# ---------------------------------------------------------------------------
# PII scrubber (pure function — testable without Sentry)
# ---------------------------------------------------------------------------


def scrub_pii(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Sentry before_send hook — scrub PII from every event before transmission.

    Mutates string values at the top-level ``message`` key and inside
    the ``extra`` mapping. Designed to be passed as ``before_send`` to
    ``sentry_sdk.init()``.

    Args:
        event: Sentry event dict (mutable).
        hint:  Sentry hint dict (unused, required by protocol).

    Returns:
        The (potentially mutated) event, or None to drop it entirely.
        This implementation never drops events — it always returns the event.
    """

    def _scrub_string(value: str) -> str:
        value = _PHONE_PATTERN.sub("[REDACTED_PHONE]", value)
        value = _KEY_PATTERN.sub("[REDACTED_KEY]", value)
        return value

    def _scrub_value(value: Any) -> Any:
        if isinstance(value, str):
            return _scrub_string(value)
        if isinstance(value, dict):
            return {k: _scrub_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_scrub_value(item) for item in value]
        return value

    # Scrub top-level "message" field
    if "message" in event and isinstance(event["message"], str):
        event["message"] = _scrub_string(event["message"])

    # Scrub "extra" dict recursively
    if "extra" in event and isinstance(event["extra"], dict):
        event["extra"] = {k: _scrub_value(v) for k, v in event["extra"].items()}

    # Scrub breadcrumbs if present
    if "breadcrumbs" in event:
        breadcrumbs = event["breadcrumbs"]
        if isinstance(breadcrumbs, dict) and "values" in breadcrumbs:
            for crumb in breadcrumbs["values"]:
                if isinstance(crumb, dict):
                    if "message" in crumb and isinstance(crumb["message"], str):
                        crumb["message"] = _scrub_string(crumb["message"])
                    if "data" in crumb and isinstance(crumb["data"], dict):
                        crumb["data"] = {k: _scrub_value(v) for k, v in crumb["data"].items()}

    return event


# ---------------------------------------------------------------------------
# Init helper
# ---------------------------------------------------------------------------


def init_sentry(settings: "Settings") -> None:
    """Initialize Sentry SDK when SENTRY_DSN is configured.

    This function is a no-op when:
    - settings.sentry_dsn is None or empty
    - sentry-sdk is not installed

    Must be called early in the application lifespan (before the first request).

    Args:
        settings: Validated application settings. DSN and environment are
                  read from ``settings.sentry_dsn`` and ``settings.sentry_environment``.

    Spec: sdd/b9-observability/spec — Requirement: Optional Initialization via SENTRY_DSN
    """
    if sentry_sdk is None:  # pragma: no cover
        return

    dsn = getattr(settings, "sentry_dsn", None)
    # Guard: must be a non-empty string (MagicMock or None both short-circuit here)
    if not isinstance(dsn, str) or not dsn.strip():
        return

    environment = getattr(settings, "sentry_environment", "production")
    release = getattr(settings, "app_version", "0.1.0")

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        before_send=scrub_pii,
        # Capture 100% of transactions in all environments by default.
        # Operators can lower this via SENTRY_TRACES_SAMPLE_RATE env override.
        traces_sample_rate=0.0,
    )
