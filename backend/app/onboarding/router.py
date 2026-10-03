"""POST /api/v1/admin/onboarding — superadmin-gated onboarding harness endpoint.

Calls the same `app.onboarding.service.run_onboarding` the CLI entrypoint
calls, so the two entrypoints never diverge on provisioning behavior
(design.md M-D2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_superadmin
from app.onboarding.service import OnboardingResult, run_onboarding
from app.onboarding.spec import OnboardingSpec

router = APIRouter(prefix="/admin", tags=["admin"])


async def get_db_session() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    from app.core.database import async_session_factory

    if async_session_factory is None:
        raise RuntimeError("Database not initialized.")

    async with async_session_factory() as session:
        yield session


class OnboardingRequest(BaseModel):
    spec: OnboardingSpec
    dry_run: bool = False


@router.post(
    "/onboarding",
    dependencies=[Depends(require_superadmin)],
    response_model=OnboardingResult,
)
async def post_onboarding(
    payload: OnboardingRequest,
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingResult:
    result = await run_onboarding(payload.spec, session, dry_run=payload.dry_run)
    if not payload.dry_run:
        await session.commit()
    return result
