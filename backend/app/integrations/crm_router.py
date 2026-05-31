"""CRM import API router — triggers Airtable → Qora lead import.

Provides:
- POST /api/v1/clients/{client_id}/crm/import
  Triggers a batch import of leads from the client's configured external CRM
  (Airtable) into Qora's internal database.

Design decisions:
- No auth required for now (dev/demo environment).
- Uses the same DB session pattern as leads/router.py.
- Returns ImportResult counts; never raises on partial failures.
- This is a batch operation triggered manually (not during live calls).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.integrations.crm_import_service import ImportResult, import_leads_from_crm

# Imported at module level for testability (can be patched in tests)
try:
    from app.core.database import async_session_factory
except ImportError:
    async_session_factory = None  # type: ignore[assignment]

router = APIRouter(prefix="/clients", tags=["crm"])


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class ImportResultResponse(BaseModel):
    """JSON-serializable summary of a CRM import run."""

    created: int
    updated: int
    skipped: int
    errors: list[str]

    @classmethod
    def from_result(cls, result: ImportResult) -> "ImportResultResponse":
        return cls(
            created=result.created,
            updated=result.updated,
            skipped=result.skipped,
            errors=result.errors,
        )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/{client_id}/crm/import",
    response_model=ImportResultResponse,
    summary="Import leads from external CRM",
    description=(
        "Triggers a batch import of leads from the client's configured Airtable "
        "base into Qora's internal database. "
        "Creates new leads for phones not yet in Qora; updates existing leads. "
        "Returns a summary with created/updated/skipped/error counts."
    ),
)
async def trigger_crm_import(client_id: str) -> ImportResultResponse:
    """POST /api/v1/clients/{client_id}/crm/import — trigger Airtable → Qora import."""
    import app.integrations.crm_router as _self

    factory = _self.async_session_factory
    if factory is None:
        # Fallback: re-import from database module (handles runtime init)
        from app.core.database import async_session_factory as db_factory

        factory = db_factory

    if factory is None:
        raise RuntimeError("Database not initialized.")

    async with factory() as session:
        result = await import_leads_from_crm(client_id, session)
        await session.commit()

    return ImportResultResponse.from_result(result)
