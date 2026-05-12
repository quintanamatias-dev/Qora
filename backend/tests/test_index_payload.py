"""Tests for index.html buildInitPayload correctness.

Covers two change sets:
- fix-qora-demo-agent-prompt-pipeline: no agent.prompt or model override
- unify-qora-agent-runtime-config (Slice 2): no hardcoded TTS literals; dynamic TTS from agent API

These tests parse the static HTML and verify that the JS payload logic
does NOT include agent.prompt overrides or invalid model strings,
and that TTS values come from per-agent API data, not hardcoded literals.
They test the SOURCE of the payload construction, not a live connection.
"""

import re
from pathlib import Path


INDEX_HTML_PATH = Path(__file__).parent.parent / "app" / "static" / "index.html"


def read_index_html() -> str:
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


class TestIndexHtmlPayloadNoInvalidOverrides:
    """Verify index.html does not contain prohibited ElevenLabs override patterns."""

    def test_no_agent_prompt_key_in_payload(self):
        """buildInitPayload must NOT include agent.prompt override."""
        content = read_index_html()
        # The old pattern: { agent: { prompt: { llm: ... } } }
        assert "agent: { prompt:" not in content, \
            "index.html still contains agent.prompt override — remove agentOverride block"

    def test_no_gpt_5_4_model_string(self):
        """buildInitPayload must NOT reference invalid gpt-5.4 model."""
        content = read_index_html()
        assert "gpt-5.4" not in content, \
            "index.html still references invalid gpt-5.4 model string"

    def test_no_skip_agent_override_parameter(self):
        """skipAgentOverride parameter should be removed (dead code after agent override removal)."""
        content = read_index_html()
        assert "skipAgentOverride" not in content, \
            "index.html still has skipAgentOverride parameter — dead code after agent override removal"

    def test_tts_override_still_present(self):
        """TTS speed override (working, safe) must remain in place."""
        content = read_index_html()
        # Per design: TTS override works when accepted, fails gracefully via existing reconnect
        assert "tts" in content and "speed" in content, \
            "TTS speed override was incorrectly removed from index.html"

    def test_dynamic_variables_still_present(self):
        """dynamic_variables block must remain — it routes lead context to the backend."""
        content = read_index_html()
        assert "dynamic_variables" in content, \
            "dynamic_variables block was incorrectly removed from index.html"


class TestIndexHtmlNoDynamicTtsFromAgentApi:
    """Verify index.html TTS override uses per-agent values, not hardcoded literals.

    Spec: sdd/unify-qora-agent-runtime-config/spec
    Requirement: Browser fetches backend-generated EL override payload
    Scenario: No hardcoded TTS values in index.html
    """

    def test_no_hardcoded_tts_speed_literal(self):
        """buildInitPayload must NOT contain hardcoded speed: 1.2.

        TTS speed must come from the agent API response (selectedAgent.tts_speed).
        """
        content = read_index_html()
        assert "speed: 1.2" not in content, (
            "index.html still has hardcoded TTS speed: 1.2. "
            "Must use per-agent value from API (e.g. selectedAgent.tts_speed)."
        )

    def test_no_hardcoded_tts_stability_literal(self):
        """buildInitPayload must NOT contain hardcoded stability: 0.40 or 0.4.

        Triangulation: different hardcoded literal than speed test.
        """
        content = read_index_html()
        # Match both "0.40" and "0.4" as stability literals inside a tts object
        assert re.search(r"stability:\s*0\.40?[,\s}]", content) is None, (
            "index.html still has hardcoded TTS stability literal. "
            "Must use per-agent value from API (e.g. selectedAgent.tts_stability)."
        )

    def test_no_hardcoded_tts_similarity_boost_literal(self):
        """buildInitPayload must NOT contain hardcoded similarity_boost: 1.0.

        Triangulation: different field than speed/stability.
        """
        content = read_index_html()
        assert "similarity_boost: 1.0" not in content, (
            "index.html still has hardcoded TTS similarity_boost: 1.0. "
            "Must use per-agent value from API (e.g. selectedAgent.tts_similarity_boost)."
        )

    def test_tts_override_uses_agent_tts_speed_field(self):
        """buildInitPayload must read speed from selected agent's tts_speed field.

        The browser stores the selected agent's TTS values from the agents API
        and builds the EL override payload using those values.
        """
        content = read_index_html()
        assert "tts_speed" in content, (
            "index.html does not reference selectedAgent.tts_speed. "
            "Browser must build EL override from agent API TTS fields."
        )

    def test_tts_override_uses_agent_tts_stability_field(self):
        """buildInitPayload must read stability from selected agent's tts_stability field.

        Triangulation: different field than tts_speed test.
        """
        content = read_index_html()
        assert "tts_stability" in content, (
            "index.html does not reference tts_stability. "
            "Browser must use agent API field for stability."
        )

    def test_tts_override_uses_agent_tts_similarity_boost_field(self):
        """buildInitPayload must read similarity_boost from agent's tts_similarity_boost field.

        Triangulation: all 3 TTS fields must be covered.
        """
        content = read_index_html()
        assert "tts_similarity_boost" in content, (
            "index.html does not reference tts_similarity_boost. "
            "Browser must use agent API field for similarity_boost."
        )

    def test_1008_fallback_reconnect_still_present(self):
        """1008 fallback: browser must still retry without TTS override on EL rejection.

        Spec: Requirement: 1008 fallback remains safe if EL rejects TTS override
        The reconnect mechanism must be preserved even though TTS values are now dynamic.
        """
        content = read_index_html()
        assert "1008" in content, (
            "index.html removed the 1008 fallback reconnect logic. "
            "Must preserve retry-without-override behavior per spec."
        )

    def test_logging_reflects_dynamic_tts_not_hardcoded_speed(self):
        """console.log for TTS must NOT reference the old hardcoded '1.2' speed.

        The log message was: console.log('[tts] Sending speed override: 1.2')
        Must be removed or updated to reflect actual dynamic value.
        """
        content = read_index_html()
        assert "Sending speed override: 1.2" not in content, (
            "index.html still logs hardcoded speed 1.2. "
            "Update log to reflect actual dynamic TTS values."
        )

    def test_tts_log_uses_el_payload_key_names(self):
        """TTS console.log must log EL payload keys (speed, stability, similarity_boost).

        The log must not only log the DB key names (tts_speed, tts_stability, …)
        because that makes console verification confusing — the EL payload uses
        'speed', not 'tts_speed'. Verifies the log block includes the EL key 'speed:'.
        """
        content = read_index_html()
        assert "conversation_config_override.tts" in content, (
            "index.html TTS log must reference 'conversation_config_override.tts' "
            "so console output clearly maps to the EL payload structure."
        )


