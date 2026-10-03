"""Static-import regression guard — skill-packages Task 3.7.

No module under backend/app/ may construct a registry.yaml or *.agent-skill.md
filesystem path literal anymore — skills are resolved from the DB
(skill_packages, skills, skill_revisions) via
app.skills.service.resolve_agent_skills().

The one-time import migration under backend/alembic/ is explicitly excluded:
it reads the filesystem exactly once, by design (P4-D4).
"""

from __future__ import annotations

import re
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent.parent / "app"

# Matches a quoted string-literal path component: "registry.yaml", 'registry.yaml',
# or a string literal ending in .agent-skill.md — the shape a filesystem read would
# need, as opposed to a prose mention in a comment or docstring (e.g. "...has a
# skills registry.yaml" is prose inside a longer sentence, not a path literal).
_FORBIDDEN_LITERAL = re.compile(
    "(\"registry.yaml\"|'registry.yaml'|agent-skill\\.md\"|agent-skill\\.md')"
)


def test_no_remaining_skill_registry_filesystem_reads():
    offenders: list[str] = []
    for path in _APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _FORBIDDEN_LITERAL.search(text):
            offenders.append(str(path.relative_to(_APP_DIR.parent)))

    assert not offenders, (
        "No backend/app/ module may construct a registry.yaml or *.agent-skill.md "
        f"filesystem path literal (skills are DB-backed now): {offenders}"
    )
