# Dynamic Skill System

The Qora skill system lets AI agents load specialized knowledge on demand during a conversation, rather than front-loading everything into the system prompt. This keeps the initial context window lean and allows agents to handle many different topic areas without bloating every call with irrelevant knowledge.

---

## TL;DR

- **Skills** are Markdown files with domain knowledge (product details, FAQs, pricing, etc.).
- A **registry** (`registry.yaml`) tells the agent what skills exist and when to load them.
- The agent calls the `load_skill` tool mid-conversation to inject a skill's content into the GPT context.
- Loaded skills are **cached per session** — they're only loaded once per conversation.

---

## How to Add a Skill (Quick Path)

1. **Create the skill content file**:
   ```
   backend/clients/{client_id}/agents/{agent_slug}/skills/{skill-name}.agent-skill.md
   ```
   Write everything the agent needs to know about that topic: product details, pricing, FAQs, objection handling.

2. **Register it in `registry.yaml`**:
   ```yaml
   skills:
     - name: {skill-name}
       description: "What this skill covers"
       trigger_hint: "When to load it (match user intent keywords)"
       filler_text: "Natural filler phrase ending with punctuation."
   ```

3. **Verify**: Start a test call and ask about the skill's topic. The agent should say the filler phrase, pause briefly, then answer with the skill's content.

---

## File Layout

```text
backend/clients/{client_id}/agents/{agent_slug}/skills/
├── registry.yaml                  ← skill index (injected into system prompt)
└── {skill-name}.agent-skill.md    ← full skill content (loaded on demand)
```

> **Naming convention**: Runtime agent skill files use `.agent-skill.md`, **not** `SKILL.md`. The `SKILL.md` naming is reserved for project developer skills (under the root `skills/`). This prevents coding-agent skill registries from accidentally loading product-agent skills.

---

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
| `name` | string | Unique skill identifier — used as the `skill_name` argument to `load_skill`. Must be non-empty. |
| `description` | string | What the skill contains. Shown in the `## Available Skills` index injected into the system prompt. |
| `trigger_hint` | string | When the LLM should call `load_skill`. Shown in the skills index. |
| `filler_text` | string | Phrase spoken aloud via TTS while the skill loads. Must end with punctuation (`.`, `!`, `?`, `…`). In the agent's configured language. |

All four fields are required. A missing field causes the entire registry to fail (empty list returned + warning logged).

---

## Architecture

### How the Skills Index Is Injected

At call start, `PromptLoader.render_for_agent()` builds a skills index from the registry and appends it to the system prompt:

```python
from app.prompts.skill_loader import load_skill_registry, build_skills_index

entries = await load_skill_registry(client_id, agent_slug)
skills_block = build_skills_index(entries)
# skills_block is appended after the system prompt
```

The resulting block looks like:

```markdown
## Available Skills
You have access to specialized knowledge that can be loaded on demand.
Call the `load_skill` tool when the conversation topic matches a skill below.
Only load a skill ONCE per conversation — the knowledge persists after loading.

| Skill | Description | When to use |
|-------|-------------|-------------|
| Qora-info | Complete information about the Qora platform... | When the user asks about Qora... |
```

If no skills are registered (empty `skills: []`) or `registry.yaml` doesn't exist, no block is injected — the agent simply doesn't have skill-loading capability for that session.

### How `load_skill` Works at Runtime

When the LLM calls `load_skill`:

1. The `tool_dispatcher` receives the call with a `skill_name` argument.
2. `handle_load_skill(client_id, agent_slug, skill_name, session_id)` is invoked.
3. The skill file is resolved at: `backend/clients/{client_id}/agents/{agent_slug}/skills/{skill_name}.agent-skill.md`
4. The file is read and returned as the tool result content.
5. The tool result is injected into the GPT context as a `tool` role message.
6. GPT now has the full skill knowledge and uses it to answer.

### Filler Text Behavior

Because loading a skill involves a disk read + a second GPT call, there is a brief pause before the agent can respond. The `filler_text` bridges this gap:

```
[filler text streamed to TTS] → [brief pause] → [skill loads] → [actual answer]
```

**Filler text rules**:
- Must be a complete sentence ending with punctuation (`.`, `!`, `?`, `…`).
- Should feel like a thoughtful pause, not a robotic delay message.
- Examples: `"Dejame buscar esa información..."`, `"Un momento, verifico eso para vos."`

### Skill Caching

ElevenLabs uses a stateless Custom LLM protocol — each turn arrives as a fresh POST with the full conversation history. Without caching, the agent would call `load_skill` on every turn.

Qora solves this with an **in-memory session cache** keyed by `elevenlabs_conversation_id`:

```python
class ConversationState:
    loaded_skills: dict[str, str]   # skill_name → raw markdown content
```

**Cache behavior**:

| Step | What happens |
|------|-------------|
| Call start | `loaded_skills = {}` |
| First `load_skill` call | Skill content stored in `loaded_skills[skill_name]` |
| Subsequent turns | Skill content re-injected from cache — `load_skill` is NOT called again |
| Session expiry (5 min inactivity) | Cache cleared — next call must reload skills |

Loaded skill blocks are assembled into the system message by `_assemble_context_system_content()` as `## Loaded Skill: {name}` sections — the agent sees the knowledge in every subsequent turn as if it had just loaded it.

---

## Error Handling

| Error | Behavior |
|-------|----------|
| Skill file not found | Returns `{"error": "Skill '{name}' not found..."}`. The dispatcher prefixes with `"Error:"` so the cache guard detects failure and skips caching. |
| Registry YAML malformed | `load_skill_registry()` logs a warning and returns `[]`. Session starts without skill-loading capability. |
| Registry entry missing required fields | Same as malformed YAML — entire registry returns `[]` with a warning. |
| Failed load attempts | NOT cached — only successful loads are stored in `ConversationState`. |

---

## Multi-Tenant Isolation

`load_skill_registry(client_id, agent_slug)` and `handle_load_skill(client_id, agent_slug, ...)` always scope file paths to:

```
backend/clients/{client_id}/agents/{agent_slug}/skills/
```

The `client_id` and `agent_slug` are **always explicit parameters** — never raw filesystem paths passed from outside. This prevents cross-tenant skill leakage.

---

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

**Flow when a user asks "How does Qora work?"**:
1. Agent detects the trigger (Qora platform question)
2. Streams `"Dejame buscar esa informacion..."` to TTS
3. Calls `load_skill("Qora-info")`
4. Receives the full `Qora-info.agent-skill.md` content
5. Caches it in `ConversationState`
6. Answers with detailed Qora platform knowledge
