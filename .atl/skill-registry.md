# Skill Registry — Qora
# Updated: 2026-05-10

**Delegator use only.** Any agent that launches sub-agents reads this registry to resolve compact rules, then injects them directly into sub-agent prompts. Sub-agents do NOT read this registry or individual SKILL.md files.

---

## Project Skills

These are developer workflow skills for building Qora. They live in `skills/` at the project root.

| Trigger | Skill | Path |
|---------|-------|------|
| create skill, add agent instructions, document AI workflow patterns | skill-creator | /Users/mati/Desktop/Qora/skills/skill-creator/SKILL.md |
| create client, configure agent, ElevenLabs setup, voice demo routing | qora-client-agent-setup | /Users/mati/Desktop/Qora/skills/qora-client-agent-setup/SKILL.md |

---

## Compact Rules

Pre-digested rules per skill. Delegators copy matching blocks into sub-agent prompts as `## Project Standards (auto-resolved)`.

### skill-creator
- Project developer skills live at `skills/{skill-name}/SKILL.md` and are loaded by coding agents.
- Runtime/product agent skills live at `backend/clients/{client-id}/agents/{agent-slug}/skills/` and must NOT be named `SKILL.md`.
- Create skills only for repeated project workflows, conventions, or complex decision trees.
- Frontmatter must include `name`, one-line quoted `description` with Trigger words, `license`, `metadata.author`, and `metadata.version`.
- Put templates/schemas/examples in `assets/`; put long local references in `references/`.
- Register project skills in `AGENTS.md` and update this registry after changes.

### qora-client-agent-setup
- Treat `client_id` as the tenant boundary; never reuse another client's Custom LLM URL.
- Runtime agent files belong under `backend/clients/{client-id}/agents/{agent-slug}/`.
- ElevenLabs Custom LLM server URL is `https://{ngrok}/api/v1/voice/{client_id}/custom-llm`; ElevenLabs appends `/chat/completions`.
- ElevenLabs initiation webhook is `https://{ngrok}/api/v1/voice/initiation?client_id={client_id}&lead_id={{lead_id}}`.
- Store the ElevenLabs `agent_id` on the matching Qora Agent row.
- If `/calls/{conversation_id}/end` returns 404 after custom LLM error, debug Custom LLM firing first; the session was never created.

---

## Qora Project Standards

### Python + FastAPI Conventions
- Use `pyproject.toml` for project configuration
- Use `pytest` for backend testing.
- Async-first: all I/O operations MUST be async
- Type hints required on all public functions
- Pydantic v2 for request/response models

### Architecture Patterns
- Channel abstraction: agents communicate through ChannelAdapter interface
- Event-driven: conversation completion emits events for async processing
- SQLite for MVP, PostgreSQL-ready schema design
- Each agent has a configurable system prompt per client
- ElevenLabs Conversational AI Custom LLM URL for tenant routing uses `/api/v1/voice/{client_id}/custom-llm`; ElevenLabs appends `/chat/completions` in the Custom LLM UI.
- Qora demo client id is `qora-demo`; never route Qora demo traffic through `quintana-seguros`.

## Project Conventions

| File | Path | Notes |
|------|------|-------|
| AGENTS.md | /Users/mati/Desktop/Qora/AGENTS.md | Index for Qora project developer skills vs client-scoped runtime agent skills |
