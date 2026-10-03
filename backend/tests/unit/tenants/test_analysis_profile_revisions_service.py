"""Phase 2 (analysis-profiles) — Task 2.1: analysis-profile revisions service.

Covers: resolve_client_catalog, create_analysis_profile_revision (insert-only),
rollback_analysis_profile_revision (creates a NEW revision, never resurrects),
apply_analysis_profile_template. Built on revisions_service.py's existing
generic private helpers (design.md P5-D2), same reuse already demonstrated
for Agent/AgentConfigRevision and Client/ClientConfigRevision.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def session(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/analysis_profile_revisions_service_test.db",
    )
    await init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        yield sess

    await db_module.engine.dispose()


async def _seed_quintana(session: AsyncSession):
    from app.tenants.service import seed_quintana

    await seed_quintana(session)
    await session.commit()


async def test_resolve_client_catalog_returns_active_revision_config(session: AsyncSession):
    from app.tenants import revisions_service
    from app.analysis.profiles.templates import insurance
    from app.tenants.models import Client

    await _seed_quintana(session)

    # seed_quintana() applies the insurance template directly to revision 1
    # (Gap A) \u2014 confirm that default, then apply a fresh insurance
    # revision explicitly and confirm resolution reflects the new revision.
    seeded_config = await revisions_service.resolve_client_catalog(session, "quintana-seguros")
    assert {p.id for p in seeded_config.products} == {p.id for p in insurance.config.products}
    assert seeded_config.vertical == "insurance"

    client = await session.get(Client, "quintana-seguros")
    assert client is not None
    await revisions_service.apply_analysis_profile_template(
        session, client=client, vertical="insurance", created_by="tester"
    )
    await session.commit()

    config = await revisions_service.resolve_client_catalog(session, "quintana-seguros")

    assert {p.id for p in config.products} == {p.id for p in insurance.config.products}
    assert {n.id for n in config.need_tags} == {n.id for n in insurance.config.need_tags}
    assert config.vertical == "insurance"


async def test_create_revision_does_not_mutate_existing_rows(session: AsyncSession):
    from app.tenants import revisions_service
    from app.analysis.profiles.schema import AnalysisProfileConfigV1
    from app.tenants.models import Client, ClientAnalysisProfileRevision

    await _seed_quintana(session)
    client = await session.get(Client, "quintana-seguros")
    assert client is not None
    first_active_id = client.active_analysis_profile_revision_id

    new_config = AnalysisProfileConfigV1(vertical="generic", products=[], need_tags=[])
    revision = await revisions_service.create_analysis_profile_revision(
        session,
        client=client,
        config=new_config,
        source="api",
        created_by="tester",
    )
    await session.commit()

    assert revision.revision_number == 2
    assert client.active_analysis_profile_revision_id == revision.id

    original = await session.get(ClientAnalysisProfileRevision, first_active_id)
    assert original is not None
    assert original.revision_number == 1

    result = await session.execute(
        select(ClientAnalysisProfileRevision).where(
            ClientAnalysisProfileRevision.client_id == "quintana-seguros"
        )
    )
    assert len(result.scalars().all()) == 2


async def test_rollback_creates_new_revision_not_resurrection(session: AsyncSession):
    from app.tenants import revisions_service
    from app.analysis.profiles.schema import AnalysisProfileConfigV1
    from app.tenants.models import Client

    await _seed_quintana(session)
    client = await session.get(Client, "quintana-seguros")
    assert client is not None
    revision_1_id = client.active_analysis_profile_revision_id

    await revisions_service.create_analysis_profile_revision(
        session,
        client=client,
        config=AnalysisProfileConfigV1(vertical="generic", products=[], need_tags=[]),
        source="api",
        created_by="tester",
    )
    await session.commit()
    assert client.active_analysis_profile_revision_id != revision_1_id

    new_revision = await revisions_service.rollback_analysis_profile_revision(
        session,
        client_id="quintana-seguros",
        target_revision_id=revision_1_id,
        created_by="tester",
    )
    await session.commit()

    assert new_revision is not None
    assert new_revision.revision_number == 3
    assert new_revision.source == "rollback"
    assert client.active_analysis_profile_revision_id == new_revision.id
    assert client.active_analysis_profile_revision_id != revision_1_id


async def test_apply_template_creates_revision_from_code_data(session: AsyncSession):
    from app.tenants import revisions_service
    from app.analysis.profiles.templates import insurance
    from app.tenants.models import Client

    await _seed_quintana(session)
    client = await session.get(Client, "quintana-seguros")
    assert client is not None

    revision = await revisions_service.apply_analysis_profile_template(
        session,
        client=client,
        vertical="insurance",
        created_by="tester",
    )
    await session.commit()

    from app.analysis.profiles.schema import AnalysisProfileConfigV1

    config = AnalysisProfileConfigV1.model_validate_json(revision.config)
    assert {p.id for p in config.products} == {p.id for p in insurance.config.products}
    assert {n.id for n in config.need_tags} == {n.id for n in insurance.config.need_tags}
