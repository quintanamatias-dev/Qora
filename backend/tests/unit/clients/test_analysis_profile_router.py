"""Phase 2 (analysis-profiles) — Tasks 2.2/2.3: analysis-profile API on the
clients router.

Covers:
  GET  /clients/{client_id}/analysis-profile
  PUT  /clients/{client_id}/analysis-profile
  GET  /clients/{client_id}/analysis-profile/revisions
  POST /clients/{client_id}/analysis-profile/rollback
  POST /clients/{client_id}/analysis-profile/apply-template
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr


@pytest_asyncio.fixture
async def analysis_profile_app(tmp_path: Path):
    """Isolated FastAPI app with the clients router + a seeded quintana
    client (insurance profile — seed_quintana applies the insurance template
    directly on revision 1, Gap A, matching migration 0023's production
    seed)."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/analysis_profile_router_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations

    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import seed_quintana

        await seed_quintana(session)
        await session.commit()

    from app.clients.router import router as clients_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(clients_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# GET /clients/{client_id}/analysis-profile
# ---------------------------------------------------------------------------


async def test_get_profile_returns_active_revision(analysis_profile_app):
    from app.analysis.universal.interest.catalog import NEED_TAGS, PRODUCT_CATALOG

    response = await analysis_profile_app.get(
        "/api/v1/clients/quintana-seguros/analysis-profile"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["client_id"] == "quintana-seguros"
    assert body["revision_number"] == 1
    assert body["vertical"] == "insurance"
    assert {p["id"] for p in body["products"]} == set(PRODUCT_CATALOG)
    assert {n["id"] for n in body["need_tags"]} == set(NEED_TAGS)


async def test_get_profile_404_for_unknown_client(analysis_profile_app):
    response = await analysis_profile_app.get(
        "/api/v1/clients/does-not-exist/analysis-profile"
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PUT /clients/{client_id}/analysis-profile
# ---------------------------------------------------------------------------


async def test_put_profile_rejects_duplicate_product_id(analysis_profile_app):
    response = await analysis_profile_app.put(
        "/api/v1/clients/quintana-seguros/analysis-profile",
        json={
            "vertical": "insurance",
            "products": [
                {"id": "hogar", "label_es": "Hogar", "label_en": "Home"},
                {"id": "hogar", "label_es": "Hogar 2", "label_en": "Home 2"},
            ],
            "need_tags": [],
        },
    )
    assert response.status_code == 422


async def test_put_profile_rejects_duplicate_need_tag_id(analysis_profile_app):
    response = await analysis_profile_app.put(
        "/api/v1/clients/quintana-seguros/analysis-profile",
        json={
            "vertical": "insurance",
            "products": [],
            "need_tags": [
                {"id": "rapidez", "label_es": "Rapidez", "label_en": "Speed"},
                {"id": "rapidez", "label_es": "Rapidez 2", "label_en": "Speed 2"},
            ],
        },
    )
    assert response.status_code == 422


async def test_put_profile_rejects_empty_label(analysis_profile_app):
    response = await analysis_profile_app.put(
        "/api/v1/clients/quintana-seguros/analysis-profile",
        json={
            "vertical": "insurance",
            "products": [{"id": "hogar", "label_es": "", "label_en": "Home"}],
            "need_tags": [],
        },
    )
    assert response.status_code == 422


async def test_put_profile_creates_new_revision_and_returns_config(analysis_profile_app):
    response = await analysis_profile_app.put(
        "/api/v1/clients/quintana-seguros/analysis-profile",
        json={
            "vertical": "insurance",
            "products": [{"id": "hogar", "label_es": "Hogar", "label_en": "Home"}],
            "need_tags": [{"id": "rapidez", "label_es": "Rapidez", "label_en": "Speed"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["revision_number"] == 2
    assert body["vertical"] == "insurance"
    assert [p["id"] for p in body["products"]] == ["hogar"]
    assert [n["id"] for n in body["need_tags"]] == ["rapidez"]

    get_response = await analysis_profile_app.get(
        "/api/v1/clients/quintana-seguros/analysis-profile"
    )
    assert get_response.json()["id"] == body["id"]


# ---------------------------------------------------------------------------
# GET /clients/{client_id}/analysis-profile/revisions
# ---------------------------------------------------------------------------


async def test_get_revisions_lists_all_in_order(analysis_profile_app):
    await analysis_profile_app.put(
        "/api/v1/clients/quintana-seguros/analysis-profile",
        json={"vertical": "generic", "products": [], "need_tags": []},
    )

    response = await analysis_profile_app.get(
        "/api/v1/clients/quintana-seguros/analysis-profile/revisions"
    )
    assert response.status_code == 200
    revisions = response.json()
    assert [r["revision_number"] for r in revisions] == [2, 1]


# ---------------------------------------------------------------------------
# POST /clients/{client_id}/analysis-profile/rollback
# ---------------------------------------------------------------------------


async def test_post_rollback_requires_target_in_same_client(analysis_profile_app):
    response = await analysis_profile_app.post(
        "/api/v1/clients/quintana-seguros/analysis-profile/rollback",
        json={"target_revision_id": "not-a-real-revision-id"},
    )
    assert response.status_code == 404


async def test_post_rollback_creates_new_revision(analysis_profile_app):
    first = await analysis_profile_app.get(
        "/api/v1/clients/quintana-seguros/analysis-profile"
    )
    revision_1_id = first.json()["id"]

    await analysis_profile_app.put(
        "/api/v1/clients/quintana-seguros/analysis-profile",
        json={"vertical": "generic", "products": [], "need_tags": []},
    )

    response = await analysis_profile_app.post(
        "/api/v1/clients/quintana-seguros/analysis-profile/rollback",
        json={"target_revision_id": revision_1_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["revision_number"] == 3
    assert body["id"] != revision_1_id


# ---------------------------------------------------------------------------
# POST /clients/{client_id}/analysis-profile/apply-template
# ---------------------------------------------------------------------------


async def test_post_apply_template_requires_known_vertical(analysis_profile_app):
    response = await analysis_profile_app.post(
        "/api/v1/clients/quintana-seguros/analysis-profile/apply-template",
        json={"vertical": "not-a-real-vertical"},
    )
    assert response.status_code == 422


async def test_post_apply_template_insurance_matches_catalog(analysis_profile_app):
    from app.analysis.universal.interest.catalog import NEED_TAGS, PRODUCT_CATALOG

    response = await analysis_profile_app.post(
        "/api/v1/clients/quintana-seguros/analysis-profile/apply-template",
        json={"vertical": "insurance"},
    )
    assert response.status_code == 200
    body = response.json()
    assert {p["id"] for p in body["products"]} == set(PRODUCT_CATALOG)
    assert {n["id"] for n in body["need_tags"]} == set(NEED_TAGS)
