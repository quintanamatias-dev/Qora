"""skill-packages (P4-D5) — Task 4: API router tests.

Covers package/skill summary reads, resolved agent-skills read, create,
content-write (new revision), revisions list, rollback, soft-deactivate,
tenant isolation, Qora-package superadmin gating, and cache invalidation.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


_CLIENT_ID = "acme"
_OTHER_CLIENT_ID = "other-co"
_AGENT_SLUG = "sales-agent"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def skills_app(tmp_path: Path):
    """Isolated FastAPI app with the skills router + a fresh SQLite DB.

    Seeds two clients (acme, other-co), each with one agent, plus a Qora
    package with one general skill, so tenant-isolation and collision tests
    have real rows to probe.
    """
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/skills_router_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations
    await init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import create_client
        from app.tenants.models import SkillPackage, Skill
        from app.skills.service import create_skill_revision

        await create_client(session, id=_CLIENT_ID, name="Acme", agent_name="Acme Agent", voice_id="v1")
        await create_client(session, id=_OTHER_CLIENT_ID, name="Other Co", agent_name="Other Agent", voice_id="v1")
        await session.commit()

        from app.tenants.models import Agent
        from sqlalchemy import select

        agent = (
            await session.execute(select(Agent).where(Agent.client_id == _CLIENT_ID))
        ).scalars().first()
        agent.slug = _AGENT_SLUG
        other_agent = (
            await session.execute(select(Agent).where(Agent.client_id == _OTHER_CLIENT_ID))
        ).scalars().first()
        await session.flush()

        qora_package = SkillPackage(owner_type="qora", client_id=None, name="qora")
        session.add(qora_package)
        await session.flush()
        qora_skill = Skill(package_id=qora_package.id, slug="general-knowledge", section="general")
        session.add(qora_skill)
        await session.flush()
        await create_skill_revision(
            session,
            skill=qora_skill,
            content_md="qora content",
            filler_text="filler",
            trigger_hint="hint",
            description="qora desc",
            source="import",
            created_by="system",
        )
        await session.commit()

        acme_agent_id = agent.id
        other_agent_id = other_agent.id

    from app.skills.router import router as skills_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(skills_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        client.acme_agent_id = acme_agent_id  # type: ignore[attr-defined]
        client.other_agent_id = other_agent_id  # type: ignore[attr-defined]
        yield client

    await db_module.close_db()


def _as_tenant(client: AsyncClient, client_ids: set[str]):
    """Override require_api_key so this client's requests act as a
    non-superadmin tenant-scoped caller restricted to client_ids."""
    from app.core.auth import require_api_key, CallerIdentity

    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[require_api_key] = lambda: CallerIdentity(
        api_key_hash="t", role="client", client_ids=frozenset(client_ids)
    )


# ---------------------------------------------------------------------------
# GET /clients/{client_id}/skill-packages
# ---------------------------------------------------------------------------


async def test_get_skill_packages_returns_client_and_qora_summary(skills_app: AsyncClient):
    response = await skills_app.get(f"/api/v1/clients/{_CLIENT_ID}/skill-packages")
    assert response.status_code == 200
    data = response.json()
    assert data["qora_package"]["skills"][0]["slug"] == "general-knowledge"
    assert data["qora_package"]["skills"][0]["active_revision_number"] == 1
    assert data["client_package"] is None  # acme has no skills of its own yet


async def test_client_cannot_access_another_clients_package(skills_app: AsyncClient):
    _as_tenant(skills_app, {_OTHER_CLIENT_ID})
    response = await skills_app.get(f"/api/v1/clients/{_CLIENT_ID}/skill-packages")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /clients/{client_id}/skills — create in client package
# ---------------------------------------------------------------------------


_VALID_SKILL = {
    "slug": "pricing",
    "section": "general",
    "description": "Pricing info",
    "trigger_hint": "when asked about price",
    "filler_text": "Let me check that.",
    "content_md": "# Pricing\n\nOur pricing is...",
}


async def test_create_client_skill_package_and_skill(skills_app: AsyncClient):
    response = await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == "pricing"
    assert data["active_revision_number"] == 1
    assert data["content_md"] == _VALID_SKILL["content_md"]

    packages = (await skills_app.get(f"/api/v1/clients/{_CLIENT_ID}/skill-packages")).json()
    assert packages["client_package"]["skills"][0]["slug"] == "pricing"


async def test_create_skill_rejects_path_separator_in_slug(skills_app: AsyncClient):
    payload = {**_VALID_SKILL, "slug": "../etc/passwd"}
    response = await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=payload)
    assert response.status_code == 422


async def test_create_skill_requires_agent_id_when_section_is_agent(skills_app: AsyncClient):
    payload = {**_VALID_SKILL, "section": "agent"}
    response = await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=payload)
    assert response.status_code == 422


async def test_create_skill_duplicate_slug_same_section_is_conflict(skills_app: AsyncClient):
    await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    response = await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    assert response.status_code == 409


async def test_create_skill_requires_superadmin(skills_app: AsyncClient):
    _as_tenant(skills_app, {_CLIENT_ID})
    response = await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# PUT /clients/{client_id}/skills/{skill_id} — content write (new revision)
# ---------------------------------------------------------------------------


async def test_put_skill_content_creates_new_revision_and_activates_it(skills_app: AsyncClient):
    created = (
        await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    ).json()
    skill_id = created["skill_id"]

    response = await skills_app.put(
        f"/api/v1/clients/{_CLIENT_ID}/skills/{skill_id}",
        json={
            "content_md": "updated content",
            "filler_text": "new filler",
            "trigger_hint": "new hint",
            "description": "new desc",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["active_revision_number"] == 2
    assert data["content_md"] == "updated content"


async def test_put_skill_content_never_mutates_an_existing_revision(skills_app: AsyncClient):
    created = (
        await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    ).json()
    skill_id = created["skill_id"]

    await skills_app.put(
        f"/api/v1/clients/{_CLIENT_ID}/skills/{skill_id}",
        json={
            "content_md": "updated content",
            "filler_text": "new filler",
            "trigger_hint": "new hint",
            "description": "new desc",
        },
    )

    revisions = (
        await skills_app.get(f"/api/v1/clients/{_CLIENT_ID}/skills/{skill_id}/revisions")
    ).json()
    rev1 = next(r for r in revisions if r["revision_number"] == 1)
    assert rev1["content_md"] == _VALID_SKILL["content_md"]


async def test_put_skill_content_invalidates_cache_for_voice_context(skills_app: AsyncClient):
    from app.skills.service import get_default_skills_cache, resolve_agent_skills

    created = (
        await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    ).json()
    skill_id = created["skill_id"]

    from app.core import database as db_module
    from app.tenants.models import Agent

    resolved_before = None
    async with db_module.async_session_factory() as session:
        agent = await session.get(Agent, skills_app.acme_agent_id)
        resolved_before = await resolve_agent_skills(session, agent)
    assert resolved_before.content_by_slug["pricing"] == _VALID_SKILL["content_md"]

    async with db_module.async_session_factory() as session:
        agent = await session.get(Agent, skills_app.acme_agent_id)
        cache = get_default_skills_cache()
        first = await cache.get(session, agent)
        assert first.content_by_slug["pricing"] == _VALID_SKILL["content_md"]

    await skills_app.put(
        f"/api/v1/clients/{_CLIENT_ID}/skills/{skill_id}",
        json={
            "content_md": "updated content",
            "filler_text": "new filler",
            "trigger_hint": "new hint",
            "description": "new desc",
        },
    )

    async with db_module.async_session_factory() as session:
        agent = await session.get(Agent, skills_app.acme_agent_id)
        cache = get_default_skills_cache()
        after = await cache.get(session, agent)
        assert after.content_by_slug["pricing"] == "updated content"


async def test_put_skill_content_requires_superadmin(skills_app: AsyncClient):
    created = (
        await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    ).json()
    skill_id = created["skill_id"]

    _as_tenant(skills_app, {_CLIENT_ID})
    response = await skills_app.put(
        f"/api/v1/clients/{_CLIENT_ID}/skills/{skill_id}",
        json={
            "content_md": "updated content",
            "filler_text": "new filler",
            "trigger_hint": "new hint",
            "description": "new desc",
        },
    )
    assert response.status_code == 403


async def test_client_cannot_write_another_clients_skill(skills_app: AsyncClient):
    created = (
        await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    ).json()
    skill_id = created["skill_id"]

    response = await skills_app.put(
        f"/api/v1/clients/{_OTHER_CLIENT_ID}/skills/{skill_id}",
        json={
            "content_md": "hijacked",
            "filler_text": "f",
            "trigger_hint": "h",
            "description": "d",
        },
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET revisions / POST rollback
# ---------------------------------------------------------------------------


async def test_get_revisions_lists_all_in_order(skills_app: AsyncClient):
    created = (
        await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    ).json()
    skill_id = created["skill_id"]
    await skills_app.put(
        f"/api/v1/clients/{_CLIENT_ID}/skills/{skill_id}",
        json={"content_md": "v2", "filler_text": "f", "trigger_hint": "h", "description": "d"},
    )

    response = await skills_app.get(f"/api/v1/clients/{_CLIENT_ID}/skills/{skill_id}/revisions")
    assert response.status_code == 200
    numbers = [r["revision_number"] for r in response.json()]
    assert numbers == [2, 1]


async def test_post_rollback_creates_new_revision_not_resurrection(skills_app: AsyncClient):
    created = (
        await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    ).json()
    skill_id = created["skill_id"]
    await skills_app.put(
        f"/api/v1/clients/{_CLIENT_ID}/skills/{skill_id}",
        json={"content_md": "v2", "filler_text": "f", "trigger_hint": "h", "description": "d"},
    )

    response = await skills_app.post(
        f"/api/v1/clients/{_CLIENT_ID}/skills/{skill_id}/rollback",
        json={"revision_number": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["revision_number"] == 3
    assert data["source"] == "rollback"
    assert data["content_md"] == _VALID_SKILL["content_md"]


async def test_post_rollback_requires_target_in_same_skill(skills_app: AsyncClient):
    created = (
        await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    ).json()
    skill_id = created["skill_id"]

    response = await skills_app.post(
        f"/api/v1/clients/{_CLIENT_ID}/skills/{skill_id}/rollback",
        json={"revision_number": 999},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE (soft deactivate)
# ---------------------------------------------------------------------------


async def test_delete_skill_soft_deactivates(skills_app: AsyncClient):
    created = (
        await skills_app.post(f"/api/v1/clients/{_CLIENT_ID}/skills", json=_VALID_SKILL)
    ).json()
    skill_id = created["skill_id"]

    response = await skills_app.delete(f"/api/v1/clients/{_CLIENT_ID}/skills/{skill_id}")
    assert response.status_code == 200
    assert response.json()["active_revision_number"] is None

    packages = (await skills_app.get(f"/api/v1/clients/{_CLIENT_ID}/skill-packages")).json()
    assert packages["client_package"]["skills"][0]["active_revision_number"] is None


# ---------------------------------------------------------------------------
# GET /clients/{client_id}/agents/{agent_id}/skills — resolved
# ---------------------------------------------------------------------------


async def test_get_resolved_agent_skills_reports_origin_and_revision(skills_app: AsyncClient):
    response = await skills_app.get(
        f"/api/v1/clients/{_CLIENT_ID}/agents/{skills_app.acme_agent_id}/skills"
    )
    assert response.status_code == 200
    data = response.json()
    assert data[0]["slug"] == "general-knowledge"
    assert data[0]["origin"] == "qora"
    assert data[0]["active_revision_number"] == 1


async def test_get_resolved_agent_skills_tenant_isolated(skills_app: AsyncClient):
    response = await skills_app.get(
        f"/api/v1/clients/{_CLIENT_ID}/agents/{skills_app.other_agent_id}/skills"
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Qora package: superadmin-only writes, any-caller reads
# ---------------------------------------------------------------------------


async def test_qora_package_write_requires_superadmin(skills_app: AsyncClient):
    packages = (await skills_app.get(f"/api/v1/clients/{_CLIENT_ID}/skill-packages")).json()
    qora_skill_id = packages["qora_package"]["skills"][0]["skill_id"]

    _as_tenant(skills_app, {_CLIENT_ID})
    response = await skills_app.put(
        f"/api/v1/clients/{_CLIENT_ID}/skills/{qora_skill_id}",
        json={"content_md": "hijacked", "filler_text": "f", "trigger_hint": "h", "description": "d"},
    )
    assert response.status_code == 403


async def test_qora_package_read_allowed_for_any_authenticated_client(skills_app: AsyncClient):
    _as_tenant(skills_app, {_CLIENT_ID})
    response = await skills_app.get(f"/api/v1/clients/{_CLIENT_ID}/skill-packages")
    assert response.status_code == 200
    assert response.json()["qora_package"]["skills"][0]["slug"] == "general-knowledge"


async def test_qora_package_write_by_superadmin_invalidates_all_agents(skills_app: AsyncClient):
    packages = (await skills_app.get(f"/api/v1/clients/{_CLIENT_ID}/skill-packages")).json()
    qora_skill_id = packages["qora_package"]["skills"][0]["skill_id"]

    from app.core import database as db_module
    from app.tenants.models import Agent
    from app.skills.service import get_default_skills_cache

    async with db_module.async_session_factory() as session:
        agent = await session.get(Agent, skills_app.acme_agent_id)
        cache = get_default_skills_cache()
        await cache.get(session, agent)

    response = await skills_app.put(
        f"/api/v1/clients/{_CLIENT_ID}/skills/{qora_skill_id}",
        json={"content_md": "updated qora", "filler_text": "f", "trigger_hint": "h", "description": "d"},
    )
    assert response.status_code == 200

    async with db_module.async_session_factory() as session:
        agent = await session.get(Agent, skills_app.acme_agent_id)
        cache = get_default_skills_cache()
        fresh = await cache.get(session, agent)
        assert fresh.content_by_slug["general-knowledge"] == "updated qora"
