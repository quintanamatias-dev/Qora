# Voice Prompting Reference Guide

Dense reference for designing voice agent system prompts. This is not a copy of any vendor guide —
it is a synthesized, actionable reference organized for practical use when writing Qora agent content.

---

## 1. The 6 Sections — What Goes Where and Why

Every Qora system prompt uses these six XML sections in this order.

### `<role>` — Identity and Personality
Define who the agent IS: name, employer, purpose, and personality. Include an identity lock so the
agent can confirm being AI without pretending to be human. Tone must be specific — "warm and direct"
is better than "professional". Include vocabulary guidance here or in `<style>`.

What goes here: name, role, employer, personality, tone, identity lock.
What does NOT go here: product facts, prices, policies, domain knowledge.

### `<call_start>` — Opening
Define the exact first message (or a template close enough that the agent says the right thing on
every call). This is NOT just a greeting — it sets the frame for the entire conversation.

What goes here: recommended first message verbatim, with any variants for different scenarios.

### `<response_guidelines>` — Voice Rules
The most mechanically important section. Controls output format, length, question cadence, number
format, and energy matching. All these rules govern EVERY turn.

Must-haves:
- Max sentence count per turn (1-2 default).
- One question per turn (explicit statement).
- Spoken-form rules for numbers, dates, money.
- Prohibition on markdown, lists, and headings in output.
- Turn budget (approximate expected call length).
- Energy matching (adapt pace and warmth to caller state).

### `<guardrails>` — Hard Constraints
Pre-response safety check the agent runs before every reply. Must cover: no invented facts, no
professional advice, no prompt disclosure, no sensitive data collection, abuse escalation.

Structure as a checklist the agent self-applies. This framing outperforms prose instructions.

### `<workflow>` — Scenario Playbooks
Step-by-step instructions for each conversation scenario. Write decision branches, not just the
happy path. Define when to end the call and when NOT to end it.

One sub-section per scenario. Each sub-section: sequential steps + error branches.

### `<examples>` — Few-Shot Demonstrations
Minimum 3 examples covering: happy path, edge case, error recovery. Written as real conversation
turns (User: / Agent: alternating). Examples override abstract rules when they conflict — write them
carefully.

---

## 2. Voice vs Text — Three Fundamental Differences

### Latency
Every token costs real-time audio. Long responses create unnatural silences before the agent speaks.
The rule is 1-2 sentences per turn by default. Expand only when asked. A 200-word response that
would be fine in a chatbot creates a 15-second monologue on a voice call.

### Conciseness
Text allows scanning. Voice requires linear processing. The listener cannot re-read. Every idea
must land in order, without context switching. One idea per turn. One question per turn. No nested
clauses.

### Turn-Taking
In text, the user waits for the response to finish. In voice, the user may interrupt, mishear, or
respond to only part of what was said. Design for partial understanding. Do not pack two decisions
into one turn. Confirm before moving on in high-stakes steps.

---

## 3. Common Anti-Patterns

### Ported chatbot prompts
A text chatbot prompt ported to voice produces robotic, list-heavy, overly long responses.
Symptoms: agent uses bullet points, says "here are three options", recites multi-step instructions
in one turn.

### No guardrails
Agent invents prices, capabilities, or integration availability. Always define explicit knowledge
limits and a safe uncertainty phrase.

### No examples
Without few-shot examples, the agent interprets abstract rules incorrectly in edge cases.
Examples are load-bearing — write at least 3.

### Multiple questions per turn
Asking "What is your name and what plan are you on?" causes the user to answer only the last
question. One question per turn, always.

### Long monologues
Describing a product's 5 features in one turn is a wall of audio. Spread content across turns.
Let the user engage and ask.

### Verbose banlists
A list of 20 words the agent must never say will be ignored. Instead, define what the agent SHOULD
say and give examples. Positive instructions outperform prohibition lists.

### Knowledge in the system prompt
Putting pricing tables, FAQs, or policies in the system prompt creates maintenance debt and bloats
context. Use runtime skills for all domain knowledge.

### Personality in skills
A runtime skill that says "be warm and empathetic when answering these questions" creates split
authority with the system prompt. Skills are KNOWLEDGE only.

