# Configuration Phase 0 — Quick Wins

Goal: make what is configured in Qora actually reach production calls, without changing the configuration model yet. Source: configuration survey (PR #177) and the user's review comments.

## Tasks

- [ ] 1. Sync voice and TTS settings (voice_id, tts_model, speed, stability, similarity) to ElevenLabs, and only mark an agent "synced" when ElevenLabs reports the values Qora sent.
- [ ] 2. Tune the production ElevenLabs agent: less eager turn taking; evaluate enabling `end_call` through the custom LLM.
- [ ] 3. Admin UI tools list matches the backend tool registry; agent creation persists the phone number; tools column default has no removed tools.
- [ ] 4. Give the qora-demo client its own production ElevenLabs agent (stop sharing Quintana's).
- [ ] 5. Production login for Quintana users (link the WorkOS organization).
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
