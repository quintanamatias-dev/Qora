# Exploration: Phone Number Normalization

## Status

- **Phase:** explore
- **Change:** `phone-number-normalization`
- **Scope:** read-only product and code investigation; no implementation, tests, provider calls, git operations, or policy decision was made.
- **Motivation:** a recent corrected-format outbound call succeeded. This is evidence that contact-data normalization is worth investigating; it does **not** indicate a dialer defect or justify new dialing behavior.

## Current Contract and Storage

`Lead.phone` is the operational contact number. It is a required unconstrained `String` on `leads`: it has no canonical-format check, validity state, country metadata, raw-value shadow, uniqueness constraint, or phone index. The same stored value is exposed in admin/demo/tool payloads, included in outbound dynamic variables, used as the outbound destination, and used by CRM import deduplication.

The canonical outbound specification deliberately validates at trigger time: a non-E.164 value returns 422 before a `CallSession` is created or a provider is called. This is a cost and safety guard, but it happens after data was already allowed into storage.

## Phone Ingress Map

| Ingress | Current behavior | Normalization/validation gap |
|---|---|---|
| Admin/API lead creation | `POST /api/v1/leads` accepts required `name` and `phone`, then `create_lead()` persists the string unchanged. | No parsing, country resolution, or E.164 validation before storage. |
| CRM pull import | `POST /api/v1/clients/{client_id}/crm/import` reverse-maps Airtable fields. The import skips only a missing phone, deduplicates by exact `(client_id, phone)` text, creates with the imported text unchanged, and intentionally never updates the matched lead phone. | Formatting variants become separate leads; a local/national number can be persisted; no canonical identity key exists. |
| Post-call data correction | The LLM correction pipeline permits a phone with at least ten digits after stripping non-digits and, with the current disabled confidence gate, the summarizer can write it directly to `Lead.phone`. | This is a second write ingress with looser rules than outbound E.164 validation and can reintroduce noncanonical data after initial import. |
| Seed/demo setup | Seed helpers create `Lead` rows directly or through `create_lead()`. | Test/demo data follows no common canonicalization seam. Treat as fixture maintenance, not customer-data migration. |
| CSV/manual import UI | The frontend Import page says CSV import is coming soon; no CSV implementation was found. | No active ingress to change. |
| Manual browser UI | The lead list has Call Now only; no create/edit-phone form or PATCH-phone endpoint was found. | Current 422 copy tells an operator to update a phone, but the product has no in-app correction route. |

## CRM Sync Boundary

CRM sync is an **egress**, not an ingress: it reads `Lead.phone`, maps it through `FieldMapper`, and writes an external CRM payload. `FieldMapper.normalize_phone_e164()` removes spaces, dashes, parentheses, and dots only when the value already has a `+` E.164 shape. It does not change Qora storage. Invalid phone mapping aborts that sync attempt after logging, while the core call-analysis path continues.

The pull and push paths therefore disagree today: imported phones are passed through untouched, while exported phone-typed fields are structurally cleaned or rejected.

## Outbound Boundaries

| Boundary | Observed behavior |
|---|---|
| Manual Call Now UI | The table always exposes Call Now, requires explicit real-cost confirmation, then displays the API outcome. A 422 is rendered as an E.164/update-and-retry error. |
| Manual outbound API | `POST /api/v1/clients/{client_id}/leads/{lead_id}/call` checks the feature flag, tenant ownership, cooldown, and E.164 before it delegates. Invalid input produces 422 before a call session or provider request. |
| Shared dial service | `dial_outbound_call()` independently validates the same stored number before it commits its pre-dial `CallSession` and before it invokes ElevenLabs. This is the authoritative defense-in-depth boundary. |
| Scheduled auto-dialer | `run_scheduler_cycle()` claims due rows and calls the same `dial_outbound_call(..., scheduled_call=sc)` service. An invalid stored phone therefore fails before provider contact and the claimed scheduled row is marked failed. |
| Dynamic variables / probe | After the shared dial guard passes, the stored number is included in the provider request, dynamic variables, and post-dial probe context. These are consumers, not alternate validation points. |

Normalization must not weaken the existing pre-provider guard. This change should improve stored data before either manual or scheduled dialing reaches that guard; it is not a change to dialing, feature flags, scheduler claims, retry semantics, or provider integrations.

## Existing Normalization, Validation, Dependencies, and Tests

### Three incompatible rules

1. `app.integrations.field_mapping.normalize_phone_e164()` strips a narrow set of display separators and accepts a structural regex with 2–15 digits after `+`.
2. `app.outbound.phone.validate_e164()` accepts a stricter structural regex with 7–15 digits after `+`; when the optional `phonenumbers` import is available it also calls its parser and `is_valid_number()`.
3. `app.analysis.universal.data_corrections._validate_phone()` accepts any value containing at least ten digits after punctuation stripping.

These are materially different acceptance policies. Neither structural regex establishes that an international number is assigned or dialable, and the correction validator does not require an international prefix.

`phonenumbers` is mentioned as preferred in the outbound module but is not declared in `backend/pyproject.toml`. Its availability in a deployed environment is therefore not a supported dependency contract. No other phone library was found.

