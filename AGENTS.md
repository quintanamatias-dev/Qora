# Qora Agent Instructions

This repository keeps two different “skill” concepts separated on purpose:

| Area | Path | Purpose | Loaded by |
|------|------|---------|-----------|
| Project developer skills | `skills/{skill-name}/SKILL.md` | Instructions for AI/dev agents that build Qora | OpenCode/Claude-style coding agents |
| Product agent skills | `backend/clients/{client-id}/agents/{agent-slug}/skills/` | Future runtime capabilities for one specific Qora voice agent | Qora application/runtime, not coding agents |
| Local plugins/tools | `Plugin/` | Local MCP/plugin experiments and vendor tooling | Local dev environment only |

## Project Developer Skills

Project skills are for developing this codebase. They are not product features and must not be exposed to Qora customers or voice agents.

| Skill | Purpose | Path |
|-------|---------|------|
| `skill-creator` | Create or update project developer skills with the Gentleman Skills conventions | [`skills/skill-creator/SKILL.md`](skills/skill-creator/SKILL.md) |
| `qora-client-agent-setup` | Create/configure isolated Qora clients, agents, ElevenLabs URLs, and demo verification | [`skills/qora-client-agent-setup/SKILL.md`](skills/qora-client-agent-setup/SKILL.md) |

## Product Agent Skills

Runtime voice-agent skills belong inside the owning client and agent folder:

```text
backend/clients/{client-id}/agents/{agent-slug}/
├── system-prompt.md
└── skills/
    └── {capability}.agent-skill.md
```

Do not name runtime agent skill files `SKILL.md`; use product-facing names such as `{capability}.agent-skill.md` so coding-agent skill registries do not load them by mistake.
