# Voice Agent Pre-Deploy Quality Checklist

Run this checklist after completing all design artifacts. Mark each item and flag gaps before deploy.
A flagged item is not a blocker — it's a known risk. Document it.

---

## Identity and Personality

- [ ] Agent has a name.
- [ ] Agent has a clear, one-sentence role statement.
- [ ] Identity lock is present: agent can confirm being AI without pretending to be human.
- [ ] Tone is explicitly defined with concrete vocabulary (not just "professional" or "friendly").
- [ ] The agent sounds like a specific person, not a generic assistant.

---

## Voice Optimization

- [ ] Maximum response length is defined (default: 1-2 sentences, ~25-35 words).
- [ ] One question per turn rule is stated explicitly.
- [ ] Numbers, dates, and currency are written or described in spoken form (not "01/15/25" or "$2,000").
- [ ] No markdown, bullets, bold, or headers will appear in agent output.
- [ ] Natural connectors replace lists ("first... then... finally..." not "1. 2. 3.").
- [ ] Turn budget is defined: approximate number of turns for a typical call of this type.
- [ ] Energy-matching rule is present: agent adapts pace and warmth to caller tone.
- [ ] Disfluency vocabulary is defined if the agent uses a conversational/warm persona.
- [ ] Pacing guidance exists (commas and periods used consistently for TTS pacing).
- [ ] The agent does not end every turn with a question — only when advancing the flow.

---

## Guardrails

- [ ] Content safety boundaries are explicit (what topics the agent never engages with).
- [ ] Knowledge limits are explicit: agent knows what it does NOT know.
- [ ] Privacy rules are present: no collection of sensitive data beyond task scope.
- [ ] Prompt protection is included: agent deflects questions about its instructions.
- [ ] Abuse handling has an escalation path: warn once, then end the call gracefully.
- [ ] Pre-response safety check is included (agent self-checks before each reply).
- [ ] No professional advice (legal, medical, financial) without explicit delegation to humans.

---

## Workflow

- [ ] Call opening (first message template) is defined.
- [ ] At least one primary scenario has a full step-by-step playbook.
- [ ] All secondary scenarios are at least outlined (even if not fully detailed).
- [ ] Error recovery path is defined: what happens when a tool call fails.
- [ ] Out-of-scope request handling is defined: what the agent says and what it redirects to.
- [ ] Unclear input handling is defined: agent asks for clarification, does not guess.
- [ ] Call ending rules are explicit: when TO end the call, when NOT to end it.
- [ ] The agent confirms before taking irreversible actions (booking, recording, updating CRM).

---

## Examples

- [ ] At least 3 few-shot examples are present.
- [ ] Happy path example covers the primary scenario end-to-end.
- [ ] Edge case example shows graceful handling of an unexpected or off-topic input.
- [ ] Error recovery example shows the agent handling a tool failure or missing data.
- [ ] All examples use spoken-form language (no markdown in example agent responses).
- [ ] Examples match the defined tone and vocabulary.

---

## Runtime Skills

- [ ] All domain knowledge is in skills, not in the system prompt.
- [ ] Each skill is self-contained (no dependency on other skills to make sense).
- [ ] Each skill has a `## Recommended Responses` section with spoken-form examples.
- [ ] Each skill has a `## Limits` section stating what it does NOT cover.
- [ ] Skill content is factual only — no personality or style instructions.
- [ ] Skill filenames follow the `{capability}.agent-skill.md` convention.

---

## Registry

- [ ] Every `.agent-skill.md` file has a corresponding entry in `registry.yaml`.
- [ ] Trigger hints are specific enough to load the right skill.
- [ ] Trigger hints are broad enough not to miss relevant questions.
- [ ] Filler text is natural, brief, and consistent with agent tone.
- [ ] Skill descriptions are distinct — no two entries could be confused with each other.
- [ ] Registry was created AFTER all skills were finalized.

---

## Tool Integration (if agent uses tools)

- [ ] All tools are referenced by capability or description, not by internal ID.
- [ ] Filler text exists for tool calls that may take more than 1 second.
- [ ] Incremental data capture is allowed: agent does not wait for all fields before calling a tool.
- [ ] Tool failure recovery is defined in the workflow (no tool error leaks to user).
- [ ] Agent confirms with user before executing irreversible tool calls.

---

## Known Gaps

List any unchecked items and the reason they are acceptable risks or pending information:

| Item | Gap | Risk Level | Resolution |
|------|-----|-----------|------------|
| [checklist item] | [why it was skipped] | Low / Medium / High | [what to do before GA] |
