# Qora Skills Architecture

Qora uses “skills” in two different contexts. Keep them separate or the project becomes impossible to reason about.

## 1. Project developer skills

**Path:** `skills/{skill-name}/SKILL.md`

These are instructions for AI coding agents and maintainers while building Qora. Examples: how to create skills, how to debug ElevenLabs routing, how to verify voice demo readiness.

Rules:
- They may reference source files, tests, local docs, and development commands.
- They are loaded by the coding environment, not by Qora users.
- They must use the `SKILL.md` filename and valid skill frontmatter.
- Register them in `AGENTS.md`.

## 2. Product/runtime agent skills

**Path:** `backend/clients/{client-id}/agents/{agent-slug}/skills/`

These are future capabilities for Qora voice agents themselves. They belong under the owning client because agent behavior is tenant-scoped: Qora's `qora-explainer` skills must not sit beside Quintana's agents or in a global root folder.

Rules:
- Do **not** use `SKILL.md` for runtime agent skills.
- Prefer names like `skills/{capability}.agent-skill.md`, `tools/{tool}.md`, and `policies/{policy}.md`.
- Treat them as product configuration, not developer workflow instructions.
- Keep each agent isolated under its own client and slug folder.

Suggested shape:

```text
backend/clients/
└── qora-demo/
    └── agents/
        └── qora-explainer/
            ├── system-prompt.md
            ├── policies/
            ├── tools/
            └── skills/
                └── example.agent-skill.md
```

## 3. Plugins and local tooling

**Path:** `Plugin/`

This is for local MCP/plugin tooling. It is not the project skill registry and it is currently ignored by git.
