---
name: qora-agent-designer
description: "Trigger: design agent, write system prompt, create runtime skill, voice agent content, agent-skill.md, registry.yaml. Design the content of a Qora voice agent."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## Activation Contract

Use this skill when designing the CONTENT of a Qora voice agent: writing `system-prompt.md`, creating runtime knowledge skills (`.agent-skill.md` files), and generating `registry.yaml`.

This is the CONTENT design skill. For infrastructure (ElevenLabs URLs, DB records, filesystem scaffold), use `qora-client-agent-setup`.

## Hard Rules

- The system prompt is the agent's SOUL — identity, personality, style, behavior, and constraints live here.
- Runtime skills are KNOWLEDGE — factual content loaded dynamically via the `load_skill` tool.
- The system prompt must NEVER contain domain knowledge that belongs in a skill.
- Skills must NEVER contain personality, style, or behavioral instructions — those belong in the system prompt.
- All system prompts use XML tags for structure (Qora convention, matches ElevenLabs Custom LLM).
- All system prompts must be voice-optimized: short turns, spoken-form numbers, no markdown in output, one question at a time.
- Runtime skill files are named `{capability}.agent-skill.md` — never `SKILL.md`.
- `registry.yaml` is the LAST artifact — only after system-prompt and all skills are finalized.
- Do not hallucinate client data, product facts, or integration capabilities. If unsure, leave a `[PLACEHOLDER]`.
- Context hygiene rule: each dynamic datum enters agent context exactly once, through the best channel for that agent.
- Lead data uses prompt placeholders OR one structured lead context block, never both.
- Do not use generic `confirmed_facts` blocks. They mix stale facts, notes, profile data, and interest history.
- `current_insurance` comes from the Lead column only. Post-call corrections must update that column.

## Decision Gates

| Question | Goes in system prompt | Goes in skill |
|----------|-----------------------|---------------|
| Who is the agent? | Yes | No |
| How does the agent speak? | Yes | No |
| What must the agent never do? | Yes | No |
| What does the product cost? | No | Yes |
| What are the product features? | No | Yes |
| What is the cancellation policy? | No | Yes |
| How does the agent greet? | Yes (workflow) | No |
| What are the FAQs? | No | Yes |

## Context Hygiene Checklist

- Choose one channel per datum: prompt placeholder, context block, or on-demand skill/tool result.
- Do not duplicate lead fields between prompt placeholders and `[DATOS DEL LEAD]` / `lead_profile`.
- Keep dynamic lead data in context or tool results; keep behavior in the system prompt; keep knowledge in runtime skills.
- Use `misc_notes` only through one explicit channel if the agent needs it.
- Keep `call_history` limited to the last 3 post-call summaries. Do not inject past transcripts.
- Do not trim current conversation history unless there is a deliberate memory strategy.

## Execution Steps

### Step 1: Gather Client Information

Ask the following before writing anything:

- What does the client/company do?
- What is this agent's specific purpose? (lead follow-up, support, scheduling, demos, etc.)
- What data will the agent have about the person it's calling? (fields injected as context)
- What tools/integrations will the agent use? (CRM write, calendar booking, quote lookup, etc.)
- What tone and personality should the agent have?
- What language(s)? Are there regional speech patterns to follow?
- Any brand names, product names, or acronyms that need pronunciation guidance?
- What are the agent's hard limits? (what it must NEVER say or do)
- How long should calls typically last? (sets turn budget guidance)

Do not proceed to Step 2 until you have enough answers to make design decisions. Missing information should become explicit `[PLACEHOLDER]` markers in the output — never invented content.

### Step 2: Analyze and Distribute Information

Separate gathered information into two buckets:

**System prompt content:**
- Agent identity, name, role
- Tone and communication style
- Language and regional patterns
- Response length and format rules
- How to handle uncertainty
- What topics are off-limits
- Step-by-step conversation workflows
- Few-shot examples
- Identity lock (agent must stay in character)

**Skill content:**
- Product facts, features, pricing
- Policies and procedures
- FAQs and recommended answers
- Domain-specific knowledge the agent retrieves on demand

