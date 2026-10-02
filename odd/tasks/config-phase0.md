# Configuration Phase 0 — Quick Wins

Goal: make what is configured in Qora actually reach production calls, without changing the configuration model yet. Source: configuration survey (PR #177) and the user's review comments.

## Tasks

- [x] 1. Sync voice and TTS settings (voice_id, tts_model, speed, stability, similarity) to ElevenLabs, and only mark an agent "synced" when ElevenLabs reports the values Qora sent.
- [x] 2. Tune the production ElevenLabs agent: less eager turn taking; evaluate enabling `end_call` through the custom LLM.
- [x] 3. Admin UI tools list matches the backend tool registry; agent creation persists the phone number; tools column default has no removed tools.
- [x] 4. Give the qora-demo client its own production ElevenLabs agent (stop sharing Quintana's).
- [x] 5. Production login for Quintana users (link the WorkOS organization).
- [x] 6. Expose `analysis_language` and next-action rules through the client API.
- [x] 7. Inject lead profile facts into the agent memory, categorized, at the end of the prompt, only facts evidenced by the lead's own words.
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
- Task 2: `4b58703` (worker; strict RED: 7 new tests failed first; 196 voice tests green; ruff clean). Request tools not named like Qora tools are offered to the model and forwarded to ElevenLabs as a tool_calls delta + finish_reason tool_calls, without local execution, filler or follow-up call. Deployed; `end_call` enabled on the prod Quintana agent (voicemail_detection already on). Live check via ElevenLabs simulate-conversation against prod: the user declined, the model called end_call (reason recorded) and ElevenLabs ended the conversation. Follow-up: the prompt should ask the agent to pass a farewell `message` with end_call (it hung up without saying goodbye).
- Task 3: `08e4caf` (worker; RED: new phone test failed with None; 120 agents tests, 119 admin frontend tests, lint and tsc green). Create persists elevenlabs_phone_number_id and returns it; Agent.tools_enabled default is ["get_lead_details"]; the admin form offers the 5 valid tools (load_skill is auto-injected). Not deployed yet (batched).
- Task 6: `0d764d0` (worker; RED 15/16 new tests; 16 + 107 client tests green; ruff clean). analysis_language and next_action_* in ClientUpdate/ClientResponse with validation; retry-outcomes response default aligned with DB. Tasks 3 and 6 deployed together and verified via GET /clients/quintana-seguros.
- Task 7: `ef7f274` (worker; RED not captured by the worker — parent verified it afterwards by stashing the implementation: 6/7 new tests failed, 7/7 pass with it; 477 related tests green). Write-time gate drops profile facts whose evidence is only an "Agente:" line; active facts rendered after the lead block (before per-turn loaded skills). Deployed; prod log shows profile_facts_count=8 for the test lead. Facts written before the gate (e.g. the WhatsApp one) remain — cleanup is a follow-up.
- Full-suite check after phase 0 found 9 backend failures in older suites (missing read-back GET mocks; MagicMock voice context without profile_facts_block). Fixed in `6796004` (test-only, assertions unchanged). Root-causing the `None` sync status exposed a real gap: `_fetch_agent_config` only caught timeouts/network errors, so a protocol error or non-JSON body escaped the background sync. Fixed test-first in `54f7849` (RED: 2 new cases raised). Full backend suite: 3786 passed, 0 failed; frontend 875 passed, lint and tsc clean.
