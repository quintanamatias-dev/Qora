# Design: QORA Phase 1 — Multi-client Foundation

## Technical Approach

Introduce a filesystem-based prompt system (`backend/clients/{id}/prompt.md` + `knowledge.md`), a `PromptLoader` class with fallback to the existing hardcoded template, a new `/api/v1/clients` CRUD router (aliasing `/tenants` for backward compat), a Click CLI for client onboarding, and a client selector in the web demo. Remove `default_client_id` — make `client_id` mandatory everywhere.

## Architecture Decisions

| # | Decision | Alternatives | Rationale |
|---|----------|-------------|-----------|
| 1 | `{{var}}` double-brace syntax in prompt.md, rendered via regex `re.sub` | Jinja2 / Python `str.format` | Jinja2 is a dep we don't need; `str.format` breaks on `{` in prompt text. Custom regex is 10 lines, safe, zero deps. |
| 2 | New `backend/app/clients/router.py` under `/api/v1/clients` — keep `/api/v1/tenants/{id}` as a one-line alias | Rename tenants router in-place | Zero breaking change for anything hitting `/tenants`. Old router stays as-is (read-only), new router adds full CRUD. |
| 3 | `PromptLoader` as stateless module functions (not a class) | Singleton class with cache | No state to manage — functions are simpler, testable, match existing `render_system_prompt()` pattern. Caching adds complexity for no gain (prompts are small files, read once per call). |
| 4 | Token estimation: `len(text.split()) * 1.3` | tiktoken / character count | tiktoken adds 20MB dep. Character count is too inaccurate. Word × 1.3 is ~90% accurate for Spanish text — good enough for a 2000-token cap. |
| 5 | CLI as `backend/qora_cli.py` using Click | argparse / Typer / `__main__` package | Click is battle-tested, already in common use. Single top-level script avoids package import issues with async DB. |
| 6 | Sanitize variable values by escaping `{{` and `}}` before injection | Whitelist characters / strip all special chars | Escaping preserves legitimate content (e.g., names with accents) while preventing template injection. Only the delimiter is dangerous. |

## Data Flow

```
                          index.html
                              │
            GET /api/v1/clients → client dropdown
            GET /api/v1/leads?client_id=X → lead dropdown
                              │
        ┌─── dynamic_variables { client_id: X } ───┐
        │                                           │
   ElevenLabs WS                              ElevenLabs WS
        │                                           │
   POST /voice/initiation                    POST /voice/custom-llm
   (client_id from query/body)               (client_id from extra_body)
        │                                           │
        └──────────────┐   ┌────────────────────────┘
                       ▼   ▼
                   PromptLoader
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
  clients/{id}/    clients/{id}/   JAUMPABLO_PROMPT_
  prompt.md        knowledge.md    TEMPLATE (fallback)
          │            │
          └──→ rendered system prompt ←──┘
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/clients/quintana-seguros/prompt.md` | Create | Migrate `JAUMPABLO_PROMPT_TEMPLATE` to markdown with `{{var}}` syntax |
| `backend/clients/quintana-seguros/knowledge.md` | Create | Insurance-specific FAQs, pricing tiers placeholder |
| `backend/clients/demo-inmobiliaria/prompt.md` | Create | Real-estate agent prompt (Spanish, voseo, property focus) |
| `backend/clients/demo-inmobiliaria/knowledge.md` | Create | Property listings, neighborhood info |
| `backend/app/prompts/loader.py` | Create | `load_prompt()`, `load_knowledge()`, `render_client_prompt()` — the core of Phase 1 |
| `backend/app/prompts/insurance_agent.py` | Modify | Update `render_system_prompt()` to call `loader.render_client_prompt()` internally (preserves API, adds filesystem check + knowledge injection) |
| `backend/app/clients/__init__.py` | Create | New package |
| `backend/app/clients/router.py` | Create | Full CRUD: POST/GET/GET-list/PATCH/DELETE under `/api/v1/clients` |
| `backend/app/clients/schemas.py` | Create | Pydantic request/response models with slug validation (`^[a-z0-9-]+$`) |
| `backend/app/tenants/router.py` | Modify | Keep as backward-compat alias — no functional changes |
| `backend/app/tenants/service.py` | Modify | Add `list_active_clients()`, `soft_delete_client()` |
| `backend/app/voice/webhook.py` | Modify | Remove `default_client_id` fallback (lines 348-358) → return 422 if missing |
| `backend/app/core/config.py` | Modify | Remove `default_client_id`, `default_broker_name`, `default_agent_name` |
| `backend/app/static/index.html` | Modify | Add client `<select>`, dynamic lead reload, send `client_id` in `dynamic_variables` |
| `backend/app/main.py` | Modify | Register new `clients` router, add `seed_demo_inmobiliaria` to startup |
| `backend/qora_cli.py` | Create | Click CLI: `create-client`, `list-clients` commands |

