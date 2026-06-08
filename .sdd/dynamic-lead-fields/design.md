# Design: Dynamic Lead Fields

## Technical Approach

Add `LeadCustomField` model (key-value, type-enforced at write) alongside existing `Lead`. A thin CRUD service (`lead_custom_fields_service.py`) handles all custom field I/O. Every consumer that reads/writes the 6 hardcoded columns migrates to this service incrementally — old columns stay in DB but become dead reads/writes by WU-7.

CRM config (`crm.yaml`) gains `custom_fields` definitions and `quote_ready_fields`. The `api_key_env` field becomes `api_key` with smart resolver (env var name vs literal).

## Architecture Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Custom field storage | Separate `lead_custom_fields` table | JSON column on Lead | Queryable, indexable, typed; follows existing `LeadProfileFact` pattern |
| Type enforcement | Write-time coercion in service layer | Read-time coercion | Single source of truth; avoids inconsistent reads. Existing `_extract_int()` pattern in data_corrections validates approach |
| API key resolution | `api_key` field + `resolve_api_key()` heuristic (ALL_CAPS_UNDERSCORES → env lookup, else literal) | Separate `api_key` / `api_key_env` fields | One field, backward-compat; regex `^[A-Z][A-Z0-9_]+$` distinguishes env var names from literal keys |
| Quote-ready config | `quote_ready_fields` list in crm.yaml | Hardcoded per-client in Python | Client-configurable; absent list → never "quoted" (safe default) |
| Tool schema generation | Build from `custom_fields` definitions in crm.yaml at agent load time | Keep `_QUINTANA_TOOL_CONFIG` constant | Unblocks multi-tenant; schema always matches field config |
| register_interest | Delete entirely | Keep as deprecated | capture_data fully replaces it; dual-run proved stable |

## Data Flow

```
crm.yaml (custom_fields defs)
    │
    ├──→ capture_data tool schema (dynamic at agent load)
    ├──→ is_quote_ready() (reads quote_ready_fields)
    └──→ CORRECTABLE_FIELDS registry (dynamic keys)

Lead write paths:
  capture_data ──→ lead_custom_fields_service.upsert()
  crm_import   ──→ lead_custom_fields_service.upsert()
  data_corrections ──→ lead_custom_fields_service.upsert()

Lead read paths:
  _build_variables() ──→ lead_custom_fields_service.get_all(lead_id, client_id) → merged dict
  _lead_to_dict()    ──→ same get_all → merged into flat dict
  is_quote_ready()   ──→ same get_all → check quote_ready_fields present
  current_lead_data  ──→ same get_all → merged snapshot
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/leads/models.py` | Modify | Add `LeadCustomField` model; deprecate 6 columns (leave in DB) |
| `backend/app/leads/lead_custom_fields_service.py` | Create | CRUD: get_all, get_one, upsert, delete, batch_get |
| `backend/app/leads/service.py` | Modify | Remove car_* params from `create_lead()`; update seed data |
| `backend/app/leads/router.py` | Modify | Remove car_* from `CreateLeadRequest`; add `custom_fields` to `_lead_to_dict` |
| `backend/app/integrations/crm_config.py` | Modify | `api_key_env` → `api_key`; add `custom_fields`, `quote_ready_fields` to `CRMConfig` |
| `backend/clients/quintana-seguros/crm.yaml` | Modify | Add `custom_fields`, `quote_ready_fields`; rename `api_key_env` → `api_key` |
| `backend/app/integrations/crm_sync_service.py` | Modify | `_lead_to_dict()` merges custom fields from DB |
| `backend/app/integrations/crm_import_service.py` | Modify | Write custom field values to `lead_custom_fields` instead of Lead columns |
| `backend/app/prompts/loader.py` | Modify | `_build_variables()` loads custom fields, merges into template vars |
| `backend/app/summarizer.py` | Modify | `is_quote_ready()` reads config + custom fields; `current_lead_data` merged |
| `backend/app/analysis/universal/data_corrections.py` | Modify | `CORRECTABLE_FIELDS` write path → custom fields service; add `storage` attr |
| `backend/app/tenants/service.py` | Modify | `_QUINTANA_TOOL_CONFIG` → dynamic from crm.yaml `custom_fields` |
| `backend/app/tools/register_interest.py` | Delete | Legacy tool removed |
| `backend/app/tools/get_lead_details.py` | Modify | Read custom_fields from service |
| `backend/app/main.py` | Modify | Startup migration: CREATE TABLE + data copy + marker |
| `frontend/src/api/types.ts` | Modify | Remove 4 fields; add `custom_fields?: Record<string, string>` |
| `frontend/tests/mocks/handlers.ts` + 6 test files | Modify | Fixture updates |

## Interfaces / Contracts

