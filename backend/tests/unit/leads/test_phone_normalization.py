"""Strict-TDD coverage for lead phone normalization at API ingress."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_create_lead_stores_canonical_phone_before_session_mutation():
    """The service normalizes before constructing or flushing a Lead."""
    from app.leads.service import create_lead

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    lead = await create_lead(
        session,
        client_id="tenant-a",
        name="Ana",
        phone="011 15 5555-0101",
    )

    assert lead.phone == "+5491155550101"
    session.add.assert_called_once_with(lead)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_lead_rejects_invalid_phone_without_session_writes():
    """Invalid input cannot construct, add, or flush a Lead."""
    from app.leads.service import create_lead
    from app.phones.normalization import PhoneNormalizationError

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    with pytest.raises(PhoneNormalizationError) as error:
        await create_lead(
            session,
            client_id="tenant-a",
            name="Ana",
            phone="011 5555-0101",
        )

    assert error.value.reason == "ambiguous_or_incomplete"
    assert "011" not in str(error.value)
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_new_lead_returns_safe_phone_422_before_custom_fields_or_commit():
    """The router translates only normalization failures and performs no writes."""
    from app.leads.router import CreateLeadRequest, create_new_lead
    from app.phones.normalization import PhoneNormalizationError

    session = AsyncMock()
    session.commit = AsyncMock()
    body = CreateLeadRequest(
        client_id="tenant-a",
        name="Ana",
        phone="011 5555-0101",
        custom_fields={"car_make": "Ford"},
    )

    with patch(
        "app.leads.router.create_lead",
        new=AsyncMock(side_effect=PhoneNormalizationError("ambiguous_or_incomplete")),
    ) as create, patch("app.leads.router.cf_service.upsert_many", new=AsyncMock()) as upsert:
        with pytest.raises(HTTPException) as error:
            await create_new_lead(body, client_id=None, session=session)

    assert error.value.status_code == 422
    assert error.value.detail == {
        "error": "invalid_phone",
        "reason": "ambiguous_or_incomplete",
    }
    assert "011" not in str(error.value.detail)
    create.assert_awaited_once()
    upsert.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_new_lead_requires_client_before_phone_validation():
    """The established client-id guard remains earlier than phone validation."""
    from app.leads.router import CreateLeadRequest, create_new_lead

    body = CreateLeadRequest(name="Ana", phone="011 5555-0101")
    with patch("app.leads.router.create_lead", new=AsyncMock()) as create:
        with pytest.raises(HTTPException) as error:
            await create_new_lead(body, client_id=None, session=AsyncMock())

    assert error.value.status_code == 422
    assert error.value.detail == {"error": "client_id is required"}
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_equivalent_spellings_store_the_same_canonical_value_in_isolated_db(db_session):
    """A rejected request has no persisted row, while accepted forms agree."""
    from sqlalchemy import select

    from app.leads.models import Lead
    from app.leads.service import create_lead
    from app.phones.normalization import PhoneNormalizationError

    domestic = await create_lead(
        db_session, client_id="tenant-a", name="Domestic", phone="011 15 5555-0101"
    )
    canonical = await create_lead(
        db_session, client_id="tenant-a", name="Canonical", phone="+5491155550101"
    )
    with pytest.raises(PhoneNormalizationError):
        await create_lead(
            db_session, client_id="tenant-a", name="Rejected", phone="011 5555-0101"
        )

    stored = list((await db_session.execute(select(Lead).order_by(Lead.name))).scalars())
    assert [lead.phone for lead in stored] == ["+5491155550101", "+5491155550101"]
    assert domestic.phone == canonical.phone
