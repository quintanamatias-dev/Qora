# QORA — Dynamic Skill System

## Overview

The QORA skill system allows AI agents to load specialized knowledge on demand during a conversation, without having that knowledge loaded into the system prompt from the start. This keeps the initial context window lean and allows agents to handle many different topic areas without bloating every call with irrelevant knowledge.

The skill system has two layers:
1. **Registry** (`registry.yaml`) — declares available skills at a high level (name, description, when to use, filler text). This index is injected into the system prompt.
2. **Skill files** (`*.agent-skill.md`) — the full skill content, loaded only when the agent calls the `load_skill` tool.

## File Layout

```text
backend/clients/{client_id}/agents/{agent_slug}/skills/
├── registry.yaml                  ← skill index (injected into system prompt)
└── {skill-name}.agent-skill.md    ← full skill content (loaded on demand)
```

> **Important naming convention**: Runtime agent skill files use `.agent-skill.md` extension, NOT `SKILL.md`. The `SKILL.md` naming is reserved for project developer skills (under `skills/`). This prevents coding-agent skill registries from accidentally loading product-agent skills.

## `registry.yaml` Format

```yaml
skills:
  - name: Qora-info
    description: "Complete information about the Qora platform: identity, capabilities, use cases, and demo limits"
    trigger_hint: "When the user asks about Qora, its capabilities, how it works, pricing, integrations, or the Mariano demo"
    filler_text: "Dejame buscar esa informacion..."

  - name: product-auto
    description: "Detailed information about auto insurance products, coverages, and pricing"
    trigger_hint: "When the lead asks about auto insurance specifics, premium ranges, or coverage details"
    filler_text: "Dejame verificar eso para vos..."
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique skill identifier. Used as the `skill_name` argument to `load_skill`. Must be non-empty. |
| `description` | string | What the skill contains. Shown in the `## Available Skills` index injected into the system prompt. |
| `trigger_hint` | string | When the LLM should call `load_skill`. Shown in the index. |
| `filler_text` | string | A phrase spoken aloud (via TTS) while the skill is being loaded. Must end with punctuation (`.`, `!`, `?`, `…`). In the agent's configured language. |

All four fields are required. A missing field causes the entire registry to fail (empty list returned + warning logged).

## How the Skills Index Is Injected

At call start, `PromptLoader.render_for_agent()` calls:

```python
from app.prompts.skill_loader import load_skill_registry, build_skills_index

entries = await load_skill_registry(client_id, agent_slug)
skills_block = build_skills_index(entries)
# skills_block is appended after the system prompt
```

The resulting block injected into the system prompt looks like:

```markdown
## Available Skills
You have access to specialized knowledge that can be loaded on demand.
Call the `load_skill` tool when the conversation topic matches a skill below.
Only load a skill ONCE per conversation — the knowledge persists after loading.

| Skill | Description | When to use |
|-------|-------------|-------------|
| Qora-info | Complete information about the Qora platform... | When the user asks about Qora... |
```

If there are no skills in `registry.yaml` (empty `skills: []`) or the file doesn't exist, `build_skills_index([])` returns an empty string — no block is injected. The agent simply doesn't have skill-loading capability for that session.

## How `load_skill` Works at Runtime

When the LLM calls `load_skill`:

1. The `tool_dispatcher` receives the call with `skill_name` argument.
2. `handle_load_skill(client_id, agent_slug, skill_name, session_id)` is invoked.
3. The skill file is resolved at: `backend/clients/{client_id}/agents/{agent_slug}/skills/{skill_name}.agent-skill.md`
4. The file is read and returned as the tool result content.
5. The tool result is injected into the GPT context as a `tool` role message.
6. GPT now has the full skill knowledge and uses it to answer the current question.

## Filler Text Behavior (Approach E)

Because loading a skill involves a disk read + a second GPT call, there is a brief pause after the user's question before the agent can respond. The filler text bridges this gap.

**Before loading the skill**, the webhook streams the `filler_text` from the registry entry to the SSE stream. ElevenLabs TTS converts this to audio immediately.

Then, after `load_skill` completes:
- `transition_text` (if configured) is streamed as a brief bridge phrase.
- The agent's actual answer is streamed.

This creates: `[filler] ... [brief pause] ... [actual answer]` — audible and natural.

