## Exploration: Reusable CRM Integration via Airtable

### Current State

#### Lead data read/write

Qora stores leads in SQLite (`leads` table) with these key fields:

| Category | Fields |
|----------|--------|
| Identity | `id`, `client_id`, `name`, `phone`, `email`, `age` |
| Domain (insurance-specific) | `car_make`, `car_model`, `car_year`, `current_insurance` |
| CRM state | `status` (state machine), `call_count`, `last_called_at`, `do_not_call` |
| Analysis output | `summary_last_call`, `objections_heard`, `interest_level`, `extracted_facts`, `next_action`, `next_action_at` |

- **Read**: `app/leads/service.py` — `get_lead()`, `list_leads_for_client()`, `get_active_profile_facts()`, `get_interest_history()`
- **Write**: `create_lead()`, `transition_lead_status()`, and the summarizer's `_merge_facts_into_lead()`
- **Router**: `app/leads/router.py` — `GET/POST /api/v1/leads`, `PATCH /{id}/status`
- **Supplementary tables**: `lead_profile_facts` (key-value append+supersede), `lead_interest_history` (append-only time series)
- **Seed data**: 5 hardcoded Quintana Seguros test leads in `leads/service.py`

**Important**: The Lead model has insurance-specific columns (`car_make`, `car_model`, etc.) baked into the schema. For a generalized CRM adapter, the fields synced to/from Airtable should be configurable, NOT driven by these hardcoded columns.

#### Post-call analysis/summarizer path (CRM sync trigger point)

The summarizer (`app/summarizer.py`) is the natural trigger for async CRM sync:

1. **Trigger**: `_schedule_summarize(session_id)` fires after session close (`calls/service.py:626`), ElevenLabs webhook reconciliation (`:526`), or stale session sweep
2. **Execution**: `asyncio.create_task` → independent DB session → `generate_summary_and_facts()`
3. **Pipeline end** (inside single savepoint):
   - Persists analysis to `CallSession` + `CallAnalysis`
   - Merges facts into `Lead` (objections, interest_level, do_not_call, etc.)
   - Writes `LeadProfileFact` rows
   - Writes `LeadInterestHistory` row
   - Calls `_auto_schedule_if_needed()` (scheduler)
4. **Hook point**: After the savepoint commits successfully, a CRM sync task can fire. The pattern already exists with `_auto_schedule_if_needed()`.

#### Client/agent config structure

- **Client model** (`app/tenants/models.py`): Flat columns on `clients` table — scheduler config, next_action engine config, analysis_language, `extraction_config` (JSON Text, nullable)
- **Agent model**: Per-agent tool config via `tool_config` JSON column
- **Filesystem**: `backend/clients/{client-id}/agents/{agent-slug}/` with `system-prompt.md` and `skills/`
- **No existing integration/adapter pattern**: There is no CRM port, no adapter interface, no integration module anywhere in the codebase. This is entirely new.

### Affected Areas

| File/Area | Why |
|-----------|-----|
| `app/summarizer.py` | Add CRM sync hook after savepoint commit |
| `app/tenants/models.py` | Add CRM provider config to Client (or new table) |
| `app/leads/models.py` | Lead is source-of-truth for data synced to CRM |
| `app/core/config.py` | Airtable API key env var (though per-client creds preferred) |
| NEW `app/integrations/` | New module: port, adapters, field mapping, sync service |
| `backend/clients/quintana-seguros/` | Per-client CRM config file (field mapping, base/table IDs) |

### Approaches

#### 1. Port+Adapter with per-client config file — Recommended

A `CRMPort` abstract interface with `AirtableAdapter` as first implementation. Per-client CRM config lives in the filesystem alongside the agent config.

```
app/integrations/
├── __init__.py
├── ports.py            # CRMPort abstract class
├── field_mapping.py    # FieldMapping model + resolver
├── sync_service.py     # Post-call CRM sync orchestrator
└── adapters/
    ├── __init__.py
    └── airtable.py     # AirtableAdapter implements CRMPort

backend/clients/{client-id}/
├── crm.yaml            # Per-client CRM provider config
└── agents/...
```

- Pros: Clean separation, testable via mock port, easy to add HubSpot later, config lives with client files
- Cons: More files upfront, need to define field mapping schema
- Effort: Medium

#### 2. Flat columns on Client model

Add `crm_provider`, `crm_api_key`, `crm_base_id`, `crm_table_id`, `crm_field_mapping` as columns on the existing Client table.

- Pros: Simple, no new tables, works immediately
- Cons: Pollutes Client model (already 30+ columns), field_mapping as JSON blob is fragile, adding HubSpot means more columns, no clean separation
- Effort: Low

#### 3. Separate CRM integration table + config

New `client_crm_configs` table with FK to `clients`, stores provider, credentials reference, field mapping JSON.

- Pros: Clean DB separation, multiple CRM providers per client theoretically possible
- Cons: Still no adapter abstraction, credentials in DB is risky, migration needed
- Effort: Medium

### Recommendation

**Approach 1 (Port+Adapter with per-client config file)** is the clear winner.

Rationale:
- Qora already uses the filesystem pattern for per-client config (`system-prompt.md`, `skills/`, `registry.yaml`). CRM config is a natural extension.
- A `CRMPort` interface makes it trivial to add HubSpot/Salesforce later without touching the sync orchestrator.
- Credentials should live in env vars or a secrets manager (not in filesystem config files — the config file references a credential key, the actual API key lives in `.env` or a secrets store).
- Field mapping as a typed Pydantic model gives validation at startup, not runtime errors.

