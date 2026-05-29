# Proposal: Airtable CRM Integration

## Intent

Qora has no CRM integration layer. When a call ends, lead data stays in SQLite only. Quintana Seguros needs call outcomes visible in their Airtable CRM to operate and close deals — this is the blocker for making them a demoable, sellable client. The integration must be generic enough that future clients can point it at HubSpot or any other CRM without touching Qora core.

## Scope

### In Scope
- `CRMPort` abstract interface + `AirtableAdapter` as first implementation
- `FieldMapping` Pydantic model loaded from per-client `crm.yaml`
- Post-summarizer async CRM sync hook (fire-and-forget, mirrors `_auto_schedule_if_needed` pattern)
- Credential resolution from env vars referenced by key in `crm.yaml` — never stored in config
- Quintana Seguros sandbox `crm.yaml` as first real deployment target
- Integration tests with mocked Airtable API
- Structured error logging + retry with exponential backoff (3 attempts); CRM failure NEVER blocks call analysis

### Out of Scope
- Live Airtable reads during calls
- Bidirectional sync (Airtable → Qora)
- Admin UI for CRM config management
- HubSpot / Salesforce adapters (port accommodates them; implementation deferred)
- Multi-CRM per client

## Capabilities

### New Capabilities
- `crm-sync`: Post-call async push of lead data to external CRM via configurable port+adapter
- `crm-field-mapping`: Per-client declarative field mapping from Qora lead fields to CRM field names

### Modified Capabilities
- None

## Approach

Port+Adapter pattern. A `CRMPort` abstract class defines the write contract. `AirtableAdapter` implements it using pyairtable. The sync service loads `crm.yaml` from the client filesystem directory, resolves credentials from env, maps lead fields, and upserts the record (match by `match_field`, typically phone). The hook fires inside `summarizer.py` after the savepoint commits — exactly like the existing scheduler hook. Clients without `crm.yaml` are silently skipped.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/summarizer.py` | Modified | Add `_schedule_crm_sync(client_id, lead_id)` after savepoint |
| `app/integrations/` | New | Port, adapters, field_mapping, sync_service modules |
| `backend/clients/quintana-seguros/crm.yaml` | New | First client CRM config (sandbox) |
| `app/core/config.py` | Modified | Document env var convention for CRM credentials |
| `app/leads/models.py` | Read-only | Source of truth for synced data; no schema change |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Airtable rate limits (5 req/sec free tier) | Med | Exponential backoff + jitter on retry |
| Phone format mismatch on record lookup | Med | Normalize to E.164 before `filterByFormula` |
| Summarizer double-fire → double sync | Low | Upsert is inherently idempotent |
| Airtable field type mismatch | Low | Validate + coerce in FieldMapping at startup |
| CRM outage blocks call analysis | Low | Fire-and-forget; failure logged, not raised |

## Rollback Plan

1. Remove `_schedule_crm_sync` call from `summarizer.py` — CRM sync stops immediately, no data loss (SQLite is authoritative).
2. Delete or rename `backend/clients/{client-id}/crm.yaml` — integration silently skips that client.
3. Revoke Airtable API key from env — all adapter calls fail gracefully with logged error.

No DB migrations to revert. No schema changes to the `leads` table.

## Dependencies

- `pyairtable` (Python Airtable client, Apache-2.0)
- Quintana Seguros Airtable sandbox base + table IDs (provided by client)
- `QUINTANA_AIRTABLE_API_KEY` env var in `.env` / secrets manager

## Success Criteria

- [ ] A completed Quintana call appears in the Airtable sandbox base within 30 seconds of session close
- [ ] A client without `crm.yaml` completes normally with no errors or warnings
- [ ] Simulated Airtable 429 triggers retry with backoff; call analysis result is unaffected
- [ ] Adding a second fake CRM adapter requires zero changes outside `app/integrations/adapters/`
- [ ] No Airtable credentials appear in any committed file
