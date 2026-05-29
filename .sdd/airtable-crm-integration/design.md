# Design: Airtable CRM Integration

## Technical Approach

Port+Adapter inside a new `app/integrations/` package. A `CRMPort` ABC defines the write contract; `AirtableAdapter` implements it via `pyairtable`. Config lives in per-client `crm.yaml` files under `backend/clients/{client-id}/`, loaded by a `CRMConfigLoader`. The sync hook fires inside `_run_summarizer` after the savepoint commits — mirrors the `_auto_schedule_if_needed` pattern exactly. SQLite stays authoritative; CRM is a read-only downstream mirror.

## Architecture Decisions

| Decision | Alternatives | Rationale |
|----------|-------------|-----------|
| `app/integrations/` as new top-level package | Nest under `app/leads/` or `app/core/` | CRM is cross-cutting, not lead-specific. Own package isolates deps (`pyairtable`) and allows future HubSpot adapter without touching existing modules. |
| `crm.yaml` per client in filesystem (`backend/clients/{id}/crm.yaml`) | DB column on Client model, global config | Avoids DB migration. Follows existing filesystem convention (`clients/{id}/agents/`). No global config pollution. Clients without the file are silently skipped. |
| Credential env-var reference in `crm.yaml` (key only, e.g. `QUINTANA_AIRTABLE_API_KEY`) | Store encrypted in DB, use Settings | Zero secrets in committed files. `os.environ[key]` at load time — fails fast if missing. Consistent with how `Settings` already reads `.env`. |
| Fire-and-forget async hook (no `await` on caller) | Background task queue (Celery/ARQ) | Qora has no task queue infra. `asyncio.create_task` inside the savepoint callback matches `_auto_schedule_if_needed`. Retry logic lives inside the task. |
| Upsert by `match_field` (default: phone, E.164 normalized) | Create-only, or lookup by Airtable record ID | Idempotent on re-runs or double-fires. Phone is the natural key Quintana uses. E.164 normalization handles format mismatches. |
| `FieldMapping` as Pydantic model validated at load time | Runtime dict, or validate on first sync | Fail-fast: bad config surfaces at startup/first-load, not on the first real call. Type coercion rules are explicit and testable. |

## Data Flow

```
summarizer._run_summarizer()
    │
    ├─ [savepoint commits facts + lead merge]
    │
    └─ _schedule_crm_sync(client_id, lead_id)
           │
           └─ asyncio.create_task(crm_sync_service.sync_lead(...))
                  │
                  ├─ CRMConfigLoader.load(client_id)
                  │     └─ reads backend/clients/{id}/crm.yaml
                  │     └─ resolves env var → API key
                  │     └─ returns CRMConfig (validated Pydantic)
                  │
                  ├─ Lead read from SQLite (authoritative source)
                  │
                  ├─ FieldMapping.map(lead_data) → CRM payload
                  │     └─ coerce types, normalize phone to E.164
                  │
                  └─ CRMPort.upsert_record(payload, match_field)
                        └─ AirtableAdapter: pyairtable upsert
                        └─ retry 3x with exp backoff + jitter
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `app/integrations/__init__.py` | Create | Package init |
| `app/integrations/crm_port.py` | Create | `CRMPort` ABC: `upsert_record()`, `health_check()` |
| `app/integrations/adapters/__init__.py` | Create | Adapters sub-package |
| `app/integrations/adapters/airtable.py` | Create | `AirtableAdapter(CRMPort)` — pyairtable upsert + retry |
| `app/integrations/field_mapping.py` | Create | `FieldMapping`, `CRMFieldDef` Pydantic models + coercion |
| `app/integrations/crm_config.py` | Create | `CRMConfig` Pydantic model, `CRMConfigLoader.load(client_id)` |
| `app/integrations/crm_sync_service.py` | Create | `sync_lead()` orchestrator: load config → read lead → map → upsert |
| `app/summarizer.py` | Modify | Add `_schedule_crm_sync()` after savepoint (mirrors `_auto_schedule_if_needed`) |
| `backend/clients/quintana-seguros/crm.yaml` | Create | Quintana sandbox CRM config |
| `tests/unit/integrations/` | Create | Unit tests: field_mapping, crm_config, adapter (mocked) |
| `tests/integration/integrations/` | Create | Integration: sync_lead with mocked Airtable API |

## Interfaces / Contracts

```python
# crm_port.py
class CRMPort(ABC):
    @abstractmethod
    async def upsert_record(
        self, table_id: str, payload: dict[str, Any],
        match_field: str,
    ) -> str:  # returns external record ID
        ...

# crm_config.py — loaded from crm.yaml
class CRMFieldDef(BaseModel):
    source: str          # Qora lead field name
    target: str          # CRM field name
    type: str = "string" # string | integer | phone | date | boolean
    required: bool = False

class CRMConfig(BaseModel):
    provider: Literal["airtable"]
    base_id: str
    table_id: str
    api_key_env: str     # env var NAME, never the value
    match_field: str     # required explicit matching field, usually "phone"
    field_mappings: list[CRMFieldDef]

# crm.yaml schema (Quintana example)
# provider: airtable
# base_id: appXXXXXXXXXXXXXX
# table_id: tblYYYYYYYYYYYYYY
# api_key_env: QUINTANA_AIRTABLE_API_KEY
# match_field: phone
# field_mappings:
#   - source: name    target: "Nombre"   type: string  required: true
#   - source: phone   target: "Teléfono" type: phone   required: true
#   - source: interest_level  target: "Interés"  type: integer
#   - source: summary_last_call  target: "Resumen"  type: string
#   - source: status  target: "Estado"    type: string
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `FieldMapping.map()` — coercion, phone normalization, missing required fields | Pydantic + pytest, no IO |
| Unit | `CRMConfigLoader.load()` — valid YAML, missing file → None, bad env var → error | tmp_path YAML fixtures, monkeypatch env |
| Unit | `AirtableAdapter.upsert_record()` — success, retry on 429, give up after 3 | `respx` mock or `unittest.mock.AsyncMock` on pyairtable |
| Integration | `sync_lead()` end-to-end — DB lead → config load → mapped upsert | `db_session` fixture + mocked adapter |
| Integration | Summarizer hook — crm_sync fires after savepoint, no-op without crm.yaml | Patch `crm_sync_service.sync_lead`, assert called/not-called |

## Migration / Rollout

No DB migration required. No schema changes to `leads` or `clients` tables.

1. **Phase 1**: Merge code + Quintana `crm.yaml` pointing at Airtable sandbox base
2. **Phase 2**: Set `QUINTANA_AIRTABLE_API_KEY` in staging `.env`
3. **Phase 3**: Run test calls → verify records appear in sandbox base
4. **Phase 4**: Point `crm.yaml` at production base when Quintana approves
5. **Rollback**: Delete/rename `crm.yaml` → sync stops immediately, zero code changes

Future HubSpot: add `app/integrations/adapters/hubspot.py` implementing `CRMPort`. Change `provider: hubspot` in `crm.yaml`. Zero changes outside `app/integrations/adapters/`.

## Open Questions

- [x] None blocking — all design decisions resolved