**Filler text rules**:
- Must be a complete sentence ending with punctuation (`.`, `!`, `?`, `…`).
- Should be natural in the agent's language and voice.
- Should feel like a thoughtful pause, not a robotic delay message.
- Examples: `"Dejame buscar esa información..."`, `"Un momento, verifico eso para vos."`

## Skill Caching Mechanism

ElevenLabs uses a stateless Custom LLM protocol — each turn arrives as a fresh POST request with the full conversation history. There is no persistent WebSocket state between turns.

QORA solves this with an **in-memory session cache** keyed by `elevenlabs_conversation_id`:

```python
# app/voice/session.py
class ConversationState:
    conversation_id: str
    client_id: str
    lead_id: str | None
    session_id: str            # call_sessions.id in SQLite
    turn_count: int
    context: VoiceSessionContext | None   # cached once at initiation
    loaded_skills: dict[str, str]         # skill_name → raw markdown content
```

**Cache behavior**:
1. At call start: `loaded_skills = {}` (empty dict).
2. When `load_skill` is called: skill content is stored in `loaded_skills[skill_name]`.
3. On subsequent turns: the webhook checks `loaded_skills.get(skill_name)`. If cached, it re-injects the skill content directly — **without calling `load_skill` again**. Multiple skills can be loaded and cached per conversation.
4. Loaded skill blocks are assembled into the system message by `_assemble_context_system_content()` as `## Loaded Skill: {name}` sections — the agent sees the skill knowledge in every subsequent turn as if it had just loaded it.

**Why this is needed**: Without caching, the agent would call `load_skill` on every turn (because ElevenLabs sends the full history without the tool result from the previous session). The cache prevents re-loading and ensures the filler is only played once.

**Session expiry**: Sessions expire after 5 minutes of inactivity. The cleanup background task runs every 60 seconds. After expiry, the next call starts fresh (skill must be loaded again).

## Error Handling

- **Skill file not found**: `handle_load_skill` returns `{"error": "Skill '{name}' not found..."}`. The dispatcher prefixes the error with `"Error:"` so the cache guard can detect failed loads and not cache them.
- **Registry YAML malformed**: `load_skill_registry()` logs a warning and returns `[]`. The agent session starts without skill-loading capability.
- **Registry entry missing required fields**: Same as malformed YAML — entire registry returns `[]` with a warning.
- **Failed load attempts are NOT cached**: Only successful loads are stored in `ConversationState`.

## Multi-Tenant Isolation

`load_skill_registry(client_id, agent_slug)` and `handle_load_skill(client_id, agent_slug, ...)` always scope file paths to:

```
backend/clients/{client_id}/agents/{agent_slug}/skills/
```

The `client_id` and `agent_slug` are **always explicit parameters** — never raw filesystem paths passed from outside. This prevents cross-tenant skill leakage.

## How to Add a New Skill to an Agent

1. **Create the skill content file**:

   ```
   backend/clients/{client_id}/agents/{agent_slug}/skills/{skill-name}.agent-skill.md
   ```

   Write the skill content in Markdown. Include everything the agent needs to know about that topic — product details, pricing, FAQs, objection handling.

2. **Register it in `registry.yaml`**:

   ```yaml
   skills:
     - name: {skill-name}
       description: "What this skill covers"
       trigger_hint: "When to load it (match user intent keywords)"
       filler_text: "Natural filler phrase ending with punctuation."
   ```

3. **Verify the agent can load it**: Start a test call and ask about the skill's topic. The agent should say the filler phrase, pause briefly, then answer with the skill's content.

## Example: Qora Demo Agent

The `qora-demo / qora-explainer` agent has one skill configured:

**`registry.yaml`**:
```yaml
skills:
  - name: Qora-info
    description: "Informacion completa sobre la plataforma Qora: identidad, funcionamiento, capacidades, casos de uso y limites del demo"
    trigger_hint: "Cuando el usuario pregunte sobre Qora, sus capacidades, como funciona, precios, integraciones o el demo de Mariano"
    filler_text: "Dejame buscar esa informacion..."
```

**Skill file**: `backend/clients/qora-demo/agents/qora-explainer/skills/Qora-info.agent-skill.md`

When a user asks "How does Qora work?", the agent:
1. Detects the trigger (Qora platform question)
2. Streams `"Dejame buscar esa informacion..."` to TTS
3. Calls `load_skill("Qora-info")`
4. Receives the full `Qora-info.agent-skill.md` content
5. Caches it in `ConversationState`
6. Answers with detailed Qora platform knowledge