### Relevant test coverage

- `backend/tests/unit/outbound/test_phone_validator.py` covers the outbound validator's valid/international, local-format, short, empty, and malformed cases.
- `backend/tests/unit/outbound/test_outbound_router.py` and `backend/tests/unit/outbound/test_dial_service.py` assert invalid phone rejection before dialing.
- `backend/tests/unit/integrations/test_field_mapping.py` covers separator stripping, structurally E.164 input, and rejection of local input for CRM payloads.
- `backend/tests/unit/integrations/test_crm_import.py` covers missing-phone skip and exact-phone create/update behavior, but not normalization-before-deduplication or invalid imported-number treatment.
- `backend/tests/unit/leads/test_router.py` covers successful API lead creation, but not validation or a correction workflow.
- `backend/tests/test_data_corrections.py` documents the ten-digit correction acceptance rule.

No tests were run during this exploration.

## Argentina-Specific Ambiguity (No Policy Assumed)

Argentina cannot be safely normalized from punctuation removal alone. Domestic notation may contain a trunk prefix (`0`); mobiles commonly contain a domestic `15` marker; geographic area lengths vary. In international E.164 representation, an Argentine mobile conventionally uses the mobile `9` after country code `54` and omits domestic `0` and `15`, while a landline uses country code plus area and subscriber number without that mobile marker.

Consequences:

- A national-format string is not self-describing without a chosen default/explicit country context.
- Removing `0` or `15` mechanically can corrupt a landline or misclassify a mobile when the source format is incomplete or ambiguous.
- A parsing library can apply Argentina numbering rules when given an explicit region, but it cannot establish the business intent behind an ambiguous value or infer a tenant's default country safely.
- A valid Argentine mobile and a valid Argentine landline need different canonical E.164 outcomes; accepting both is a product decision, not merely a regex change.

The investigation does not choose a country default, assume Argentina-only tenants, or require mobile-only dialing.

## Product Decisions Required Before Proposal

1. **Country resolution:** Must every number arrive with an explicit country code, may a tenant have an explicit default country, or may an operator select a country per entry/import? If defaults are allowed, where are they configured and how are multi-country imports handled?
2. **Argentina number class:** Are mobile and landline both eligible for storage and dialing? If both, how should domestic prefixes be interpreted and what inputs must remain review-only rather than automatically transformed?
3. **Ambiguity handling:** For an input that parses under more than one interpretation or lacks sufficient context, should Qora reject it, retain it as unverified, or require an operator choice? It must not silently guess.
4. **Invalid-number UX:** At each ingress, should invalid data block persistence, be saved with an explicit invalid/unverified status, or enter a remediation queue? If an operator must repair it, which UI/API workflow will exist?
5. **Legacy migration:** Should existing `Lead.phone` values remain untouched until edited/dialed, be normalized only when unambiguous, or receive a one-time audited migration/review queue? How are canonicalization collisions handled when two legacy rows resolve to one number?
6. **CRM authority:** If Qora changes a phone imported from CRM, should it push the canonical value back, retain source text separately, or treat the external CRM as authoritative until an explicit confirmation?
7. **Privacy/audit behavior:** If raw and canonical values coexist, what retention and visibility rules apply? Existing call/provider observability work already avoids persisting raw phone-bearing provider text.

## Minimal Safe Scope After Those Decisions

A bounded first slice can be limited to the `Lead.phone` lifecycle:

1. Add one shared, pure parser/canonicalizer with an explicit region/country input rather than hidden Argentina assumptions.
2. Make the supported parser dependency explicit, if product policy requires national-format handling.
3. Apply the same result at API creation, CRM import **before** deduplication, and post-call correction before any write.
4. Preserve outbound `validate_e164()` as a pre-charge backstop; consolidate its structural/country-validity behavior with the shared utility only after compatibility tests establish equivalent safety.
5. Return structured, non-PII error codes/messages that distinguish malformed, unsupported-country, and ambiguous/unverified inputs; surface actionable UI state only where a repair workflow actually exists.
6. Add fixtures using synthetic/redacted numbers and test canonicalization, ambiguity rejection/review, tenant isolation, deduplication, no provider invocation, manual trigger, and scheduler failure behavior.

This slice should not silently rewrite legacy rows. A legacy backfill or raw/canonical dual-storage design is a separately approved extension because it has collision, audit, CRM-authority, and rollback consequences.

## Non-Goals

- No new dialer, scheduler runner, retry lane, provider endpoint, real call, or feature-flag change.
- No provider contact, carrier lookup, live-number verification, or assumption that structural E.164 implies reachability.
- No change to CallSession/SIP observability data or storage of raw SIP/provider messages.
- No silent Argentina default, mobile-only policy, country expansion policy, or auto-correction of ambiguous legacy data.
- No CSV importer implementation, phone-management UI redesign, CRM credential/configuration change, or unrelated lead schema cleanup.

## Candidate Files (Conditional on Decisions)