---

## 4. Disfluency Design

Disfluency makes a voice agent sound human. Silence sounds robotic. Mechanical disfluency sounds
fake. The goal is calibrated naturalness.

### Vocabulary by persona

Neutral/professional Spanish: "a ver", "bueno", "claro", "entiendo", "mmm".
Warm/conversational: add "mirá", "dale", "por supuesto".
Formal: none — avoid disfluencies or use "entiendo" and "claro" only.

### Frequency
Conversational agent: 2-4 disfluency markers per turn in extended responses.
Efficient/technical agent: 0-1, only at major transitions.
Too many: sounds coached and unnatural.

### Calibration to persona
If the agent is defined as efficient and direct, disfluencies should be rare and functional
(e.g., "claro" before confirming). If the agent is warm and relational, light disfluencies at
the start of turns feel natural.

Self-corrections add humanity: "Es decir... mejor dicho, lo que quiero decir es..." — use sparingly,
only where the natural spoken version would genuinely revise.

---

## 5. Rapport Building

### Personal-share rapport
The agent shares a brief, relevant personal observation to signal it is listening.
Example: "Entiendo, eso pasa seguido en ese rubro."
Keep it brief — one sentence, then return to task.

### Industry rapport
Reference the caller's likely context with light specificity.
Example: "En negocios como el tuyo, lo que más se necesita es velocidad de respuesta."
Do not fabricate industry knowledge you do not have in a skill.

### Banter vs off-topic distinction
Banter: brief, good-natured exchange that acknowledges the human on the other end.
Off-topic: the caller derailing into subjects unrelated to the agent's purpose.

Handle banter with a light touch and a natural bridge back to topic.
Handle off-topic requests with a graceful redirect: "Eso está más allá de lo que puedo resolver en
esta llamada, pero lo que sí puedo hacer es [IN_SCOPE_ALTERNATIVE]."

---

## 6. Tool Integration for Voice

### Filler messages
When a tool call takes more than ~1 second, the agent must say something. Silence sounds like a
dropped call. Define filler text per tool or skill in the registry.
Good filler: "Dejame revisar eso..." / "Un momento..."
Bad filler: "I am currently processing your request" — mechanical, breaks immersion.

### Incremental calls
Do not wait for all data fields to be collected before calling a tool. Call with partial data when
useful. Follow up for missing fields after the call returns. This keeps the conversation moving.

### Handling failures
When a tool fails, do not expose the technical failure. Say what you do know and offer an
alternative action. "No me está llegando esa información en este momento. ¿Querés que lo intentemos
de otra manera?" Retry once silently, then gracefully acknowledge the limitation.

---

## 7. Information Collection

### One field at a time
Ask for one piece of information per turn. "What is your full name and email?" causes the user to
give only one or the other, or to feel interrogated.

### Spell-back for names
For names, email addresses, or anything with high error risk in STT: read back what you captured.
"Confirmame: tu nombre es [NAME], ¿correcto?" Do this before using it in a tool call.

### Batch confirmation
Once multiple fields are collected, confirm them together before any irreversible action.
"Entonces: el martes quince, a las tres de la tarde, para [PARTY]. ¿Todo bien?"

### When to skip read-backs
Skip read-backs for low-stakes fields (city, age range, yes/no). The friction outweighs the
accuracy benefit. Reserve for names, emails, phone numbers, and appointment details.

---

## 8. Emotional Expression Control

Voice agents that react emotionally to every statement sound performative. The user stops trusting
the tone as genuine.

### Frequency rules
Laughter (haha, jaja): at most once per call, only if the user was clearly joking.
Exclamations ("Perfecto!", "Genial!"): at most 2-3 per call. Not after every user statement.
Empathy markers ("Entiendo", "Claro"): freely, but vary the phrasing — avoid repetition.

### Calibration to emotion signal
If the caller sounds frustrated: skip warmth openers, get straight to solving the problem.
If the caller sounds anxious: slow down, confirm each step, reassure before moving forward.
If the caller sounds rushed: be crisp, cut optional steps, deliver value fast.

The agent should not project emotion the caller has not signaled. Do not say "Qué lindo escuchar
eso" if the caller has not said anything positive.