### Architecture Detail

#### CRMPort interface

```python
class CRMPort(ABC):
    """Abstract port for CRM write operations."""
    
    @abstractmethod
    async def upsert_lead(self, lead_data: dict, field_mapping: FieldMapping) -> CRMSyncResult: ...
    
    @abstractmethod
    async def find_record_by_field(self, field_name: str, value: str) -> str | None: ...
```

#### FieldMapping model

```yaml
# backend/clients/quintana-seguros/crm.yaml
provider: airtable
credentials_key: QUINTANA_AIRTABLE_API_KEY  # resolved from env
base_id: appXXXXXXXXXXXXXX
table_id: tblXXXXXXXXXXXXXX
match_field: phone  # Qora field used to find existing Airtable record
field_mapping:
  # qora_field: airtable_field_name
  name: "Nombre"
  phone: "Teléfono"
  email: "Email"
  status: "Estado"
  interest_level: "Nivel de Interés"
  summary_last_call: "Resumen Última Llamada"
  next_action: "Próxima Acción"
  # Client can add any Airtable field they want mapped
```

#### Sync trigger (post-summarizer hook)

```python
# In summarizer.py, after the savepoint commits:
if cs.lead_id and cs.client_id:
    await _auto_schedule_if_needed(db, cs, facts)
    # NEW: fire-and-forget CRM sync
    _schedule_crm_sync(cs.client_id, cs.lead_id)
```

The sync service:
1. Loads `crm.yaml` for the client
2. If no CRM config → skip (most clients won't have CRM initially)
3. Reads current Lead data from SQLite
4. Maps Qora fields → CRM fields using the field mapping
5. Finds or creates the record in Airtable (match by `match_field`, typically phone)
6. Upserts the mapped data
7. Logs result (success/failure/skipped)

#### What should be configurable vs hardcoded

| Configurable (per-client) | Hardcoded / Convention |
|--------------------------|----------------------|
| CRM provider (`airtable`, future `hubspot`) | Port interface shape |
| API credentials reference | Credential resolution mechanism |
| Base ID, table ID | Retry policy (3 retries, exponential backoff) |
| Field mapping (Qora → CRM field names) | Sync trigger point (post-summarizer) |
| Match field for upsert | Fire-and-forget async pattern |
| Which Qora fields to sync | Error logging structure |
| Sync enabled/disabled | — |

### Risks

1. **Airtable rate limits**: Free tier = 5 req/sec, Pro = 50 req/sec. A burst of completed calls could hit limits. Mitigation: exponential backoff + queue (or simple retry with jitter). For MVP, retry 3x is sufficient.

2. **Record matching / deduplication**: Finding the right Airtable record to update requires a reliable match field. Phone number is the natural key but format differences ("+54 11..." vs "011...") can cause mismatches. Mitigation: normalize phone format before matching. Airtable `filterByFormula` supports string matching.

3. **Airtable API key security**: API keys should NOT live in `crm.yaml`. The config references a key name, the actual value lives in `.env` or a secrets manager. For MVP, a single env var per client (`QUINTANA_AIRTABLE_API_KEY`) works.

4. **Idempotency**: If the summarizer runs twice for the same session (webhook retry), the CRM sync fires twice. Since we use upsert (find-by-phone then update), this is inherently idempotent — same data written twice = no harm.

5. **Airtable field type mismatches**: Airtable has typed fields. Writing a string to a number field fails silently or errors. Mitigation: validate field types in the mapping config and coerce before sending.

6. **Partial sync failure**: If Airtable is down, the call analysis still succeeds (SQLite is authoritative). The CRM sync failure is logged but does NOT block or roll back the analysis. This matches the existing pattern with `_auto_schedule_if_needed()`.

7. **Sandbox testing**: Use a duplicated Airtable base for testing. The `crm.yaml` for dev/staging points to the sandbox base; production points to the real base. No code change needed — just different config.

8. **Lead model domain coupling**: The current Lead model has insurance-specific columns (`car_make`, etc.). The field mapping should work with ANY Lead field (including `extracted_facts` JSON subfields and `LeadProfileFact` rows), not just the hardcoded columns. The sync service reads the Lead, flattens relevant data, and maps via config.

### What the SDD Proposal Should Include

1. **CRMPort** abstract interface + **AirtableAdapter** implementation
2. **FieldMapping** Pydantic model loaded from `crm.yaml`
3. **CRM sync service** triggered post-summarizer (fire-and-forget, like scheduler)
4. **Per-client config** at `backend/clients/{client-id}/crm.yaml`
5. **Credential resolution** from env vars (referenced by key in config)
6. **Quintana Seguros sandbox config** as first real client
7. **Integration tests** with mocked Airtable API
8. **Error handling**: retry with backoff, graceful failure, structured logging

Out of scope for first iteration:
- Live Airtable reads during calls (can be added later if needed)
- Bidirectional sync (Airtable → Qora)
- Admin UI for CRM config management
- HubSpot/Salesforce adapters (but the port interface should accommodate them)

### Ready for Proposal

Yes. The codebase is well-understood, the architecture pattern is clear, and there are no blockers. The proposal should define the port interface, the config schema, the sync trigger hook, and the Quintana sandbox as first deployment target.
