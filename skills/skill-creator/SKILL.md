---
name: skill-creator
description: "Trigger: create skill, add agent instructions, document AI workflow patterns. Create project developer skills for Qora."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## Activation Contract

Use this skill when creating or updating Qora **project developer skills** under `skills/`. Do not use it for Qora runtime voice-agent capabilities under `backend/clients/{client-id}/agents/{agent-slug}/skills/`.

## Hard Rules

- Project developer skills live at `skills/{skill-name}/SKILL.md`.
- Runtime/product agent skills live at `backend/clients/{client-id}/agents/{agent-slug}/skills/` and must not be named `SKILL.md`.
- A skill is an LLM instruction contract, not human documentation.
- Keep `SKILL.md` concise; move templates to `assets/` and deep references to `references/`.
- Frontmatter must include `name`, one-line quoted `description` with trigger words, `license`, `metadata.author`, and `metadata.version`.
- Register project skills in `AGENTS.md`.

## Decision Gates

| Need | Action |
|------|--------|
| Repeated project workflow | Create/update `skills/{name}/SKILL.md` |
| One-off note | Put it in docs or memory, not a skill |
| Code template/schema/example | Add it under `assets/` |
| Longer conceptual detail | Add it under `references/` or link local docs |
| Voice-agent runtime behavior | Use `backend/clients/{client-id}/agents/{agent-slug}/skills/`, not project skills |

## Execution Steps

1. Check `AGENTS.md` and `docs/skills-architecture.md` before writing.
2. Confirm the skill does not already exist and the pattern is reusable.
3. Create `skills/{skill-name}/SKILL.md` with: Activation Contract, Hard Rules, Decision Gates, Execution Steps, Output Contract, References.
4. Add optional `assets/` or `references/` only when they reduce cognitive load.
5. Register the skill in `AGENTS.md`.
6. Update `.atl/skill-registry.md` and save the registry to Engram when available.

## Output Contract

Return: files changed, whether supporting assets/references were added, AGENTS.md registration status, and any follow-up needed.

## References

- `docs/skills-architecture.md` — Qora distinction between project developer skills and client-scoped runtime agent skills.
- `assets/SKILL-TEMPLATE.md` — vendored template from Gentleman Skills `skill-creator`.
