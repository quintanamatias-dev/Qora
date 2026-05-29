# Tasks: Airtable CRM Integration

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 900-1,150 |
| 400-line budget risk | High |
| 800-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 config/mapping → PR 2 Airtable/service → PR 3 summarizer + Quintana |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High
800-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Config + field mapping foundation | PR 1 | No runtime hook; tests included |
| 2 | Airtable adapter + sync service | PR 2 | Depends on PR 1; mocked Airtable |
| 3 | Summarizer hook + Quintana sandbox | PR 3 | Depends on PR 2; no live reads |

## Phase 1: Config and Mapping TDD

- [x] 1.1 RED: Add `backend/tests/unit/integrations/test_crm_config.py` for valid `crm.yaml`, missing file skip, missing `match_field`, missing env; run `cd backend && pytest tests/unit/integrations/test_crm_config.py`.
- [x] 1.2 GREEN: Create `backend/app/integrations/crm_config.py` validating `adapter`, `base_id`, `table_id`, `match_field`, `credentials_key`; never persist/log secret values.
- [x] 1.3 RED: Add `backend/tests/unit/integrations/test_field_mapping.py` for string/integer/boolean/date/phone coercion, required fields, arbitrary `field_mappings` / `field_map` alias; run targeted pytest.
- [x] 1.4 GREEN/REFACTOR: Create `backend/app/integrations/field_mapping.py` and `backend/app/integrations/__init__.py`; normalize phone to E.164 and keep mapping pure/no IO.

## Phase 2: Airtable Adapter and Sync Service TDD

- [ ] 2.1 RED: Add `backend/tests/unit/integrations/test_airtable_adapter.py` for upsert success, create/update idempotency contract, 429 retry, 3-failure structured log; run targeted pytest.
- [ ] 2.2 GREEN: Create `backend/app/integrations/crm_port.py`, `backend/app/integrations/adapters/__init__.py`, and `backend/app/integrations/adapters/airtable.py` using mocked `pyairtable` only in tests.
- [ ] 2.3 RED: Add `backend/tests/integration/integrations/test_crm_sync_service.py` for DB lead → config → mapped upsert, missing `crm.yaml` no-op, credential failure isolation; run targeted pytest.
- [ ] 2.4 GREEN/REFACTOR: Create `backend/app/integrations/crm_sync_service.py` with async `sync_lead(client_id, lead_id)`, adapter factory limited to `app/integrations/adapters/`, and no Airtable reads in active call path.

## Phase 3: Summarizer Hook and Quintana Sandbox TDD

- [ ] 3.1 RED: Extend `backend/tests/unit/test_summarizer.py` for `_schedule_crm_sync` called only after savepoint commit and never on savepoint failure; run `cd backend && pytest tests/unit/test_summarizer.py`.
- [ ] 3.2 GREEN: Modify `backend/app/summarizer.py` to fire-and-forget `asyncio.create_task(sync_lead(...))`, swallowing/logging CRM failures without affecting summarizer output.
- [ ] 3.3 RED/GREEN: Add `backend/clients/quintana-seguros/crm.yaml` and config test coverage proving no Quintana-specific logic exists in `backend/app/integrations/`; run integration/unit targeted pytest.

## Phase 4: Verification and Cleanup

- [ ] 4.1 Run `cd backend && pytest tests/unit/integrations tests/integration/integrations tests/unit/test_summarizer.py` and fix only Airtable CRM scope regressions.
- [ ] 4.2 Run `cd backend && pytest` before handoff; confirm no admin UI, bidirectional sync, or live Airtable reads were introduced.