| File | Likely role |
|---|---|
| `backend/app/phones/normalization.py` (new) | Single pure parsing, canonicalization, error taxonomy, and explicit-country seam. A neutral module avoids coupling CRM mapping to outbound dialing. |
| `backend/pyproject.toml` | Declare the chosen supported parsing dependency, if national-format parsing is approved. |
| `backend/app/leads/service.py` and `backend/app/leads/router.py` | Normalize/validate API-created leads and shape safe validation responses. |
| `backend/app/integrations/crm_import_service.py` | Normalize before exact-phone deduplication and define import skip/review/error accounting. |
| `backend/app/integrations/field_mapping.py` | Delegate CRM payload normalization to the shared semantics or remove the divergent helper after compatibility coverage. |
| `backend/app/analysis/universal/data_corrections.py` and `backend/app/summarizer.py` | Replace the loose ten-digit write rule and ensure corrections cannot bypass canonicalization. |
| `backend/app/outbound/phone.py`, `backend/app/outbound/router.py`, `backend/app/outbound/service.py` | Retain and potentially align the last pre-charge validation boundary; maintain no-CallSession/no-provider behavior for invalid data. |
| `frontend/src/features/leads/call-now-cell.tsx` | Improve invalid-number guidance only if the approved remediation path is available. |
| `frontend/src/features/import/page.tsx` | Not needed for the current product; relevant only if CSV import is separately approved. |
| `backend/alembic/versions/...` and a dedicated migration/review mechanism | Needed only for an approved legacy-data policy or new canonical/verification metadata. |
| Backend/frontend tests adjacent to the files above | Cover ingress parity, import deduplication, correction path, manual/scheduler boundaries, and selected UX. |

## Workload Forecast

| Approved scope | Estimated changed lines | Review-budget assessment |
|---|---:|---|
| Shared normalization plus API/CRM-import/post-call ingress wiring and focused backend tests; no legacy migration or edit UI | ~330–470 | Near/over the current 400-line budget; refine after policy choices and pause for `ask-on-risk` if the estimate remains above 400. |
| Above plus user-facing remediation/edit workflow | ~500–700 | Exceeds current budget; requires delivery decision. |
| Above plus country/default metadata and audited legacy migration or raw/canonical dual storage | ~700–1,000+ | Exceeds current budget; should be separately scoped and likely split after explicit approval. |

The incident supports the smallest ingestion-and-storage slice first. It does not support bundling legacy cleanup or dialer changes with normalization.

## Relevant OpenSpec Evidence

- `openspec/config.yaml` requires ambiguous country behavior to be resolved in specification before implementation and preserves trigger-time invalid-E.164 rejection.
- `openspec/specs/outbound-call-trigger/spec.md` defines the manual pre-charge 422/no-session/no-provider invariant and the shared scheduler dial seam.
- `openspec/changes/archive/2026-07-03-phase-c2-outbound-call-trigger/exploration.md` records the original deliberate choice to validate at trigger time rather than retroactively.
- `openspec/changes/phase-c6b-auto-dialer/design.md` documents that the scheduler now reuses `dial_outbound_call()` and shares its guards.
- `openspec/changes/phase-c6b-auto-dialer/specs/outbound-call-trigger/spec.md` modifies the scheduler-reuse contract for live scheduled rows.
- `openspec/changes/call-observability-reconciliation/exploration.md` and `openspec/changes/call-observability-reconciliation/specs/outbound-call-trigger/spec.md` establish provider/SIP PII exclusions that normalization must not weaken.
- `openspec/specs/call-sip-observability/spec.md` prohibits persistence of raw phone-bearing SIP bodies and credentials.

## Evidence Paths

- `backend/app/leads/models.py`
- `backend/app/leads/router.py`
- `backend/app/leads/service.py`
- `backend/app/integrations/crm_router.py`
- `backend/app/integrations/crm_import_service.py`
- `backend/app/integrations/crm_sync_service.py`
- `backend/app/integrations/field_mapping.py`
- `backend/app/analysis/universal/data_corrections.py`
- `backend/app/summarizer.py`
- `backend/app/outbound/phone.py`
- `backend/app/outbound/router.py`
- `backend/app/outbound/service.py`
- `backend/app/outbound/dynamic_vars.py`
- `backend/app/scheduler/service.py`
- `backend/app/scheduler/models.py`
- `backend/pyproject.toml`
- `frontend/src/features/import/page.tsx`
- `frontend/src/features/leads/lead-table.tsx`
- `frontend/src/features/leads/call-now-cell.tsx`
- `frontend/src/features/leads/detail-page.tsx`
- `backend/tests/unit/outbound/test_phone_validator.py`
- `backend/tests/unit/outbound/test_outbound_router.py`
- `backend/tests/unit/outbound/test_dial_service.py`
- `backend/tests/unit/integrations/test_field_mapping.py`
- `backend/tests/unit/integrations/test_crm_import.py`
- `backend/tests/unit/leads/test_router.py`
- `backend/tests/test_data_corrections.py`

## Unresolved Decisions

This exploration is **not ready for proposal** until the seven product decisions above are answered, at minimum country resolution, Argentina mobile/landline eligibility, ambiguity treatment, legacy-data strategy, and invalid-number remediation UX. No user policy has been selected.