```python
# --- NEW: backend/app/leads/models.py ---
class LeadCustomField(Base):
    __tablename__ = "lead_custom_fields"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    lead_id: Mapped[str] = mapped_column(String, ForeignKey("leads.id"), nullable=False)
    client_id: Mapped[str] = mapped_column(String, ForeignKey("clients.id"), nullable=False)
    field_key: Mapped[str] = mapped_column(String, nullable=False)
    field_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_type: Mapped[str] = mapped_column(String, nullable=False, default="string")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        Index("ix_lcf_lead_client", "lead_id", "client_id"),
        Index("ix_lcf_lead_key", "lead_id", "field_key", unique=True),
    )

# --- NEW: backend/app/leads/lead_custom_fields_service.py ---
VALID_FIELD_TYPES = {"string", "integer", "boolean", "date", "phone"}

def coerce_value(value: Any, field_type: str) -> str:
    """Validate and coerce value to canonical string representation.
    Raises ValueError on invalid type/value."""

async def get_all(db: AsyncSession, lead_id: str, client_id: str) -> dict[str, str]:
    """Return {field_key: field_value} for all custom fields of a lead."""

async def get_one(db: AsyncSession, lead_id: str, field_key: str) -> str | None:
    """Return single field value or None."""

async def upsert(db: AsyncSession, *, lead_id: str, client_id: str,
                 field_key: str, field_value: Any, field_type: str = "string") -> LeadCustomField:
    """Insert or update a custom field. Coerces value at write time."""

async def upsert_many(db: AsyncSession, *, lead_id: str, client_id: str,
                      fields: dict[str, Any], field_types: dict[str, str] | None = None) -> int:
    """Batch upsert. Returns count of upserted fields."""

async def delete(db: AsyncSession, lead_id: str, field_key: str) -> bool:
    """Delete a custom field. Returns True if existed."""

async def batch_get(db: AsyncSession, lead_ids: list[str], client_id: str) -> dict[str, dict[str, str]]:
    """Batch load: {lead_id: {field_key: field_value}}. Single query with IN clause."""

# --- MODIFIED: crm_config.py / CRMConfig ---
class CustomFieldDef(BaseModel):
    field_key: str
    field_type: Literal["string", "integer", "boolean", "date", "phone"] = "string"
    label: str  # human-readable for tool description
    required: bool = False

class CRMConfig(BaseModel):
    api_key: str  # renamed from api_key_env; resolver handles both patterns
    custom_fields: list[CustomFieldDef] = []
    quote_ready_fields: list[str] = []  # field_keys required for "quoted" status
    # ... existing fields unchanged ...

    def resolve_api_key(self) -> str:
        """If api_key matches ^[A-Z][A-Z0-9_]+$ → os.environ lookup. Else → literal."""

# --- MODIFIED: summarizer.py ---
def is_quote_ready(custom_fields: dict[str, str], quote_ready_fields: list[str]) -> bool:
    """Pure function: all quote_ready_fields present and truthy in custom_fields dict."""
    return bool(quote_ready_fields) and all(custom_fields.get(f) for f in quote_ready_fields)

# --- MODIFIED: prompts/loader.py ---
async def _build_variables(self, client, lead, call_count, db=None) -> dict[str, str]:
    """Now loads custom fields via lead_custom_fields_service.get_all()
    and merges them into the template variables dict.
    Template {{car_make}} resolves from custom_fields['car_make']."""
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `LeadCustomField` model, `coerce_value()`, `is_quote_ready()` new signature, `resolve_api_key()` heuristic | pytest, no DB |
| Unit | `lead_custom_fields_service` CRUD (get_all, upsert, upsert_many, batch_get) | async SQLite in-memory |
| Unit | `_lead_to_dict()` with custom fields, `_build_variables()` with custom fields | mock service |
| Integration | CRM import writes to custom_fields, CRM export reads them | existing test patterns |
| Integration | capture_data → custom_fields (not just LeadProfileFact) | existing capture_data test pattern |
| Integration | Startup migration: table creation + data copy idempotency | fresh + seeded DB |

## Migration / Rollout

**3-phase startup migration in `_apply_schema_compat()`:**

1. **Phase A** — `CREATE TABLE IF NOT EXISTS lead_custom_fields (...)`. Idempotent.
2. **Phase B** — Check migration marker (row in `lead_custom_fields` with `field_key='_migration_v1'` for a sentinel lead). If absent: for each lead with non-null car_make/car_model/car_year/current_insurance/age/zona, INSERT rows. Write marker when done.
3. Old columns stay. No DROP. Code stops reading them progressively across WU-2 through WU-7.

**Rollback**: Revert code → reads fall back to Lead columns (still populated during dual-write WUs).

## Open Questions

- [x] Field type enforcement at write vs read time → **Write time** (decided)
- [x] register_interest removal → **Yes, delete** (decided)
- [ ] Should `capture_data` write to BOTH `LeadProfileFact` (captured: namespace) AND `lead_custom_fields`? Or migrate away from captured: facts entirely? **Recommendation**: write to `lead_custom_fields` only; captured: namespace becomes redundant for custom field data.
