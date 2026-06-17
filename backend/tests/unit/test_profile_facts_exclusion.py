"""Unit tests for profile facts exclusion — EXCLUDED_STRUCTURED_FIELDS.

TDD RED → GREEN → TRIANGULATE → REFACTOR

Covers (task 2.7):
- age field produces no profile fact (routed to corrections)
- zona field produces no profile fact
- car_make, car_model, car_year produce no profile facts
- current_insurance produces no profile fact
- name, phone, email produce no profile facts (contact fields)
- Non-excluded field (e.g. occupation) passes through normally
- Suppression audit logging (logger.info called with structured fields)

Acceptance criteria: profile-facts-exclusion spec scenarios.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
# Pure function tests — EXCLUDED_STRUCTURED_FIELDS set
# ===========================================================================


def test_excluded_structured_fields_contains_required_entries():
    """EXCLUDED_STRUCTURED_FIELDS must include all known structured lead fields.

    Acceptance: exclusion list is exhaustive at deploy time.
    """
    from app.analysis.universal.profile_facts import EXCLUDED_STRUCTURED_FIELDS

    required = {
        "age",
        "zona",
        "car_make",
        "car_model",
        "car_year",
        "current_insurance",
        "name",
        "phone",
        "email",
    }
    missing = required - EXCLUDED_STRUCTURED_FIELDS
    assert not missing, (
        f"EXCLUDED_STRUCTURED_FIELDS is missing required entries: {missing}"
    )


def test_excluded_structured_fields_is_a_set():
    """EXCLUDED_STRUCTURED_FIELDS must be a set for O(1) membership lookup."""
    from app.analysis.universal.profile_facts import EXCLUDED_STRUCTURED_FIELDS

    assert isinstance(EXCLUDED_STRUCTURED_FIELDS, (set, frozenset)), (
        f"Expected set/frozenset, got {type(EXCLUDED_STRUCTURED_FIELDS).__name__}"
    )


# ===========================================================================
# _filter_excluded_profile_facts — post-processing suppression
# ===========================================================================


def test_filter_suppresses_age_proxy_facts():
    """ProfileFactUpdate with category family_context and age evidence must be suppressed.

    Acceptance: age detected — routed to corrections, not profile facts.
    """
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _filter_excluded_profile_facts,
    )

    # age evidence detected under family_context — should be suppressed
    age_fact = ProfileFactUpdate(
        operation="add",
        category="family_context",
        fact="tiene 23 años",
        evidence="dijo que tiene 23 años",
        confidence="high",
        target_fact_id=None,
    )

    result, suppressed = _filter_excluded_profile_facts([age_fact], call_id="test-call-1")

    assert len(result) == 0, (
        "Age-proxy fact under family_context must be suppressed"
    )
    assert len(suppressed) == 1, (
        "Suppressed list must contain the discarded age fact"
    )


def test_filter_suppresses_zona_lifestyle_facts():
    """ProfileFactUpdate mentioning zona/location under lifestyle must be suppressed.

    Acceptance: zona detected — suppressed from profile facts.
    """
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _filter_excluded_profile_facts,
    )

    zona_fact = ProfileFactUpdate(
        operation="add",
        category="lifestyle",
        fact="vive en zona sur",
        evidence="mencionó que está en zona sur",
        confidence="medium",
        target_fact_id=None,
    )

    result, suppressed = _filter_excluded_profile_facts([zona_fact], call_id="test-call-2")

    assert len(result) == 0, (
        "Zona/location fact under lifestyle must be suppressed"
    )
    assert len(suppressed) == 1


def test_filter_passes_non_excluded_facts():
    """Non-excluded profile facts (occupation, decision_style, etc.) pass through.

    Acceptance: non-excluded field passes through normally.
    """
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _filter_excluded_profile_facts,
    )

    occupation_fact = ProfileFactUpdate(
        operation="add",
        category="occupation",
        fact="es gerente comercial",
        evidence="dijo que trabaja como gerente",
        confidence="high",
        target_fact_id=None,
    )
    personality_fact = ProfileFactUpdate(
        operation="add",
        category="personality_tone",
        fact="directo y formal",
        evidence="habla de forma directa",
        confidence="medium",
        target_fact_id=None,
    )

    result, suppressed = _filter_excluded_profile_facts(
        [occupation_fact, personality_fact], call_id="test-call-3"
    )

    assert len(result) == 2, (
        f"Non-excluded facts must pass through. Got {len(result)} instead of 2"
    )
    assert len(suppressed) == 0, (
        "No suppressions expected for non-excluded facts"
    )


def test_filter_suppresses_vehicle_facts():
    """Car-related profile facts must be suppressed (route to car corrections).

    Acceptance: car make/model detected — routed to corrections.
    """
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _filter_excluded_profile_facts,
    )

    vehicle_fact = ProfileFactUpdate(
        operation="add",
        category="lifestyle",
        fact="tiene un Toyota Corolla 2020",
        evidence="mencionó su Toyota Corolla",
        confidence="high",
        target_fact_id=None,
    )

    result, suppressed = _filter_excluded_profile_facts([vehicle_fact], call_id="test-call-4")

    assert len(result) == 0, "Vehicle/car fact must be suppressed"
    assert len(suppressed) == 1


def test_filter_suppresses_insurance_facts():
    """current_insurance profile fact must be suppressed.

    Acceptance: current_insurance routed to corrections, not profile facts.
    """
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _filter_excluded_profile_facts,
    )

    insurance_fact = ProfileFactUpdate(
        operation="add",
        category="provider_relationship",
        fact="tiene seguro en La Caja",
        evidence="dijo que su seguro actual es La Caja",
        confidence="high",
        target_fact_id=None,
    )

    result, suppressed = _filter_excluded_profile_facts([insurance_fact], call_id="test-call-5")

    assert len(result) == 0, "current_insurance fact must be suppressed"
    assert len(suppressed) == 1


def test_filter_suppresses_contact_field_facts():
    """name/phone/email facts must be suppressed (contact fields, not profile facts).

    Acceptance: contact field already set — suppress, do not overwrite.
    """
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _filter_excluded_profile_facts,
    )

    email_fact = ProfileFactUpdate(
        operation="add",
        category="communication_preference",
        fact="su email es test@example.com",
        evidence="dijo su email es test@example.com",
        confidence="high",
        target_fact_id=None,
    )

    result, suppressed = _filter_excluded_profile_facts([email_fact], call_id="test-call-6")

    assert len(result) == 0, "Email/contact fact must be suppressed"
    assert len(suppressed) == 1


# ===========================================================================
# Audit logging tests
# ===========================================================================


def test_suppression_logs_structured_audit_entry():
    """Suppressed facts must trigger logger.info with structured fields.

    Acceptance: suppression audit log written — field, reason, call_id logged.
    Verifies that logger.info is called at least once with a message that
    includes 'suppress' and the call_id value.
    """
    import logging
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _filter_excluded_profile_facts,
    )

    age_fact = ProfileFactUpdate(
        operation="add",
        category="family_context",
        fact="tiene 35 años",
        evidence="dijo que tiene 35 años",
        confidence="medium",
        target_fact_id=None,
    )

    log_messages: list[str] = []

    class _CapturingHandler(logging.Handler):
        def emit(self, record):
            log_messages.append(self.format(record))

    handler = _CapturingHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))

    import app.analysis.universal.profile_facts as pf_module
    target_logger = logging.getLogger(pf_module.__name__)
    original_level = target_logger.level
    target_logger.addHandler(handler)
    target_logger.setLevel(logging.DEBUG)

    try:
        result, suppressed = _filter_excluded_profile_facts(
            [age_fact], call_id="call-audit-001"
        )
    finally:
        target_logger.removeHandler(handler)
        target_logger.setLevel(original_level)

    assert len(suppressed) == 1, "Age fact must be suppressed"
    suppression_logs = [m for m in log_messages if "suppress" in m.lower()]
    assert len(suppression_logs) >= 1, (
        f"Expected at least one suppression log message. Got: {log_messages}"
    )
    # Verify call_id is included in the log message
    assert "call-audit-001" in suppression_logs[0], (
        f"Suppression log must include call_id 'call-audit-001'. Got: {suppression_logs[0]}"
    )


# ===========================================================================
# Integration: run_profile_facts_pipeline respects exclusion
# ===========================================================================


@pytest.mark.asyncio
async def test_pipeline_filters_excluded_facts_before_returning():
    """run_profile_facts_pipeline must apply exclusion filter on GPT output.

    If GPT returns an age-proxy fact, it must be filtered before the function returns.
    Non-excluded facts still pass through.

    Acceptance: age detected → not emitted as profile fact.
    """
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        ProfileFactsAxis,
        run_profile_facts_pipeline,
    )

    # GPT returns one excluded (age-proxy) and one non-excluded (occupation) update
    age_fact = ProfileFactUpdate(
        operation="add",
        category="family_context",
        fact="tiene 30 años",
        evidence="mencionó que tiene 30 años",
        confidence="high",
        target_fact_id=None,
    )
    occupation_fact = ProfileFactUpdate(
        operation="add",
        category="occupation",
        fact="trabaja en ventas",
        evidence="dijo que trabaja en ventas",
        confidence="high",
        target_fact_id=None,
    )

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = ProfileFactsAxis(
        updates=[age_fact, occupation_fact]
    )
    mock_response.choices[0].message.refusal = None
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    result = await run_profile_facts_pipeline(
        transcript="Lead dijo que tiene 30 años y trabaja en ventas.",
        client=mock_client,
        current_facts=[],
        call_id="pipeline-exclusion-test",
    )

    categories = {u.category.value for u in result.updates}
    assert "family_context" not in categories, (
        f"Age-proxy family_context fact must be filtered out. Got categories: {categories}"
    )
    assert "occupation" in categories, (
        f"Non-excluded occupation fact must pass through. Got categories: {categories}"
    )


# ===========================================================================
# Production-path wiring: _call_gpt_summarize must forward session_id as call_id
# so suppression audit logs are never call_id=None in production.
# ===========================================================================


@pytest.mark.asyncio
async def test_production_path_forwards_session_id_as_call_id():
    """_call_gpt_summarize must pass session_id to run_profile_facts_pipeline as call_id.

    The production summarizer wires session_id → call_id so suppression audit logs
    carry the real call ID. This test patches run_profile_facts_pipeline and asserts
    the call_id kwarg equals the session_id passed into _call_gpt_summarize.

    Acceptance: production-path suppression audit logs include the call ID.
    """
    from app.analysis.universal.profile_facts import ProfileFactsAxis
    import app.summarizer as summarizer_module

    captured: dict[str, object] = {}

    async def _fake_profile_pipeline(transcript, client, **kwargs):
        captured["call_id"] = kwargs.get("call_id")
        return ProfileFactsAxis(updates=[])

    # Stub all other pipelines/dimensions so only the wiring is exercised.
    async def _fake_interest_pipeline(*args, **kwargs):
        from app.analysis.universal.interest.interest_level import InterestLevelResult

        return {}, InterestLevelResult(
            general_score=0, level="very_low", reason="no interest", confidence="low"
        )

    async def _fake_misc_pipeline(*args, **kwargs):
        from app.analysis.universal.misc_notes import MiscNotesAxis

        return MiscNotesAxis()

    async def _fake_corrections_pipeline(*args, **kwargs):
        from app.analysis.universal.data_corrections import DataCorrectionsAxis

        return DataCorrectionsAxis()

    with (
        patch.object(
            summarizer_module, "run_profile_facts_pipeline", _fake_profile_pipeline
        ),
        patch.object(
            summarizer_module, "run_interest_pipeline", _fake_interest_pipeline
        ),
        patch.object(
            summarizer_module, "run_misc_notes_pipeline", _fake_misc_pipeline
        ),
        patch.object(
            summarizer_module,
            "run_data_corrections_pipeline",
            _fake_corrections_pipeline,
        ),
        patch.object(
            summarizer_module,
            "_get_openai_client",
            lambda: (AsyncMock(), "gpt-4o-mini"),
        ),
        patch.object(summarizer_module, "DIMENSION_MODULES", []),
    ):
        await summarizer_module._call_gpt_summarize(
            "Lead dijo que tiene 30 años.",
            current_profile_facts=[],
            has_lead=True,
            session_id="prod-session-xyz",
        )

    assert captured.get("call_id") == "prod-session-xyz", (
        "Production path must forward session_id as call_id to "
        f"run_profile_facts_pipeline. Got call_id={captured.get('call_id')!r}"
    )


@pytest.mark.asyncio
async def test_production_path_suppression_log_includes_call_id():
    """Suppression audit log through the production path carries the call ID, not None.

    Drives _call_gpt_summarize with a GPT response containing a suppressible
    age-proxy fact. Captures profile_facts logger output and asserts the
    suppression log line includes the session_id (proving call_id != None).

    Acceptance: production-path suppression audit logs include the call ID.
    """
    import logging

    from app.analysis.universal.profile_facts import (
        ProfileFactsAxis,
        ProfileFactUpdate,
    )
    import app.analysis.universal.profile_facts as pf_module
    import app.summarizer as summarizer_module

    age_fact = ProfileFactUpdate(
        operation="add",
        category="family_context",
        fact="tiene 30 años",
        evidence="dijo que tiene 30 años",
        confidence="high",
        target_fact_id=None,
    )

    # Real run_profile_facts_pipeline runs, but GPT (mocked) returns the age fact.
    mock_openai = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = ProfileFactsAxis(updates=[age_fact])
    mock_response.choices[0].message.refusal = None
    mock_openai.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    async def _fake_interest_pipeline(*args, **kwargs):
        from app.analysis.universal.interest.interest_level import InterestLevelResult

        return {}, InterestLevelResult(
            general_score=0, level="very_low", reason="no interest", confidence="low"
        )

    async def _fake_misc_pipeline(*args, **kwargs):
        from app.analysis.universal.misc_notes import MiscNotesAxis

        return MiscNotesAxis()

    async def _fake_corrections_pipeline(*args, **kwargs):
        from app.analysis.universal.data_corrections import DataCorrectionsAxis

        return DataCorrectionsAxis()

    log_messages: list[str] = []

    class _CapturingHandler(logging.Handler):
        def emit(self, record):
            log_messages.append(self.format(record))

    handler = _CapturingHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    target_logger = logging.getLogger(pf_module.__name__)
    original_level = target_logger.level
    target_logger.addHandler(handler)
    target_logger.setLevel(logging.DEBUG)

    try:
        with (
            patch.object(
                summarizer_module, "run_interest_pipeline", _fake_interest_pipeline
            ),
            patch.object(
                summarizer_module, "run_misc_notes_pipeline", _fake_misc_pipeline
            ),
            patch.object(
                summarizer_module,
                "run_data_corrections_pipeline",
                _fake_corrections_pipeline,
            ),
            patch.object(
                summarizer_module,
                "_get_openai_client",
                lambda: (mock_openai, "gpt-4o-mini"),
            ),
            patch.object(summarizer_module, "DIMENSION_MODULES", []),
        ):
            await summarizer_module._call_gpt_summarize(
                "Lead dijo que tiene 30 años.",
                current_profile_facts=[],
                has_lead=True,
                session_id="audit-session-123",
            )
    finally:
        target_logger.removeHandler(handler)
        target_logger.setLevel(original_level)

    suppression_logs = [m for m in log_messages if "suppress" in m.lower()]
    assert len(suppression_logs) >= 1, (
        f"Expected a suppression audit log. Got: {log_messages}"
    )
    assert "audit-session-123" in suppression_logs[0], (
        "Production-path suppression log must include the call_id. "
        f"Got: {suppression_logs[0]}"
    )
    assert "call_id=None" not in suppression_logs[0], (
        "Production path must not emit call_id=None. "
        f"Got: {suppression_logs[0]}"
    )
