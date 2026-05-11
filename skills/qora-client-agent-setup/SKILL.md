---
name: qora-client-agent-setup
description: "Trigger: create client, configure agent, ElevenLabs setup, voice demo routing. Set up isolated Qora clients and agents."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## Activation Contract

Use this skill when creating or debugging a Qora client + agent setup, especially ElevenLabs Conversational AI routing, demo readiness, tenant isolation, or a new client that must not bleed into another tenant.

## Hard Rules

- Treat `client_id` as the tenant boundary. Never reuse another client's Custom LLM URL.
- Runtime agent files belong under `backend/clients/{client-id}/agents/{agent-slug}/`.
- Project developer skills belong under root `skills/`; do not mix them with product agent skills.
- ElevenLabs Custom LLM server URL must use `/api/v1/voice/{client_id}/custom-llm`; ElevenLabs appends `/chat/completions` in its UI.
- ElevenLabs initiation/client-data webhook must include the same `client_id` as the Custom LLM path.
- Store the external ElevenLabs `agent_id` on the matching Qora Agent record, not on the client globally.

## Decision Gates

| Situation | Action |
|-----------|--------|
| New tenant/client | Create or verify `Client.id`, broker name, default Agent, demo lead if needed |
| New voice agent | Create Agent with unique slug and save its ElevenLabs `agent_id` |
| Custom LLM fails | First verify ngrok URL externally, then inspect ElevenLabs server URL |
| Agent speaks as another tenant | Check Custom LLM URL path and initiation webhook `client_id` before changing prompts |
| Need runtime skill | Add under `backend/clients/{client-id}/agents/{agent-slug}/skills/` |

## Execution Steps

1. Confirm the desired `client_id` and `agent.slug`; do not infer from display names.
2. Verify the Qora Agent row has `elevenlabs_agent_id` for the exact ElevenLabs agent.
3. Configure ElevenLabs Custom LLM server URL as `https://{ngrok}/api/v1/voice/{client_id}/custom-llm`.
4. Configure ElevenLabs initiation webhook as `https://{ngrok}/api/v1/voice/initiation?client_id={client_id}&lead_id={{lead_id}}`.
5. Test public reachability: initiation should return Qora dynamic variables; Custom LLM route should return 422 for `{}` because `messages` is missing.
6. Run the demo and confirm backend logs hit `/api/v1/voice/{client_id}/custom-llm/chat/completions`.
7. If `/calls/{conversation_id}/end` returns 404 after a custom LLM error, treat it as a symptom: the CallSession was never created because Custom LLM did not fire.

## Output Contract

Return: client id, agent slug, ElevenLabs agent id, Custom LLM URL, initiation webhook URL, verification evidence, and any remaining risk.

## References

- `docs/skills-architecture.md` — project skills vs client-scoped runtime agent skills.
- `backend/clients/qora-demo/agents/qora-explainer/` — canonical Qora demo agent file location.