**Rule of thumb:** If you asked "who is this agent and how does it behave?" → system prompt. If you asked "what does this agent know about a topic?" → skill.

### Step 3: Create System Prompt

Use `assets/system-prompt-template.md` as the base. Produce `system-prompt.md` with these six required sections (XML tags, in this order):

1. `<role>` — Identity and personality: name, role, tone, communication style, identity lock.
2. `<call_start>` — How to open the call: recommended first message verbatim or as a template.
3. `<response_guidelines>` — Voice rules: max 1-2 sentences per turn, one question at a time, spoken-form numbers, no markdown, turn budget, energy matching.
4. `<guardrails>` — Hard constraints: content safety, knowledge limits, privacy, no prompt disclosure, abuse escalation, pre-response safety check.
5. `<workflow>` — Step-by-step playbook for each conversation scenario. Include error recovery and out-of-scope handling.
6. `<examples>` — Minimum 3 few-shot examples: happy path, edge case, error recovery.

Add these optional sections as needed:
- `<style>` — Language-specific speech patterns (voseo, regional vocabulary, what to avoid).
- `<voice>` — TTS-specific rules if different from response_guidelines.
- `<context_usage>` — How to use injected lead data and memory fields.
- `<skills_usage>` — How to reference loaded skills (by description, not filename).
- `<uncertainty>` — What to say when a fact is not confirmed.
- `<sales_stance>` — Sales approach and positioning if applicable.

### Step 4: Create Runtime Skills

For each knowledge domain identified in Step 2, create `{capability}.agent-skill.md` using `assets/agent-skill-template.md`.

Each skill must be:
- Self-contained: an agent reading ONLY this file gets enough context to answer questions about this topic.
- Factual: no personality, no style instructions.
- Bounded: includes an explicit `## Limits` section stating what it does NOT cover.
- Spoken-response-ready: includes `## Recommended Responses` with suggested spoken-form answers the agent adapts (not reads verbatim).

Naming: `{capability}.agent-skill.md` where capability is lowercase-hyphenated (e.g., `product-pricing.agent-skill.md`, `cancellation-policy.agent-skill.md`).

### Step 5: Generate Registry

Create `registry.yaml` using `assets/registry-template.yaml` after all skills are final.

Each entry needs:
- `name` — matches the skill filename without `.agent-skill.md`
- `description` — what knowledge this skill provides (agent uses this to decide when to load it)
- `trigger_hint` — specific scenarios or question types that should trigger loading this skill
- `filler_text` — natural spoken phrase while the skill loads (brief, human-sounding)

Trigger hints must be specific enough to load the right skill but broad enough not to miss relevant questions.

### Step 6: Validate with Checklist

Run through `assets/voice-prompting-checklist.md` before marking the design complete. Flag any unchecked item as a known gap.

## Output Contract

Return:
- `system-prompt.md` — complete, voice-optimized, XML-tagged
- One `{capability}.agent-skill.md` per knowledge domain
- `registry.yaml` — one entry per skill
- Checklist summary: which items passed, which are flagged as gaps
- Any `[PLACEHOLDER]` markers with notes on what information is still needed

## References

- `assets/system-prompt-template.md` — template with all 6 required sections and placeholders.
- `assets/agent-skill-template.md` — template for runtime knowledge skills.
- `assets/registry-template.yaml` — registry format.
- `assets/voice-prompting-checklist.md` — pre-deploy quality checklist.
- `references/voice-prompting-guide.md` — dense reference: voice vs text, anti-patterns, disfluency, tool integration.
- `backend/clients/qora-demo/agents/qora-explainer/system-prompt.md` — canonical example (production).
- `backend/clients/qora-demo/agents/qora-explainer/skills/Qora-info.agent-skill.md` — canonical skill example.
- `backend/clients/qora-demo/agents/qora-explainer/skills/registry.yaml` — canonical registry example.
- `skills/qora-client-agent-setup/SKILL.md` — infrastructure complement to this skill.
