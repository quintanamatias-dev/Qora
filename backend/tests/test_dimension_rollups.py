"""Dimension Rollups endpoint — unit and integration tests (Strict TDD RED phase).

Tests cover:
- GET /api/v1/leads/{lead_id}/dimension-rollups with multiple call analyses
- Single-call lead returns count=1 correctly
- Lead with no call analyses returns empty arrays + HTTP 200
- Rollup uses call_analyses, NOT CallSession.extracted_facts
- _build_dimension_rollups() pure function behavior
- Strength thresholds: count>=3 → high, count==2 → medium, count==1 → low
- Interest filtering: only PRODUCT_CATALOG / NEED_TAGS items appear
- All arrays sorted by count descending
- SECURITY: cross-tenant access returns 404 (same as missing lead — oracle-safe)
- SECURITY: mismatched CallAnalysis.client_id rows are excluded even if lead_id matches

Spec: openspec/changes/cubora-accumulated-dimension-rankings/specs/lead-dimension-rollups/spec.md
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lead_id() -> str:
    return str(uuid.uuid4())


def _session_id() -> str:
    return str(uuid.uuid4())


def _analysis_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _make_lead(db_session, client_id: str = "test-client") -> str:
    """Insert a minimal Lead and return its ID."""
    from app.leads.models import Lead

    lead_id = _lead_id()
    lead = Lead(
        id=lead_id,
        client_id=client_id,
        name="Rollup Test Lead",
        phone="+5491100000010",
        status="new",
        call_count=0,
        do_not_call=False,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db_session.add(lead)
    await db_session.flush()
    return lead_id


async def _make_call_session(
    db_session, lead_id: str, client_id: str = "test-client"
) -> str:
    """Insert a minimal CallSession and return its ID."""
    from app.calls.models import CallSession

    sid = _session_id()
    cs = CallSession(
        id=sid,
        client_id=client_id,
        lead_id=lead_id,
        status="completed",
        started_at=_utcnow(),
        created_at=_utcnow(),
    )
    db_session.add(cs)
    await db_session.flush()
    return sid


async def _make_call_analysis(
    db_session,
    session_id: str,
    lead_id: str,
    *,
    client_id: str = "test-client",
    products: list[str] | None = None,
    service_issues: list[dict] | None = None,
    primary_objection_category: str | None = None,
    primary_pain_category: str | None = None,
) -> str:
    """Insert a CallAnalysis row and return its ID."""
    from app.calls.models import CallAnalysis

    aid = _analysis_id()
    analysis = CallAnalysis(
        id=aid,
        session_id=session_id,
        lead_id=lead_id,
        client_id=client_id,
        products=json.dumps(products or []),
        service_issues=json.dumps(service_issues or []),
        primary_objection_category=primary_objection_category,
        primary_pain_category=primary_pain_category,
        analysis_status="ok",
        analyzed_at=_utcnow(),
    )
    db_session.add(analysis)
    await db_session.flush()
    return aid


# ---------------------------------------------------------------------------
# Unit tests — _build_dimension_rollups (pure logic, no HTTP layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_dimension_rollups_multi_call_interests(db_session):
    """Multi-call lead: interests ranked by count descending."""
    from app.leads.router import _build_dimension_rollups

    lead_id = await _make_lead(db_session)

    # Call 1 + Call 2: auto_todo_riesgo appears 2x; hogar appears 1x
    for _ in range(2):
        sid = await _make_call_session(db_session, lead_id)
        await _make_call_analysis(db_session, sid, lead_id, products=["auto_todo_riesgo"])
    sid3 = await _make_call_session(db_session, lead_id)
    await _make_call_analysis(db_session, sid3, lead_id, products=["hogar"])
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")

    interests = result["detected_interests"]
    assert len(interests) >= 2
    # First row must be auto_todo_riesgo with count 2
    first = next(i for i in interests if i["interest"] == "auto_todo_riesgo")
    second = next(i for i in interests if i["interest"] == "hogar")
    assert first["count"] == 2
    assert second["count"] == 1
    # Sorted descending: auto_todo_riesgo before hogar
    assert interests.index(first) < interests.index(second)


@pytest.mark.asyncio
async def test_build_dimension_rollups_single_call(db_session):
    """Single-call lead: each interest appears with count=1, no errors."""
    from app.leads.router import _build_dimension_rollups

    lead_id = await _make_lead(db_session)
    sid = await _make_call_session(db_session, lead_id)
    await _make_call_analysis(db_session, sid, lead_id, products=["moto"])
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")

    interests = result["detected_interests"]
    assert any(i["interest"] == "moto" and i["count"] == 1 for i in interests)


@pytest.mark.asyncio
async def test_build_dimension_rollups_no_analyses_returns_empty(db_session):
    """Lead with no call analyses: all arrays are empty, no error."""
    from app.leads.router import _build_dimension_rollups

    lead_id = await _make_lead(db_session)
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")

    assert result["detected_interests"] == []
    assert result["service_issues"] == []
    assert result["objections"] == []
    assert result["pain_points"] == []


@pytest.mark.asyncio
async def test_build_dimension_rollups_service_issues_ranked(db_session):
    """Service issues ranked by count; strength derived from thresholds."""
    from app.leads.router import _build_dimension_rollups

    lead_id = await _make_lead(db_session)

    # poor_attention: 2 calls → strength = medium
    for _ in range(2):
        sid = await _make_call_session(db_session, lead_id)
        await _make_call_analysis(
            db_session, sid, lead_id,
            service_issues=[{"category": "poor_attention", "description": "x",
                             "source": "current_provider", "severity": "medium",
                             "evidence": "y", "confidence": "high"}],
        )
    # delay: 1 call → strength = low
    sid3 = await _make_call_session(db_session, lead_id)
    await _make_call_analysis(
        db_session, sid3, lead_id,
        service_issues=[{"category": "delay", "description": "x",
                         "source": "current_provider", "severity": "low",
                         "evidence": "y", "confidence": "medium"}],
    )
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")
    issues = result["service_issues"]

    attn = next(i for i in issues if i["issue"] == "poor_attention")
    delay = next(i for i in issues if i["issue"] == "delay")

    assert attn["count"] == 2
    assert attn["strength"] == "medium"
    assert delay["count"] == 1
    assert delay["strength"] == "low"
    # poor_attention must rank first
    assert issues.index(attn) < issues.index(delay)


@pytest.mark.asyncio
async def test_build_dimension_rollups_service_issues_high_threshold(db_session):
    """Service issue with 3+ mentions gets strength = high."""
    from app.leads.router import _build_dimension_rollups

    lead_id = await _make_lead(db_session)
    for _ in range(3):
        sid = await _make_call_session(db_session, lead_id)
        await _make_call_analysis(
            db_session, sid, lead_id,
            service_issues=[{"category": "billing_issue", "description": "x",
                             "source": "current_provider", "severity": "high",
                             "evidence": "y", "confidence": "high"}],
        )
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")
    issues = result["service_issues"]
    billing = next(i for i in issues if i["issue"] == "billing_issue")
    assert billing["count"] == 3
    assert billing["strength"] == "high"


@pytest.mark.asyncio
async def test_build_dimension_rollups_interest_filtered_by_allowlist(db_session):
    """Interests not in PRODUCT_CATALOG or NEED_TAGS must be excluded."""
    from app.leads.router import _build_dimension_rollups

    lead_id = await _make_lead(db_session)
    sid = await _make_call_session(db_session, lead_id)
    # "comprar" is not in PRODUCT_CATALOG or NEED_TAGS — must be filtered out
    await _make_call_analysis(
        db_session, sid, lead_id,
        products=["auto_todo_riesgo", "comprar"],
    )
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")
    interests = result["detected_interests"]
    codes = [i["interest"] for i in interests]

    assert "comprar" not in codes
    assert "auto_todo_riesgo" in codes


@pytest.mark.asyncio
async def test_build_dimension_rollups_interest_category_product(db_session):
    """Interests from PRODUCT_CATALOG have category='product'."""
    from app.leads.router import _build_dimension_rollups

    lead_id = await _make_lead(db_session)
    sid = await _make_call_session(db_session, lead_id)
    await _make_call_analysis(db_session, sid, lead_id, products=["vida"])
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")
    vida = next(i for i in result["detected_interests"] if i["interest"] == "vida")
    assert vida["category"] == "product"


@pytest.mark.asyncio
async def test_build_dimension_rollups_interest_category_need(db_session):
    """Need tags from NEED_TAGS have category='need'."""
    from app.leads.router import _build_dimension_rollups

    lead_id = await _make_lead(db_session)
    sid = await _make_call_session(db_session, lead_id)
    # specific_needs contains need tag items
    from app.calls.models import CallAnalysis
    aid = _analysis_id()
    analysis = CallAnalysis(
        id=aid,
        session_id=sid,
        lead_id=lead_id,
        client_id="test-client",
        products=json.dumps([]),
        # Use specific_needs for need tags
        specific_needs=json.dumps(["precio_competitivo"]),
        analysis_status="ok",
        analyzed_at=_utcnow(),
    )
    db_session.add(analysis)
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")
    need_items = [i for i in result["detected_interests"] if i["interest"] == "precio_competitivo"]
    assert len(need_items) == 1
    assert need_items[0]["category"] == "need"


@pytest.mark.asyncio
async def test_build_dimension_rollups_objections_ranked(db_session):
    """Objections from primary_objection_category ranked by count."""
    from app.leads.router import _build_dimension_rollups

    lead_id = await _make_lead(db_session)
    for _ in range(2):
        sid = await _make_call_session(db_session, lead_id)
        await _make_call_analysis(
            db_session, sid, lead_id, primary_objection_category="price"
        )
    sid3 = await _make_call_session(db_session, lead_id)
    await _make_call_analysis(
        db_session, sid3, lead_id, primary_objection_category="current_provider"
    )
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")
    objections = result["objections"]
    price_obj = next(o for o in objections if o["category"] == "price")
    assert price_obj["count"] == 2
    assert objections[0]["category"] == "price"


@pytest.mark.asyncio
async def test_build_dimension_rollups_does_not_use_extracted_facts(db_session):
    """Rollup reads call_analyses, NOT CallSession.extracted_facts.

    We populate CallSession.extracted_facts with fake data and leave
    call_analyses empty — result must be empty arrays, not ghost data.
    """
    from app.leads.router import _build_dimension_rollups
    from app.calls.models import CallSession

    lead_id = await _make_lead(db_session)
    sid = _session_id()
    cs = CallSession(
        id=sid,
        client_id="test-client",
        lead_id=lead_id,
        status="completed",
        started_at=_utcnow(),
        created_at=_utcnow(),
        # Ghost data that must NOT appear in rollups
        extracted_facts={"products": ["auto_todo_riesgo"], "primary_objection_category": "price"},
    )
    db_session.add(cs)
    await db_session.commit()

    # No CallAnalysis rows inserted — rollup must be empty
    result = await _build_dimension_rollups(db_session, lead_id, "test-client")
    assert result["detected_interests"] == []
    assert result["objections"] == []


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_client(test_settings, db_engine):
    """HTTPX async client with isolated test DB + FastAPI app."""
    from app.main import app
    import app.core.database as db_module

    original_factory = db_module.async_session_factory

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    db_module.async_session_factory = original_factory


@pytest.mark.asyncio
async def test_endpoint_dimension_rollups_multi_call(db_session):
    """GET /api/v1/leads/{lead_id}/dimension-rollups returns 200 + arrays for multi-call lead."""
    from app.leads.router import get_dimension_rollups

    lead_id = await _make_lead(db_session)
    for _ in range(2):
        sid = await _make_call_session(db_session, lead_id)
        await _make_call_analysis(db_session, sid, lead_id, products=["auto_todo_riesgo"])
    await db_session.commit()

    result = await get_dimension_rollups(lead_id=lead_id, client_id="test-client", session=db_session)

    assert "detected_interests" in result
    assert "service_issues" in result
    assert "objections" in result
    assert "pain_points" in result
    atr = next(i for i in result["detected_interests"] if i["interest"] == "auto_todo_riesgo")
    assert atr["count"] == 2


@pytest.mark.asyncio
async def test_endpoint_dimension_rollups_no_analyses_returns_200(db_session):
    """GET dimension-rollups for lead with no analyses → 200 + all empty arrays."""
    from app.leads.router import get_dimension_rollups

    lead_id = await _make_lead(db_session)
    await db_session.commit()

    result = await get_dimension_rollups(lead_id=lead_id, client_id="test-client", session=db_session)

    assert result["detected_interests"] == []
    assert result["service_issues"] == []
    assert result["objections"] == []
    assert result["pain_points"] == []


@pytest.mark.asyncio
async def test_endpoint_dimension_rollups_404_unknown_lead(db_session):
    """GET dimension-rollups for unknown lead_id → 404."""
    from app.leads.router import get_dimension_rollups
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_dimension_rollups(lead_id="nonexistent-lead", client_id="test-client", session=db_session)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# SQL aggregation path tests (post-optimization lock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_objections_sql_aggregation_multi_category(db_session):
    """Objections use SQL GROUP BY: two categories ranked correctly by count.

    Validates that the SQL aggregation path (not Python Counter) produces
    correctly ordered results with accurate counts.
    """
    from app.leads.router import _build_dimension_rollups

    lead_id = await _make_lead(db_session)

    # "price" appears 3×, "trust" appears 1× — SQL GROUP BY must rank price first
    for _ in range(3):
        sid = await _make_call_session(db_session, lead_id)
        await _make_call_analysis(db_session, sid, lead_id,
                                  primary_objection_category="price")
    sid4 = await _make_call_session(db_session, lead_id)
    await _make_call_analysis(db_session, sid4, lead_id,
                              primary_objection_category="trust")
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")
    objections = result["objections"]

    price = next(o for o in objections if o["category"] == "price")
    trust = next(o for o in objections if o["category"] == "trust")

    assert price["count"] == 3
    assert trust["count"] == 1
    # SQL ORDER BY count DESC must place "price" first
    assert objections.index(price) < objections.index(trust)


@pytest.mark.asyncio
async def test_pain_points_sql_aggregation_null_excluded(db_session):
    """Pain points SQL GROUP BY excludes NULL primary_pain_category rows.

    Rows with NULL primary_pain_category must not appear in pain_points.
    This validates the WHERE primary_pain_category IS NOT NULL clause.
    """
    from app.leads.router import _build_dimension_rollups

    lead_id = await _make_lead(db_session)

    # One row with a real pain category, one with None
    sid1 = await _make_call_session(db_session, lead_id)
    await _make_call_analysis(db_session, sid1, lead_id,
                              primary_pain_category="financial_stress")
    sid2 = await _make_call_session(db_session, lead_id)
    await _make_call_analysis(db_session, sid2, lead_id,
                              primary_pain_category=None)
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")
    pain_points = result["pain_points"]

    categories = [p["category"] for p in pain_points]
    assert "financial_stress" in categories
    assert None not in categories
    assert len(pain_points) == 1  # only the non-NULL row


@pytest.mark.asyncio
async def test_json_dimensions_only_required_columns_fetched(db_session):
    """JSON dimension query returns correct data even with unpopulated columns.

    Verifies that selecting only (products, specific_needs, service_issues)
    does not regress correctness when other columns (summary, profile_facts,
    commitment_signals, etc.) are not loaded. The data integrity test is a
    functional proxy — we cannot assert which columns SQLAlchemy selected
    without brittle introspection, but we can confirm no data is lost.
    """
    from app.leads.router import _build_dimension_rollups
    from app.calls.models import CallAnalysis

    lead_id = await _make_lead(db_session)
    sid = await _make_call_session(db_session, lead_id)

    # Row with products, specific_needs, and service_issues all populated
    aid = _analysis_id()
    analysis = CallAnalysis(
        id=aid,
        session_id=sid,
        lead_id=lead_id,
        client_id="test-client",
        products=json.dumps(["auto_todo_riesgo", "vida"]),
        specific_needs=json.dumps(["precio_competitivo"]),
        service_issues=json.dumps([{
            "category": "poor_attention",
            "description": "x",
            "source": "provider",
            "severity": "high",
            "evidence": "y",
            "confidence": "high",
        }]),
        # Intentionally leave summary, profile_facts, etc. at defaults
        analysis_status="ok",
        analyzed_at=_utcnow(),
    )
    db_session.add(analysis)
    await db_session.commit()

    result = await _build_dimension_rollups(db_session, lead_id, "test-client")

    interest_codes = [i["interest"] for i in result["detected_interests"]]
    assert "auto_todo_riesgo" in interest_codes
    assert "vida" in interest_codes
    assert "precio_competitivo" in interest_codes

    issue_cats = [i["issue"] for i in result["service_issues"]]
    assert "poor_attention" in issue_cats


# ---------------------------------------------------------------------------
# Security tests — cross-tenant / IDOR prevention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_dimension_rollups_wrong_client_returns_404(db_session):
    """GET dimension-rollups with a client_id that does not own the lead → 404.

    Regression guard: an attacker who knows a lead_id from tenant A must not
    retrieve its rollup data by querying with tenant B's client_id.
    The endpoint verifies lead.client_id == requested client_id and returns
    404 (oracle-safe — identical response to unknown lead, preventing lead
    existence enumeration by foreign tenants).
    """
    from app.leads.router import get_dimension_rollups
    from fastapi import HTTPException

    # Lead belongs to "client-alpha"
    lead_id = await _make_lead(db_session, client_id="client-alpha")
    await db_session.commit()

    # Attacker queries with "client-beta" — must get 404, not 200 or 403
    with pytest.raises(HTTPException) as exc_info:
        await get_dimension_rollups(
            lead_id=lead_id,
            client_id="client-beta",
            session=db_session,
        )

    assert exc_info.value.status_code == 404
    # Detail must be generic (same as missing lead — no "client" hint)
    assert "not found" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_build_dimension_rollups_excludes_mismatched_client_analyses(db_session):
    """_build_dimension_rollups excludes CallAnalysis rows whose client_id differs.

    Regression guard: even if CallAnalysis rows share a lead_id (e.g. due to a
    data anomaly or future migration), rows whose client_id does not match the
    requested tenant must be silently excluded from all rollup arrays.

    Setup:
      - Lead belongs to "client-alpha"
      - CallAnalysis row A: lead_id matches, client_id = "client-alpha" → included
      - CallAnalysis row B: lead_id matches, client_id = "client-beta"  → excluded

    Expected: only the data from row A appears in rollups.
    """
    from app.leads.router import _build_dimension_rollups
    from app.calls.models import CallAnalysis

    lead_id = await _make_lead(db_session, client_id="client-alpha")

    # Row belonging to the correct tenant — should appear in results
    sid_alpha = await _make_call_session(db_session, lead_id, client_id="client-alpha")
    await _make_call_analysis(
        db_session, sid_alpha, lead_id,
        client_id="client-alpha",
        products=["auto_todo_riesgo"],
        primary_objection_category="price",
    )

    # Row with a foreign client_id attached to the same lead — must be excluded
    # Simulates a data anomaly or cross-tenant write. Insert directly to bypass
    # normal service-layer constraints.
    sid_beta = await _make_call_session(db_session, lead_id, client_id="client-beta")
    foreign_analysis = CallAnalysis(
        id=_analysis_id(),
        session_id=sid_beta,
        lead_id=lead_id,
        client_id="client-beta",  # foreign tenant
        products=json.dumps(["vida"]),         # would inflate interests if leaked
        specific_needs=json.dumps([]),
        service_issues=json.dumps([]),
        primary_objection_category="trust",    # would inflate objections if leaked
        analysis_status="ok",
        analyzed_at=_utcnow(),
    )
    db_session.add(foreign_analysis)
    await db_session.commit()

    # Query as "client-alpha" — must only see its own analysis row
    result = await _build_dimension_rollups(db_session, lead_id, "client-alpha")

    interest_codes = [i["interest"] for i in result["detected_interests"]]
    objection_cats = [o["category"] for o in result["objections"]]

    # client-alpha's product must appear
    assert "auto_todo_riesgo" in interest_codes
    # client-beta's product must NOT appear
    assert "vida" not in interest_codes

    # client-alpha's objection must appear
    assert "price" in objection_cats
    # client-beta's objection must NOT appear
    assert "trust" not in objection_cats
