"""QORA Admin - ElevenLabs reconciliation report endpoints (elevenlabs-reconciler, R-D2).

    GET  /api/v1/admin/elevenlabs/reconciliation       - latest report per agent
    POST /api/v1/admin/elevenlabs/reconciliation/run    - run one pass synchronously

Both superadmin-gated, matching client-integrations-secrets' GET .../status /
import-from-env precedent. The reconciler itself never PATCHes ElevenLabs
(fetch-only, design.md R-D1) - these endpoints only read and trigger that
same fetch-only pass, never a repair action.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_superadmin
from app.elevenlabs.models import ElevenLabsReconciliationReport
from app.elevenlabs.reconciler import run_reconciliation_once

router = APIRouter(prefix="/admin/elevenlabs", tags=["admin"])


async def get_db_session() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    from app.core.database import async_session_factory

    if async_session_factory is None:
        raise RuntimeError("Database not initialized.")

    async with async_session_factory() as session:
        yield session


def _report_to_dict(report: ElevenLabsReconciliationReport) -> dict:
    import json

    return {
        "agent_id": report.agent_id,
        "client_id": report.client_id,
        "status": report.status,
        "drift_fields": json.loads(report.drift_fields) if report.drift_fields else None,
        "status_reason": report.status_reason,
        "checked_at": report.checked_at.isoformat(),
    }


@router.get(
    "/reconciliation",
    dependencies=[Depends(require_superadmin)],
)
async def get_reconciliation_reports(
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return every agent's latest reconciliation report."""
    result = await session.execute(select(ElevenLabsReconciliationReport))
    reports = list(result.scalars().all())
    return {"reports": [_report_to_dict(r) for r in reports]}


@router.post(
    "/reconciliation/run",
    dependencies=[Depends(require_superadmin)],
)
async def run_reconciliation_now(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Run one fetch-only reconciliation pass synchronously and return the
    freshly-updated report rows."""
    settings = request.app.state.settings
    await run_reconciliation_once(session, settings)

    result = await session.execute(select(ElevenLabsReconciliationReport))
    reports = list(result.scalars().all())
    return {"reports": [_report_to_dict(r) for r in reports]}
