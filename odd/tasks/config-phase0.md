# Configuration Phase 0 — Quick Wins

Goal: make what is configured in Qora actually reach production calls, without changing the configuration model yet. Source: configuration survey (PR #177) and the user's review comments.

## Tasks

- [x] 1. Sync voice and TTS settings (voice_id, tts_model, speed, stability, similarity) to ElevenLabs, and only mark an agent "synced" when ElevenLabs reports the values Qora sent.
- [ ] 2. Tune the production ElevenLabs agent: less eager turn taking; evaluate enabling `end_call` through the custom LLM.
- [ ] 3. Admin UI tools list matches the backend tool registry; agent creation persists the phone number; tools column default has no removed tools.
- [x] 4. Give the qora-demo client its own production ElevenLabs agent (stop sharing Quintana's).
- [x] 5. Production login for Quintana users (link the WorkOS organization).
- [ ] 6. Expose `analysis_language` and next-action rules through the client API.
- [ ] 7. Inject lead profile facts into the agent memory, categorized, at the end of the prompt, only facts evidenced by the lead's own words.
- [ ] 8. Update the survey PDF with the user's corrections: prompt glossary, recontact vs next action, partner model, ElevenLabs cost facts.

## Decisions (from the user)

- No "default agent" concept in the target model; routing must identify the agent.
- Partners are users with several assigned clients; they see the same per-client config panel. Clients use an operations panel with almost nothing editable. Qora global standards are locked everywhere.
- Internal data in English; human-facing deliverables in the person's language, inherited from the client.
- ElevenLabs bills minutes and concurrency, not agent count: one ElevenLabs agent per Qora agent is fine.

## Evidence

- Branch: `fix/config-phase0` (from `main` d518d30).
- Task 2 (part): prod ElevenLabs agent turn_eagerness eager → normal (API, verified). speculative_turn left on (lower latency; it multiplies custom-LLM requests per turn).
- Task 2 finding: ElevenLabs sends its system tools (end_call, voicemail_detection, ...) in the request `tools` array to the custom LLM and expects a streamed `tool_calls` delta back; the webhook ignores request tools, so the agent can never hang up and voicemail detection never fires. Needs a webhook change (in progress).
- Task 4: new ElevenLabs agent `Qora Demo - qora-explainer (prod)` agent_4701m3ynzr4jfb0tyj836t437rbh (custom LLM /voice/qora-demo/custom-llm, initiation client_id=qora-demo, prod post-call webhook, secret headers, turn normal). Railway ELEVENLABS_AGENT_ID → it; after redeploy qora-explainer is bound to it and Quintana's leads-agent keeps agent_3001…; the agents are no longer shared.
- Task 5: linked qora-demo (existing WorkOS org, +demo active member) and quintana-seguros (org created by external_id) in prod. Invitation sent to matiasquintana12.6+quintana@gmail.com (pending acceptance).
- Task 1: `21be92f` (worker; 150 agents+elevenlabs tests green; RED came from pre-existing tests breaking under the new behavior, not a strict new-test-first RED). Payload now carries conversation_config.tts; sync triggers on voice/TTS changes and on create; read-back after PATCH yields synced/drift/error. Deployed. Prod: leads-agent set to the live-tested values (speed 1.2, stability 0.5, similarity 1.0, v4 Turbo) → `synced` by read-back; qora-explainer manual sync → `synced`. Out-of-surface test edits approved mid-task: test_sync_trigger.py (GET mocks + create-path rename), test_router.py (fixture settings + sync mocked); models.py touched for the `drift` outcome.
