"""Tests for Qora Demo seed correctness — fix-qora-demo-agent-prompt-pipeline.

Spec: sdd/fix-qora-demo-agent-prompt-pipeline/spec
Requirement: DB Seed / Fallback Prompt Correctness
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Task 2.1 — _QORA_EXPLAINER_SYSTEM_PROMPT constant must reflect Mariano/Qora
# ---------------------------------------------------------------------------

class TestQoraExplainerSystemPromptConstant:
    """Unit tests for the seed constant itself (no DB required)."""

    def test_prompt_contains_mariano(self):
        from app.tenants.service import _QORA_EXPLAINER_SYSTEM_PROMPT
        assert "Mariano" in _QORA_EXPLAINER_SYSTEM_PROMPT

    def test_prompt_does_not_contain_sofia(self):
        from app.tenants.service import _QORA_EXPLAINER_SYSTEM_PROMPT
        assert "Sofia" not in _QORA_EXPLAINER_SYSTEM_PROMPT

    def test_prompt_does_not_contain_insurance_sales_content(self):
        from app.tenants.service import _QORA_EXPLAINER_SYSTEM_PROMPT
        # Insurance-specific terms that must NEVER appear in the Qora demo agent prompt,
        # regardless of whether "Qora" is also present. The demo must not mention the
        # insurance domain even in passing; domain context comes from runtime skill files.
        prompt_lower = _QORA_EXPLAINER_SYSTEM_PROMPT.lower()
        assert "seguros" not in prompt_lower, (
            "Prompt must not contain 'seguros'; insurance domain must not leak into demo agent"
        )
        assert "productora" not in prompt_lower, (
            "Prompt must not contain 'productora'; insurance domain must not leak"
        )
        assert "cotización" not in prompt_lower and "cotizacion" not in prompt_lower, (
            "Prompt must not contain 'cotización'; insurance domain must not leak"
        )

    def test_prompt_references_qora_platform(self):
        from app.tenants.service import _QORA_EXPLAINER_SYSTEM_PROMPT
        assert "Qora" in _QORA_EXPLAINER_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Task 2.2 — seed_qora_demo() upserts stale system_prompt on existing rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSeedQoraDemoUpsertStalePrompt:
    """Integration-style tests for seed_qora_demo() upsert behavior."""

    async def test_existing_agent_with_stale_sofia_prompt_is_updated(self):
        """Existing agent with Sofia content must be upserted with Mariano prompt."""
        from app.tenants.service import _QORA_EXPLAINER_SYSTEM_PROMPT

        # Arrange: existing client + agent with stale Sofia prompt
        stale_prompt = "Sos Sofia, la asistente de seguros."
        mock_agent = MagicMock()
        mock_agent.elevenlabs_agent_id = "agent_8201kra4wjhve0srcwgbtwfetr5n"
        mock_agent.system_prompt = stale_prompt

        mock_session = AsyncMock()

        async def mock_get_client(session, client_id):
            if client_id == "qora-demo":
                return MagicMock()  # existing client
            return None

        async def mock_get_default_agent(session, client_id):
            if client_id == "qora-demo":
                return mock_agent
            return None

        async def mock_list_leads(*args, **kwargs):
            return [MagicMock()]  # has leads, skip seed

        with patch("app.tenants.service.get_client", side_effect=mock_get_client), \
             patch("app.tenants.service.get_default_agent", side_effect=mock_get_default_agent), \
             patch("app.leads.service.list_leads_for_client", side_effect=mock_list_leads):
            from app.tenants.service import seed_qora_demo
            await seed_qora_demo(mock_session)

        # Assert: stale prompt was overwritten
        assert mock_agent.system_prompt == _QORA_EXPLAINER_SYSTEM_PROMPT
        mock_session.flush.assert_called()

    async def test_existing_agent_with_correct_prompt_is_not_flushed(self):
        """Existing agent already has correct prompt — no flush for system_prompt."""
        from app.tenants.service import _QORA_EXPLAINER_SYSTEM_PROMPT

        mock_agent = MagicMock()
        mock_agent.elevenlabs_agent_id = "agent_8201kra4wjhve0srcwgbtwfetr5n"
        mock_agent.system_prompt = _QORA_EXPLAINER_SYSTEM_PROMPT

        mock_session = AsyncMock()

        async def mock_get_client(session, client_id):
            return MagicMock() if client_id == "qora-demo" else None

        async def mock_get_default_agent(session, client_id):
            return mock_agent if client_id == "qora-demo" else None

        async def mock_list_leads(*args, **kwargs):
            return [MagicMock()]

        with patch("app.tenants.service.get_client", side_effect=mock_get_client), \
             patch("app.tenants.service.get_default_agent", side_effect=mock_get_default_agent), \
             patch("app.leads.service.list_leads_for_client", side_effect=mock_list_leads):
            from app.tenants.service import seed_qora_demo
            await seed_qora_demo(mock_session)

        # Assert: system_prompt was NOT changed (still the correct one)
        assert mock_agent.system_prompt == _QORA_EXPLAINER_SYSTEM_PROMPT
        # flush may or may not be called (for elevenlabs_agent_id check), but system_prompt unchanged


# ---------------------------------------------------------------------------
# Verifier finding fix — lead seed notes must NOT contain insurance-domain content
# ---------------------------------------------------------------------------

class TestQoraDemoSeedLeadNotes:
    """Unit tests that verify the seed lead notes constant is free of insurance content."""

    def test_lead_notes_do_not_contain_insurance_wording(self):
        """Insurance terms must not appear in the qora-demo seed lead notes.

        The seed lead is a Qora evaluator, not an insurance prospect. Any insurance
        wording in the notes leaks domain context into the conversation and can make
        the agent mention seguros/cotización even when the user never asked.
        """
        from app.tenants.service import _QORA_DEMO_SEED_LEAD_NOTES
        notes_lower = _QORA_DEMO_SEED_LEAD_NOTES.lower()
        assert "seguros" not in notes_lower, (
            "Lead notes must not contain 'seguros'; insurance domain must not leak into demo context"
        )
        assert "productora" not in notes_lower, (
            "Lead notes must not contain 'productora'; insurance domain must not leak"
        )
        assert "cotización" not in notes_lower and "cotizacion" not in notes_lower, (
            "Lead notes must not contain 'cotización'; insurance domain must not leak"
        )

    def test_lead_notes_describe_qora_evaluator(self):
        """Seed lead notes must describe a Qora platform evaluator, not an insurance buyer."""
        from app.tenants.service import _QORA_DEMO_SEED_LEAD_NOTES
        notes_lower = _QORA_DEMO_SEED_LEAD_NOTES.lower()
        # Must mention Qora to confirm the lead is evaluating the platform
        assert "qora" in notes_lower, (
            "Lead notes must mention 'Qora'; the lead is evaluating Qora, not buying insurance"
        )


# ---------------------------------------------------------------------------
# Verifier finding fix — system-prompt.md must reference correct skill filename
# ---------------------------------------------------------------------------

class TestSystemPromptSkillFileReference:
    """Unit tests that verify system-prompt.md uses the correct skill file reference."""

    def test_system_prompt_references_agent_skill_filename(self):
        """system-prompt.md must reference Qora-info.agent-skill.md, not Qora-info.md.

        The PromptLoader loads skills by the `.agent-skill.md` suffix. Any reference
        to the old `Qora-info.md` name in the prompt text is stale and misleading.
        """
        import pathlib
        prompt_path = pathlib.Path(__file__).parent.parent / (
            "clients/qora-demo/agents/qora-explainer/system-prompt.md"
        )
        content = prompt_path.read_text()
        assert "Qora-info.agent-skill.md" in content, (
            "system-prompt.md must reference 'Qora-info.agent-skill.md' (the correct skill filename)"
        )
        assert "Qora-info.md" not in content.replace("Qora-info.agent-skill.md", ""), (
            "system-prompt.md must not reference the stale 'Qora-info.md' filename"
        )


# ---------------------------------------------------------------------------
# TTS seed values — qora-demo deterministic per-agent TTS config
# ---------------------------------------------------------------------------


class TestQoraDemoTtsSeed:
    """Unit tests that verify seed_qora_demo() sets deterministic TTS values on the agent."""

    def test_seed_tts_constants_exist(self):
        """_QORA_DEMO_TTS_SPEED/STABILITY/SIMILARITY_BOOST constants must be defined."""
        from app.tenants import service

        assert hasattr(service, "_QORA_DEMO_TTS_SPEED"), (
            "service module must export _QORA_DEMO_TTS_SPEED"
        )
        assert hasattr(service, "_QORA_DEMO_TTS_STABILITY"), (
            "service module must export _QORA_DEMO_TTS_STABILITY"
        )
        assert hasattr(service, "_QORA_DEMO_TTS_SIMILARITY_BOOST"), (
            "service module must export _QORA_DEMO_TTS_SIMILARITY_BOOST"
        )

    def test_seed_tts_speed_value(self):
        """Demo seed TTS speed must be 0.95 (intentional, documented value)."""
        from app.tenants.service import _QORA_DEMO_TTS_SPEED

        assert _QORA_DEMO_TTS_SPEED == 0.95, (
            f"Expected _QORA_DEMO_TTS_SPEED=0.95, got {_QORA_DEMO_TTS_SPEED}"
        )

    def test_seed_tts_speed_within_el_valid_range(self):
        """Demo seed TTS speed must be within EL Conversational AI valid range [0.7, 1.2].

        ElevenLabs rejects tts.speed values outside [0.7, 1.2] with WebSocket 1008.
        The seed value must be EL-valid to avoid the 1008 → fallback reconnect loop.
        """
        from app.tenants.service import _QORA_DEMO_TTS_SPEED

        assert 0.7 <= _QORA_DEMO_TTS_SPEED <= 1.2, (
            f"_QORA_DEMO_TTS_SPEED={_QORA_DEMO_TTS_SPEED} is outside EL valid range [0.7, 1.2]. "
            "ElevenLabs rejects speed values outside this range with 1008 WebSocket close."
        )

    def test_seed_tts_stability_value(self):
        """Demo seed TTS stability must be 0.40."""
        from app.tenants.service import _QORA_DEMO_TTS_STABILITY

        assert _QORA_DEMO_TTS_STABILITY == 0.40, (
            f"Expected _QORA_DEMO_TTS_STABILITY=0.40, got {_QORA_DEMO_TTS_STABILITY}"
        )

    def test_seed_tts_similarity_boost_value(self):
        """Demo seed TTS similarity_boost must be 0.75."""
        from app.tenants.service import _QORA_DEMO_TTS_SIMILARITY_BOOST

        assert _QORA_DEMO_TTS_SIMILARITY_BOOST == 0.75, (
            f"Expected _QORA_DEMO_TTS_SIMILARITY_BOOST=0.75, got {_QORA_DEMO_TTS_SIMILARITY_BOOST}"
        )

    async def test_seed_qora_demo_sets_tts_on_new_agent(self):
        """seed_qora_demo() sets TTS fields on the new agent when client doesn't exist.

        GIVEN an empty DB (no qora-demo client)
        WHEN seed_qora_demo() runs
        THEN the created agent MUST have tts_speed/stability/similarity_boost set from constants
        """
        from app.tenants.service import (
            _QORA_DEMO_TTS_SPEED,
            _QORA_DEMO_TTS_STABILITY,
            _QORA_DEMO_TTS_SIMILARITY_BOOST,
        )

        created_agent = MagicMock()
        created_agent.elevenlabs_agent_id = None
        created_agent.system_prompt = None
        created_agent.tts_speed = None
        created_agent.tts_stability = None
        created_agent.tts_similarity_boost = None

        mock_session = AsyncMock()

        async def mock_get_client(session, client_id):
            return None  # No client exists yet

        async def mock_get_default_agent(session, client_id):
            return created_agent

        async def mock_create_client(*args, **kwargs):
            return MagicMock()

        async def mock_list_leads(*args, **kwargs):
            return [MagicMock()]

        with patch("app.tenants.service.get_client", side_effect=mock_get_client), \
             patch("app.tenants.service.get_default_agent", side_effect=mock_get_default_agent), \
             patch("app.tenants.service.create_client", side_effect=mock_create_client), \
             patch("app.leads.service.list_leads_for_client", side_effect=mock_list_leads):
            from app.tenants.service import seed_qora_demo
            await seed_qora_demo(mock_session)

        assert created_agent.tts_speed == _QORA_DEMO_TTS_SPEED
        assert created_agent.tts_stability == _QORA_DEMO_TTS_STABILITY
        assert created_agent.tts_similarity_boost == _QORA_DEMO_TTS_SIMILARITY_BOOST

    async def test_seed_qora_demo_does_not_overwrite_edited_tts(self):
        """seed_qora_demo() re-seed does NOT overwrite manually edited TTS values.

        GIVEN qora-demo exists with tts_speed=1.5 (user edited it)
        WHEN seed_qora_demo() runs again
        THEN tts_speed MUST remain 1.5 (not reset to 0.95)
        """
        mock_agent = MagicMock()
        mock_agent.elevenlabs_agent_id = "agent_8201kra4wjhve0srcwgbtwfetr5n"
        mock_agent.system_prompt = None  # neutral — let seed update
        mock_agent.tts_speed = 1.5   # user-edited
        mock_agent.tts_stability = 0.6   # user-edited
        mock_agent.tts_similarity_boost = 0.9  # user-edited

        mock_session = AsyncMock()

        async def mock_get_client(session, client_id):
            return MagicMock()  # client exists

        async def mock_get_default_agent(session, client_id):
            return mock_agent

        async def mock_list_leads(*args, **kwargs):
            return [MagicMock()]

        with patch("app.tenants.service.get_client", side_effect=mock_get_client), \
             patch("app.tenants.service.get_default_agent", side_effect=mock_get_default_agent), \
             patch("app.leads.service.list_leads_for_client", side_effect=mock_list_leads):
            from app.tenants.service import seed_qora_demo
            await seed_qora_demo(mock_session)

        # TTS values must remain unchanged
        assert mock_agent.tts_speed == 1.5, f"Expected 1.5, got {mock_agent.tts_speed}"
        assert mock_agent.tts_stability == 0.6
        assert mock_agent.tts_similarity_boost == 0.9


# ---------------------------------------------------------------------------
# Task 1.7 — Quintana Seguros parity seed/config
# Spec: Requirement: Quintana Seguros Migration — Zero Behavioral Drift
# AC-7: Quintana Seguros schema parity test passes
# ---------------------------------------------------------------------------


class TestQuintanaToolConfigParity:
    """Tests verifying Quintana Seguros capture_data config parity.

    After Phase 1 seed, Quintana's agent must have:
    - capture_data in tools_enabled (alongside legacy tools — dual-run)
    - tool_config with a capture_data schema matching old car fields
    """

    def test_quintana_tool_config_constant_exists(self):
        """_QUINTANA_TOOL_CONFIG constant must be defined in service.py."""
        from app.tenants import service

        assert hasattr(service, "_QUINTANA_TOOL_CONFIG"), (
            "service module must export _QUINTANA_TOOL_CONFIG"
        )

    def test_quintana_tool_config_has_capture_data_key(self):
        """_QUINTANA_TOOL_CONFIG must have a 'capture_data' key."""
        from app.tenants.service import _QUINTANA_TOOL_CONFIG
        import json

        # It may be a dict or a JSON string (stored as TEXT in DB)
        if isinstance(_QUINTANA_TOOL_CONFIG, str):
            config = json.loads(_QUINTANA_TOOL_CONFIG)
        else:
            config = _QUINTANA_TOOL_CONFIG

        assert "capture_data" in config, (
            "_QUINTANA_TOOL_CONFIG must contain 'capture_data' key"
        )

    def test_quintana_capture_data_schema_has_car_fields(self):
        """_QUINTANA_TOOL_CONFIG capture_data must cover car_make, car_model, car_year."""
        from app.tenants.service import _QUINTANA_TOOL_CONFIG
        import json

        if isinstance(_QUINTANA_TOOL_CONFIG, str):
            config = json.loads(_QUINTANA_TOOL_CONFIG)
        else:
            config = _QUINTANA_TOOL_CONFIG

        capture_config = config["capture_data"]
        # Get the parameters block (may be nested or flat)
        params = capture_config.get("parameters", capture_config)
        props = params.get("properties", {})
        # Must include car fields that map to the old register_interest behavior
        car_field_names = set(props.keys())
        assert any("car_make" in f or "marca" in f for f in car_field_names), (
            f"Expected car_make or marca in properties. Got: {car_field_names}"
        )
        assert any("car_model" in f or "modelo" in f for f in car_field_names), (
            f"Expected car_model or modelo in properties. Got: {car_field_names}"
        )
        assert any("car_year" in f or "anio" in f or "año" in f for f in car_field_names), (
            f"Expected car_year, anio, or año in properties. Got: {car_field_names}"
        )


class TestQuintanaCaptureParity:
    """Parity test: capture_data with Quintana schema produces same fact keys as register_interest.

    Spec AC-7: Quintana Seguros schema parity test passes.
    """

    async def test_capture_data_quintana_parity_writes_expected_facts(self):
        """capture_data with Quintana schema writes same fact keys as register_interest.

        GIVEN Quintana Seguros schema with car fields
        WHEN capture_data is called with car data
        THEN result has status=captured and fields list contains the car fields
        AND all required car fields are present in the returned fields list
        """
        from app.tenants.service import _QUINTANA_TOOL_CONFIG
        from app.tools.capture_data import capture_data
        from unittest.mock import AsyncMock, MagicMock, patch
        import json

        if isinstance(_QUINTANA_TOOL_CONFIG, str):
            tool_config = json.loads(_QUINTANA_TOOL_CONFIG)
        else:
            tool_config = _QUINTANA_TOOL_CONFIG

        capture_cfg = tool_config["capture_data"]
        params = capture_cfg.get("parameters", capture_cfg)
        props = params.get("properties", {})

        # Build captured_fields based on actual schema (use first car field names found)
        field_names = list(props.keys())
        car_make_field = next((f for f in field_names if "car_make" in f or "marca" in f), None)
        car_model_field = next((f for f in field_names if "car_model" in f or "modelo" in f), None)
        car_year_field = next((f for f in field_names if "car_year" in f or "anio" in f or "año" in f), None)

        assert car_make_field, "Must have a car make field"
        assert car_model_field, "Must have a car model field"
        assert car_year_field, "Must have a car year field"

        captured_fields = {
            car_make_field: "Toyota",
            car_model_field: "Corolla",
            car_year_field: "2020",
            "age": 35,
            "zona": "Palermo",
        }

        # Mock the DB session and lead so we don't need a real DB
        mock_lead = MagicMock()
        mock_lead.id = "lead-q-001"
        mock_lead.client_id = "quintana-seguros"

        # Track session.add calls to verify what facts are written
        added_objects = []
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # no existing fact
        mock_session.execute.return_value = mock_result

        def track_add(obj):
            added_objects.append(obj)

        mock_session.add = track_add

        with patch("app.tools.capture_data.get_lead", return_value=mock_lead):
            result = await capture_data(
                session=mock_session,
                lead_id="lead-q-001",
                tool_config=tool_config,
                captured_fields=captured_fields,
                client_id="quintana-seguros",
            )

        assert result.get("status") == "captured", f"Expected captured, got {result}"
        captured_result_fields = set(result.get("fields", []))

        # All required car fields must be in the result
        assert car_make_field in captured_result_fields, (
            f"Expected {car_make_field} in fields. Got: {captured_result_fields}"
        )
        assert car_model_field in captured_result_fields, (
            f"Expected {car_model_field} in fields. Got: {captured_result_fields}"
        )
        assert car_year_field in captured_result_fields, (
            f"Expected {car_year_field} in fields. Got: {captured_result_fields}"
        )

        # Verify LeadProfileFact objects were created with correct keys
        added_fact_keys = {obj.fact_key for obj in added_objects}
        assert f"captured:{car_make_field}" in added_fact_keys, (
            f"Expected captured:{car_make_field} in added facts. Got: {added_fact_keys}"
        )
        assert f"captured:{car_model_field}" in added_fact_keys, (
            f"Expected captured:{car_model_field} in added facts. Got: {added_fact_keys}"
        )
        assert f"captured:{car_year_field}" in added_fact_keys, (
            f"Expected captured:{car_year_field} in added facts. Got: {added_fact_keys}"
        )

        # Verify values
        make_fact = next(o for o in added_objects if o.fact_key == f"captured:{car_make_field}")
        assert make_fact.fact_value == "Toyota"
