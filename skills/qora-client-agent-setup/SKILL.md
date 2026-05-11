---
name: qora-client-agent-setup
description: "Trigger: create client, configure agent, ElevenLabs setup, voice demo routing. Set up isolated Qora clients and agents."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.1"
---

## Activation Contract

Use this skill when creating or debugging a Qora client + agent setup, especially ElevenLabs Conversational AI routing, demo readiness, tenant isolation, or a new client that must not bleed into another tenant.

## Hard Rules

- Treat `client_id` as the tenant boundary. Never reuse another client's Custom LLM URL.
- **Filesystem `system-prompt.md` is the source of truth for every agent prompt.** DB `agent.system_prompt` is legacy fallback only.
- Runtime agent files belong under `backend/clients/{client-id}/agents/{agent-slug}/`.
- Project developer skills belong under root `skills/`; do not mix them with product agent skills.
- ElevenLabs Custom LLM server URL must use `/api/v1/voice/{client_id}/custom-llm`; ElevenLabs appends `/chat/completions` in its UI.
- ElevenLabs initiation/client-data webhook must include the same `client_id` as the Custom LLM path.
- Store the external ElevenLabs `agent_id` on the matching Qora Agent record, not on the client globally.

## Filesystem Structure for Every Client/Agent

Every Qora agent must have this layout on the filesystem:

```text
backend/clients/{client-id}/
├── agents/
│   └── {agent-slug}/
│       ├── system-prompt.md   ← SOURCE OF TRUTH (overrides DB)
│       └── skills/
│           └── README.md
├── prompt.md                  ← legacy client-level fallback only
└── knowledge.md               ← optional knowledge base
```

### Prompt priority order (PromptLoader.render_for_agent)

1. `clients/{client_id}/agents/{agent_slug}/system-prompt.md` — **preferred, source of truth**
2. `agent.system_prompt` (DB) — legacy fallback for agents not yet migrated
3. `clients/{client_id}/prompt.md` — legacy client-level fallback
4. Hardcoded `JAUMPABLO_PROMPT_TEMPLATE` — last resort

**Always create `system-prompt.md` when setting up a new agent.** Never rely solely on the DB field.

## Decision Gates

| Situation | Action |
|-----------|--------|
| New tenant/client | Create or verify `Client.id`, broker name, default Agent, demo lead if needed |
| New voice agent | Create Agent with unique slug, write `system-prompt.md`, save ElevenLabs `agent_id` |
| Custom LLM fails | First verify ngrok URL externally, then inspect ElevenLabs server URL |
| Agent speaks as another tenant | Check Custom LLM URL path and initiation webhook `client_id` before changing prompts |
| Need runtime skill | Add under `backend/clients/{client-id}/agents/{agent-slug}/skills/` |
| Prompt needs updating | Edit `system-prompt.md` — do NOT edit DB directly |

## Execution Steps

1. Confirm the desired `client_id` and `agent.slug`; do not infer from display names.
2. Create the filesystem structure:
   - `backend/clients/{client-id}/agents/{agent-slug}/system-prompt.md` — write the real prompt
   - `backend/clients/{client-id}/agents/{agent-slug}/skills/README.md` — placeholder for future runtime skills
3. Verify the Qora Agent row has `elevenlabs_agent_id` for the exact ElevenLabs agent.
4. Configure ElevenLabs Custom LLM server URL as `https://{ngrok}/api/v1/voice/{client_id}/custom-llm`.
5. Configure ElevenLabs initiation webhook as `https://{ngrok}/api/v1/voice/initiation?client_id={client_id}&lead_id={{lead_id}}`.
6. Test public reachability: initiation should return Qora dynamic variables; Custom LLM route should return 422 for `{}` because `messages` is missing.
7. Run the demo and confirm backend logs hit `/api/v1/voice/{client_id}/custom-llm/chat/completions`.
8. If `/calls/{conversation_id}/end` returns 404 after a custom LLM error, treat it as a symptom: the CallSession was never created because Custom LLM did not fire.

## Output Contract

Return: client id, agent slug, ElevenLabs agent id, Custom LLM URL, initiation webhook URL, verification evidence, filesystem files created, and any remaining risk.

## References

- `docs/skills-architecture.md` — project skills vs client-scoped runtime agent skills.
- `backend/clients/qora-demo/agents/qora-explainer/system-prompt.md` — canonical Qora demo prompt.
- `backend/clients/quintana-seguros/agents/jaumpablo/system-prompt.md` — canonical Quintana Seguros prompt.
- `backend/app/prompts/loader.py` — `PromptLoader.render_for_agent()` and `load_agent_system_prompt()`.
