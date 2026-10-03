"""Phase 4.1 — leads/router.py dimension-rollups reads the resolved per-client
catalog (via resolve_client_catalog) instead of the global PRODUCT_CATALOG/
NEED_TAGS constants.

RED (pre-change): a product id that is valid for Quintana's insurance catalog
(a global constant) incorrectly leaks into a DIFFERENT client's rollup even
though that client's own resolved catalog does not contain it — proving the
filter is globally fixed, not per-client.

GREEN (post-change): the same product id is correctly excluded from the
other client's rollup because the filter is scoped to THAT client's resolved
catalog.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


@pytest_asyncio.fixture
async def catalog_cutover_client(tmp_path: Path):
    """Isolated DB with Quintana (insurance catalog via seed_quintana) and a
    second client with a distinct, non-insurance catalog."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/dimension_rollups_cutover.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import create_client, seed_quintana
        from app.leads.service import create_lead
        from app.tenants.models import Client
        from app.tenants.revisions_service import create_analysis_profile_revision
        from app.analysis.profiles.schema import AnalysisProfileConfigV1, NeedTagEntry, ProductEntry
        from app.calls.models import CallAnalysis, CallSession

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Quintana Lead",
            phone="+5491100777001",
            lead_id="lead-quintana-cutover",
        )

        await create_client(
            sess,
            id="custom-client",
            name="Custom Client",
            voice_id="v1",
        )
        custom_client = await sess.get(Client, "custom-client")
        await create_analysis_profile_revision(
            sess,
            client=custom_client,
            config=AnalysisProfileConfigV1(
                vertical="custom",
                products=[ProductEntry(id="widget_a", label_es="Widget A", label_en="Widget A")],
                need_tags=[NeedTagEntry(id="speed", label_es="Rapidez", label_en="Speed")],
            ),
            source="api",
            created_by="test",
        )
        await create_lead(
            sess,
            client_id="custom-client",
            name="Custom Lead",
            phone="+5491100777002",
            lead_id="lead-custom-cutover",
        )

        quintana_session = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id="lead-quintana-cutover",
            status="completed",
            started_at=datetime.now(timezone.utc),
        )
        sess.add(quintana_session)
        sess.add(
            CallAnalysis(
                id=str(uuid.uuid4()),
                session_id=quintana_session.id,
                lead_id="lead-quintana-cutover",
                client_id="quintana-seguros",
                products=json.dumps(["auto_todo_riesgo", "hogar"]),
                specific_needs=json.dumps(["precio_competitivo"]),
                service_issues=json.dumps([]),
            )
        )

        custom_session = CallSession(
            id=str(uuid.uuid4()),
            client_id="custom-client",
            lead_id="lead-custom-cutover",
            status="completed",
            started_at=datetime.now(timezone.utc),
        )
        sess.add(custom_session)
        sess.add(
            CallAnalysis(
                id=str(uuid.uuid4()),
                session_id=custom_session.id,
                lead_id="lead-custom-cutover",
                client_id="custom-client",
                # "auto_todo_riesgo" is a valid GLOBAL PRODUCT_CATALOG id (Quintana's)
                # but is NOT in custom-client's own resolved catalog — it must be
                # filtered out of custom-client's rollup.
                products=json.dumps(["widget_a", "auto_todo_riesgo"]),
                specific_needs=json.dumps(["speed", "precio_competitivo"]),
                service_issues=json.dumps([]),
            )
        )

        await sess.commit()

    from app.leads.router import router as leads_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(leads_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client

    await db_module.close_db()


async def test_dimension_rollup_filters_by_quintana_own_resolved_catalog(
    catalog_cutover_client,
):
    response = await catalog_cutover_client.get(
        "/api/v1/leads/lead-quintana-cutover/dimension-rollups",
        params={"client_id": "quintana-seguros"},
    )
    assert response.status_code == 200
    body = response.json()
    interests = {row["interest"] for row in body["detected_interests"]}
    assert "auto_todo_riesgo" in interests
    assert "hogar" in interests
    assert "precio_competitivo" in interests


async def test_dimension_rollup_excludes_other_clients_product_not_in_own_catalog(
    catalog_cutover_client,
):
    """custom-client's rollup must NOT include 'auto_todo_riesgo' — it is a
    valid id in the global PRODUCT_CATALOG (Quintana's) but is absent from
    custom-client's own resolved catalog. This is the literal per-client-not-
    global cutover proof (task 4.1)."""
    response = await catalog_cutover_client.get(
        "/api/v1/leads/lead-custom-cutover/dimension-rollups",
        params={"client_id": "custom-client"},
    )
    assert response.status_code == 200
    body = response.json()
    interests = {row["interest"] for row in body["detected_interests"]}
    assert "widget_a" in interests
    assert "speed" in interests
    assert "auto_todo_riesgo" not in interests, (
        "custom-client's rollup leaked a product id from the global "
        "PRODUCT_CATALOG that is not in its own resolved catalog"
    )
    assert "precio_competitivo" not in interests, (
        "custom-client's rollup leaked a need tag from the global NEED_TAGS "
        "that is not in its own resolved catalog"
    )
