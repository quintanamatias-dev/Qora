"""QORA n8n — FastAPI dependency for internal API secret validation.

Checks the X-Internal-Secret header on all internal API endpoints.
Returns 401 if the header is absent or does not match INTERNAL_API_KEY setting.
"""

from __future__ import annotations

from fastapi import Header, HTTPException


def _get_settings():
    """Return application Settings instance.

    Extracted as a separate function so tests can patch it easily.
    """
    from app.core.config import Settings

    return Settings()


async def verify_internal_secret(
    x_internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
) -> None:
    """FastAPI dependency that validates the X-Internal-Secret header.

    Raises:
        HTTPException 401: If the header is absent or the value doesn't match
            the configured N8N_INTERNAL_API_KEY setting.
    """
    settings = _get_settings()
    expected = settings.n8n_internal_api_key.get_secret_value()

    if not x_internal_secret or x_internal_secret != expected:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: invalid or missing X-Internal-Secret",
        )
