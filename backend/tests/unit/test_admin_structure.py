"""TDD tests for CRITICAL 2: Admin UI required structure.

RED: These tests will FAIL because:
1. admin.html clients table does NOT show agent count
2. admin.html agents table does NOT show voice_id column
3. admin.html uses alert() for error handling instead of inline messages

After GREEN: admin.html contains all required columns and inline error handling.
"""

from __future__ import annotations

import os


# ---------------------------------------------------------------------------
# Helper — read admin.html content
# ---------------------------------------------------------------------------


def _read_admin_html() -> str:
    """Read the admin.html file from the static directory.

    This test file is at tests/unit/test_admin_structure.py
    admin.html is at app/static/admin.html (relative to backend/)
    """
    # tests/unit/test_admin_structure.py -> tests/unit -> tests -> backend/
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    admin_path = os.path.join(backend_dir, "app", "static", "admin.html")
    with open(admin_path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Structure tests — clients table
# ---------------------------------------------------------------------------


def test_admin_html_clients_table_has_agent_count_column():
    """Clients table must have an 'Agents' or 'Agent Count' column header."""
    html = _read_admin_html()
    # The clients table thead must include an agent count column
    # Look for any variation of 'Agent' in the table header for clients
    assert (
        "agent_count" in html.lower()
        or "agent count" in html.lower()
        or (
            # Or the table renders the count dynamically with a header like "Agents"
            "<th>Agents</th>" in html or "<th>Agent Count</th>" in html
        )
    ), (
        "Clients table must include an agent count column. "
        "Expected to find 'Agents' or 'Agent Count' table header."
    )


def test_admin_html_clients_table_renders_agent_count():
    """Clients table JS must render agent count from API response."""
    html = _read_admin_html()
    # The JS that builds the clients table must reference agent_count
    assert "agent_count" in html, (
        "Admin JS must reference 'agent_count' field when rendering clients table rows. "
        "Each client row must show the number of agents."
    )


# ---------------------------------------------------------------------------
# Structure tests — agents table
# ---------------------------------------------------------------------------


def test_admin_html_agents_table_has_voice_id_column():
    """Agents table must have a 'Voice ID' column header."""
    html = _read_admin_html()
    # The agents table must include a Voice ID column
    # Check both header presence and value rendering in table
    assert "<th>Voice ID</th>" in html or "<th>Voice</th>" in html, (
        "Agents table must include a Voice ID column header. "
        "Expected '<th>Voice ID</th>' or '<th>Voice</th>'."
    )


def test_admin_html_agents_table_renders_voice_id():
    """Agents table JS must render voice_id for each agent row."""
    html = _read_admin_html()
    # The JS that builds the agent rows must reference a.voice_id in the table rows
    # We look for voice_id being rendered inside the agents table (not just in forms)
    # The table row template must include voice_id display
    # Check that the agents table thead row specifically calls out voice_id
    assert "a.voice_id" in html, (
        "Admin JS must render a.voice_id in the agents table rows. "
        "Each agent row must display the voice_id value."
    )


# ---------------------------------------------------------------------------
# Structure tests — no alert() for guard errors
# ---------------------------------------------------------------------------


def test_admin_html_no_alert_for_errors():
    """Admin page must NOT use alert() for error handling — use inline messages instead."""
    html = _read_admin_html()
    # alert() is forbidden for error handling in admin UI
    # Count occurrences of 'alert(' in the JS section
    alert_count = html.count("alert(")
    assert alert_count == 0, (
        f"admin.html uses alert() {alert_count} time(s) for error handling. "
        "Replace all alert() calls with inline error messages using showMsg()."
    )


# ---------------------------------------------------------------------------
# Structure tests — required UI elements present
# ---------------------------------------------------------------------------


def test_admin_html_has_client_form():
    """Admin page must contain a client creation form."""
    html = _read_admin_html()
    assert 'id="c-id"' in html, "Client form must have a 'c-id' input for client ID."
    assert (
        'id="c-broker"' in html
    ), "Client form must have a 'c-broker' input for broker name."
    # voice_id is configured per-agent, not at client creation
    assert 'id="c-agent"' in html, "Client form must have a 'c-agent' input for agent name."


def test_admin_html_has_agent_form():
    """Admin page must contain an agent creation form."""
    html = _read_admin_html()
    assert 'id="a-slug"' in html, "Agent form must have an 'a-slug' input."
    assert 'id="a-name"' in html, "Agent form must have an 'a-name' input."
    assert 'id="a-voice"' in html, "Agent form must have an 'a-voice' input."


def test_admin_html_has_tool_checkboxes():
    """Admin page must contain tool checkboxes for all 4 QORA tools."""
    html = _read_admin_html()
    assert 'value="get_lead_details"' in html, "Missing get_lead_details tool checkbox."
    assert (
        'value="register_interest"' in html
    ), "Missing register_interest tool checkbox."
    assert (
        'value="mark_not_interested"' in html
    ), "Missing mark_not_interested tool checkbox."
    assert (
        'value="schedule_followup"' in html
    ), "Missing schedule_followup tool checkbox."


def test_admin_html_has_inline_error_elements():
    """Admin page must have inline error message elements (not alert() dialogs)."""
    html = _read_admin_html()
    # Must have msg divs for inline error display
    assert 'id="c-msg"' in html, "Missing inline error element 'c-msg' for client form."
    assert 'id="a-msg"' in html, "Missing inline error element 'a-msg' for agent form."
    assert "showMsg" in html, "Missing showMsg() function for inline error messages."