class TestIndexHtmlNoFallbackTtsLiterals:
    """Verify that loadAgentForClient does NOT fall back to hardcoded TTS literals.

    When the agent API returns null for TTS fields, the browser must NOT substitute
    hardcoded literals (0.95, 0.4, 0.75). Instead it should omit the TTS override
    entirely so ElevenLabs uses its own defaults.

    Spec requirement: If agent API lacks values, do not send TTS override or use
    server-provided values only.
    """

    def test_no_nullish_coalescing_to_hardcoded_tts_speed(self):
        """loadAgentForClient must NOT assign `?? 0.95` as TTS speed fallback.

        The pattern `tts_speed ?? 0.95` stores a hardcoded literal that gets sent
        to ElevenLabs even when the agent API returned null — violating the spec.
        """
        content = read_index_html()
        # Detect the specific pattern: `tts_speed  ?? <literal>` (any spacing)
        assert not re.search(r"tts_speed\s*\?\?\s*0\.\d+", content), (
            "index.html uses nullish-coalescing fallback for tts_speed "
            "(e.g. `tts_speed ?? 0.95`). Remove hardcoded fallback; "
            "when agent TTS is null, skip the TTS override entirely."
        )

    def test_no_nullish_coalescing_to_hardcoded_tts_stability(self):
        """loadAgentForClient must NOT assign `?? 0.4` as TTS stability fallback.

        Triangulation: different field and literal than the speed test.
        """
        content = read_index_html()
        assert not re.search(r"tts_stability\s*\?\?\s*0\.\d+", content), (
            "index.html uses nullish-coalescing fallback for tts_stability "
            "(e.g. `tts_stability ?? 0.4`). Remove hardcoded fallback."
        )

    def test_no_nullish_coalescing_to_hardcoded_tts_similarity_boost(self):
        """loadAgentForClient must NOT assign `?? 0.75` as TTS similarity_boost fallback.

        Triangulation: all 3 TTS fields must be covered.
        """
        content = read_index_html()
        assert not re.search(r"tts_similarity_boost\s*\?\?\s*0\.\d+", content), (
            "index.html uses nullish-coalescing fallback for tts_similarity_boost "
            "(e.g. `tts_similarity_boost ?? 0.75`). Remove hardcoded fallback."
        )

    def test_tts_null_guard_skips_override(self):
        """When agent TTS is null, skipTtsOverride must be set (or no override sent).

        The browser must check that TTS values exist before including the TTS override.
        One pattern: `if (defaultAgent.tts_speed != null)` or `hasTts` flag.
        """
        content = read_index_html()
        # Accept either: explicit null/undefined check, or a skipTtsOverride-based guard
        has_null_check = bool(
            re.search(r"tts_speed\s*[!=]=+\s*(null|undefined)", content) or
            re.search(r"tts_speed\s*!==?\s*(null|undefined)", content) or
            re.search(r"typeof\s+.*tts_speed", content) or
            # Accept: hasTts/skipTts flag derived from API values
            re.search(r"hasTts|skipTts|ttsValid|ttsAvailable", content)
        )
        assert has_null_check, (
            "index.html has no null/undefined guard for agent TTS before sending override. "
            "When agent API returns null for TTS fields, the override must be skipped."
        )