## Interfaces / Contracts

### PromptLoader (backend/app/prompts/loader.py)

```python
CLIENTS_DIR = Path(__file__).resolve().parents[2] / "clients"
MAX_KNOWLEDGE_TOKENS = 2000

def load_prompt_template(client_id: str) -> str | None:
    """Read clients/{client_id}/prompt.md. Returns None if missing."""

def load_knowledge(client_id: str) -> str | None:
    """Read clients/{client_id}/knowledge.md. Returns None if missing."""

def estimate_tokens(text: str) -> int:
    """Word count × 1.3 approximation."""

def sanitize_value(value: str) -> str:
    """Escape {{ and }} in variable values to prevent injection."""

def render_client_prompt(
    client_id: str,
    variables: dict[str, str],
    *,
    fallback_template: str | None = None,
) -> str:
    """Load prompt template → substitute {{vars}} → append knowledge."""
```

### Client CRUD Schemas (backend/app/clients/schemas.py)

```python
class CreateClientRequest(BaseModel):
    id: str  # validator: ^[a-z0-9-]+$
    name: str
    broker_name: str
    agent_name: str = "Agente"
    voice_id: str

class UpdateClientRequest(BaseModel):
    name: str | None = None
    broker_name: str | None = None
    agent_name: str | None = None
    voice_id: str | None = None
    # id is NOT updatable

class ClientResponse(BaseModel):
    id: str
    name: str
    broker_name: str
    agent_name: str
    voice_id: str
    is_active: bool
    created_at: str
```

### Client CRUD Endpoints

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/api/v1/clients` | 201 / 409 / 422 | Create client (slug validation) |
| `GET` | `/api/v1/clients` | 200 | List active clients |
| `GET` | `/api/v1/clients/{id}` | 200 / 404 | Get single client |
| `PATCH` | `/api/v1/clients/{id}` | 200 / 404 | Partial update |
| `DELETE` | `/api/v1/clients/{id}` | 200 / 404 | Soft delete (is_active=false) |

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `loader.py` — template rendering, sanitization, truncation | pytest with temp files, no DB |
| Unit | `schemas.py` — slug validation, partial update | Pydantic model tests |
| Integration | Client CRUD API — all 5 endpoints | httpx AsyncClient + test DB |
| Integration | `render_system_prompt()` — fallback chain, knowledge injection | Test with/without prompt.md on disk |
| Integration | Webhook 422 — missing client_id | Override settings, assert 422 |
| E2E | Web demo client selector → lead dropdown → dynamic_variables | Manual test (documented steps) |

## Migration Plan (Phase 0 → Phase 1)

**Order of operations** (each step is independently deployable):

1. **Add `loader.py`** — pure addition, nothing calls it yet. Zero risk.
2. **Create `backend/clients/quintana-seguros/prompt.md`** — copy from `JAUMPABLO_PROMPT_TEMPLATE`, convert `{var}` → `{{var}}`. Fallback still active.
3. **Wire `render_system_prompt()` to use loader** — if file exists, use it; else fall back. Quintana behavior identical.
4. **Add client CRUD router** — new endpoints, no existing changes.
5. **Add web demo client selector** — `client_id` now sent explicitly.
6. **Remove `default_client_id`** — webhook returns 422 if missing. Safe because step 5 already sends it.
7. **Seed `demo-inmobiliaria`** — additive data, no schema changes.
8. **Add CLI** — standalone script, no coupling.

**Rollback**: Delete `backend/clients/` dir → loader falls back to hardcoded. Revert webhook.py 422 → restore fallback. One commit each direction.

## Open Questions

- [ ] None — all decisions resolved in proposal. Ready for tasks.
