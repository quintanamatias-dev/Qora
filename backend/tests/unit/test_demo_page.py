"""Tests for the static demo page (backend/app/static/index.html).

PR3 Task 4.1: RED tests that prove the demo page:
  - Does NOT contain a hardcoded ElevenLabs agent ID value
  - Has a code path that fetches agents from the API for the selected client
  - Populates the EL agent ID from the selected agent's elevenlabs_agent_id
  - Does NOT pass voice_id as an override in any WebSocket or fetch calls
  - Shows guidance when no leads are available for the selected client

These tests parse the static HTML + embedded JS as text/content assertions
(no browser runtime needed). The design constraint is: the HTML must carry
the implementation contract so static analysis can prove it.

Test layer: Unit (static file analysis — no DB, no HTTP server needed)
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Path to the demo page under test
_DEMO_PAGE = Path(__file__).parent.parent.parent / "app" / "static" / "index.html"


@pytest.fixture(scope="module")
def demo_html() -> str:
    """Read the demo page HTML once for all tests in this module."""
    return _DEMO_PAGE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Task 4.1a: No hardcoded ElevenLabs agent ID
# ---------------------------------------------------------------------------


def test_demo_page_has_no_hardcoded_elevenlabs_agent_id(demo_html: str):
    """The agentId input MUST NOT have a hardcoded value attribute.

    Previously: value="agent_9401kn60tcbhfwhba7p7q3n5cfca"
    After fix:  value="" (empty) — populated by JS from API response.

    This proves the demo page no longer hardcodes an EL agent ID that could
    go stale or leak a production agent ID to anyone viewing source.
    """
    # The old hardcoded agent ID must NOT appear anywhere in the file
    assert "agent_9401kn60tcbhfwhba7p7q3n5cfca" not in demo_html, (
        "Hardcoded ElevenLabs agent ID found in demo page. "
        "Remove value= attribute and populate from API."
    )


def test_demo_page_agentid_input_has_no_hardcoded_value(demo_html: str):
    """The agentId <input> must NOT carry a non-empty value= attribute.

    Triangulation of test_demo_page_has_no_hardcoded_elevenlabs_agent_id:
    Tests the pattern `value="agent_` which would match any hardcoded agent ID,
    not just the specific one removed in task 4.2.
    """
    # Pattern: input with id="agentId" and value="agent_..." is forbidden
    assert 'id="agentId"' in demo_html, "agentId input element must exist"
    # Verify no hardcoded agent_ prefix in the value attribute
    assert 'value="agent_' not in demo_html, (
        "agentId input has a hardcoded value starting with 'agent_'. "
        "Must be empty — populated dynamically from API."
    )


# ---------------------------------------------------------------------------
# Task 4.1b: Demo fetches agents from API on client change
# ---------------------------------------------------------------------------


def test_demo_page_fetches_agents_api_on_client_change(demo_html: str):
    """The onClientChange function MUST fetch agents from /api/v1/clients/{id}/agents.

    After task 4.2 the client-change handler must:
    1. Fetch agents: GET /api/v1/clients/{clientId}/agents
    2. Find the default agent (is_default=true)
    3. Populate agentId input with agent.elevenlabs_agent_id

    This test verifies the JS contains the agents API call pattern.
    """
    # The agents endpoint path must appear in the JS
    assert "/agents" in demo_html, (
        "Demo page JS must fetch the agents API endpoint to get elevenlabs_agent_id. "
        "Add: fetch('/api/v1/clients/' + clientId + '/agents') in onClientChange."
    )


def test_demo_page_reads_elevenlabs_agent_id_from_agent_response(demo_html: str):
    """The JS must read elevenlabs_agent_id from the agent API response.

    Triangulation: verifies the specific field name `elevenlabs_agent_id`
    appears in the script, proving the code accesses the correct property
    from the agent API response (not a different field name).
    """
    assert "elevenlabs_agent_id" in demo_html, (
        "Demo page JS must access agent.elevenlabs_agent_id from the API response. "
        "The agentId input must be populated from this field, not hardcoded."
    )


# ---------------------------------------------------------------------------
# Task 4.1c: No voice_id override in signed-URL or WebSocket calls
# ---------------------------------------------------------------------------


def test_demo_page_does_not_pass_voice_id_in_websocket_url(demo_html: str):
    """The WebSocket URL MUST NOT include a voice_id query parameter.

    ElevenLabs conversational agents manage voice through the agent config,
    not through the WebSocket URL. Passing voice_id overrides the agent's
    configured voice and is forbidden by this spec.
    """
    # The WS URL pattern must NOT include voice_id
    # Valid:   wss://api.elevenlabs.io/v1/convai/conversation?agent_id=...
    # Invalid: wss://...?agent_id=...&voice_id=...
    assert "voice_id" not in demo_html, (
        "Demo page JS passes voice_id in WebSocket URL or fetch call. "
        "Per spec: no voice_id override — voice is configured in EL agent dashboard."
    )


# ---------------------------------------------------------------------------
# Task 4.1d: No-lead guidance is surfaced
# ---------------------------------------------------------------------------


def test_demo_page_shows_no_lead_guidance(demo_html: str):
    """When no leads exist for the selected client, the page must show guidance.

    The guidance must direct the user to create a lead in the admin panel.
    After task 4.2, loadLeadsForClient must detect the empty leads case and
    surface an actionable message — not silently show a disabled select.
    """
    # Must contain text directing user to the admin panel
    assert "admin" in demo_html.lower(), (
        "Demo page must reference 'admin' in its no-lead guidance. "
        "When leads are empty, users should be directed to create one in admin."
    )


def test_demo_page_no_lead_guidance_references_create_lead(demo_html: str):
    """No-lead guidance must be actionable: reference creating a lead.

    Triangulation of test_demo_page_shows_no_lead_guidance:
    Tests for a specific guidance message (not just any 'create' DOM call)
    that directs the user to the admin panel to create a lead.
    """
    # Must contain a user-visible text string about creating leads in admin
    # Accept Spanish or English phrasing — the key is user-facing text, not
    # JavaScript DOM API calls like createElement / createTextNode.
    html_lower = demo_html.lower()
    has_create_lead_guidance = (
        "crear un lead" in html_lower
        or "create a lead" in html_lower
        or "agregar un lead" in html_lower
        or "creá un lead" in html_lower
        or "crea un lead" in html_lower
    )
    assert has_create_lead_guidance, (
        "Demo page must show actionable guidance when no leads are found. "
        "Message must contain user-visible text like 'crear un lead' or 'create a lead'. "
        "JavaScript DOM API calls (createElement) do NOT count as guidance."
    )


# ---------------------------------------------------------------------------
# Task 4.1e: Demo auto-selects qora-demo client (JS static check)
# ---------------------------------------------------------------------------


def test_demo_page_prefers_qora_demo_client(demo_html: str):
    """The loadClients function MUST attempt to pre-select the qora-demo client.

    After task 4.2, after fetching clients the code must search for 'qora-demo'
    and select it if found, falling back to the first client otherwise.
    This is a static assertion: the string 'qora-demo' must appear in the JS.
    """
    assert "qora-demo" in demo_html, (
        "Demo page JS must explicitly prefer the 'qora-demo' client on load. "
        "Add logic to find and select 'qora-demo' from the client list."
    )


# ---------------------------------------------------------------------------
# Triangulation: backend HTTP endpoint serving the demo page
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_app():
    """Minimal FastAPI app that mounts the /demo static files — same as main.py."""
    import os
    from fastapi import FastAPI
    from starlette.staticfiles import StaticFiles

    mini_app = FastAPI()
    static_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "app", "static")
    )
    mini_app.mount("/demo", StaticFiles(directory=static_dir, html=True), name="demo")
    return mini_app


@pytest.mark.anyio
async def test_demo_endpoint_returns_200_html(demo_app):
    """GET /demo returns 200 with HTML content — triangulation via HTTP layer.

    Proves the static file is wired correctly and not just readable from disk.
    """
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=demo_app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        response = await client.get("/demo/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        # Key structural assertion: agentId input must exist
        assert 'id="agentId"' in response.text


@pytest.mark.anyio
async def test_demo_endpoint_html_has_no_hardcoded_agent_id(demo_app):
    """GET /demo confirms no hardcoded agent ID is served — triangulation.

    Triangulation of test_demo_page_has_no_hardcoded_elevenlabs_agent_id:
    Tests the SAME contract via HTTP (different code path than reading from disk).
    """
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=demo_app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        response = await client.get("/demo/")
        assert response.status_code == 200
        html = response.text
        # Must not contain the old hardcoded agent ID
        assert "agent_9401kn60tcbhfwhba7p7q3n5cfca" not in html
        # Must contain the agents API fetch
        assert "elevenlabs_agent_id" in html
        assert "qora-demo" in html
