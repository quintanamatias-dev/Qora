# Proposal: Normalize lead phones without guessing destinations

## Intent

Make newly created or corrected `Lead.phone` values consistent, canonical E.164 before storage and CRM deduplication. Qora operators and CRM users should encounter invalid contact data at intake rather than after requesting a call. A corrected-format call motivated this work; it is not evidence of a dialer defect or authorization for live verification.

## Authority and evidence

Product decisions are confirmed; no further interview is required. This proposal follows the transported auto/hybrid session preflight, with `ask-on-risk` and a 400-changed-line review budget. Chaining and size exceptions remain unselected.

Inputs read: `openspec/config.yaml`, `exploration.md`, revision-2 `research.md` and `preproposal.md`, their Engram observations (2889, 2909, 2891), the outbound-call-trigger specification, and parent proposal gate 2914. The parent gate supersedes the pre-readback `proposal_ready=false` snapshots; it reports independent hybrid SHA256 verification, not implementation approval. Research has eight source-backed claims. This phase did not repeat collection or hashing.

## Scope and required policy

Introduce one reusable, pure parser/canonicalizer with an explicit region argument and a separately enforced destination policy. Quintana supplies `AR` explicitly; missing context must not trigger a hidden country default. Initial acceptance is Argentine mobile and landline destinations only. Future countries require approved policy and tests, not bespoke regex rewrites.

Parsing must consume a strictly supported full-number input, validate numbering patterns and eligible type/country, and return either canonical E.164 or a stable, non-PII rejection reason. Successful parsing, possible length, and library type classification alone are insufficient. Declare a supported parser dependency rather than retaining environment-dependent regex fallback behavior.

### Ambiguity is rejection, not repair

- Preserve explicitly supplied international destinations. Valid Argentine mobile notation uses `+54 9` plus area/subscriber digits; complete fixed-line international notation uses `+54` plus area/subscriber digits. Neither format proves assignment or reachability.
- Complete domestic mobile forms with a supplied area code and explicit `15` may undergo the documented `0AC15`/`AC15` to `+549AC` transformation when valid. Prefix conversion must preserve the supplied area and subscriber digits.
- Bare geographic digits, including trunk-prefixed forms without an explicit mobile marker, must not be accepted as landlines merely because the parser returns `FIXED_LINE`. Where fixed/mobile intent remains ambiguous, reject; do not prepend `9`, invent an area code, fill missing digits, or infer intent from tenant, CRM, or LLM context.
- Incomplete/local-only, malformed, unsupported-country/type, and ambiguous values fail closed. Full-input grammar must prevent lenient text extraction, vanity conversion, or silent loss of destination information from turning unsupported input into an accepted number.
- Specifications/design must enumerate accepted syntax and rejection examples under these rules. They may not broaden acceptance by inventing type metadata, a new UI, or an unapproved ambiguity heuristic. If implementation cannot meet these rules without another product decision, return a bounded blocker.

### Boundary behavior

| Boundary | Required outcome |
|---|---|
| API lead creation | Validate and normalize before persistence; reject invalid/ambiguous input with a safe validation response and no new lead. |
| CRM pull import | Normalize before tenant-scoped phone comparison; skip invalid/ambiguous rows with reported reasons and accurate accounting, while continuing valid rows. Equivalent accepted spellings match the same canonical phone within the tenant. |
| Post-call phone correction | Validate and normalize before any phone write, including the summarizer path; reject an invalid correction and preserve the previous phone. Do not redesign unrelated analysis behavior. |
| Normal CRM synchronization | Preserve existing sync authority and lifecycle; align the phone mapping seam with shared semantics where needed, without initiating a dedicated external rewrite. |
| Manual and scheduled outbound | Preserve strict canonical-E.164 pre-dial validation and reject invalid, unsupported, or ambiguous destinations before creating `CallSession` or contacting a provider. Do not normalize or repair legacy storage as a side effect of dialing. |

Canonical comparison is not a uniqueness migration. Existing noncanonical rows and pre-existing duplicates remain untouched; this slice does not promise deduplication against every historical spelling, merge leads, or resolve legacy collisions. Tenant isolation must remain intact.

## Affected areas and specification impact

| Area | Expected bounded changes |
|---|---|
| Shared phone utility and dependency | New neutral module such as `backend/app/phones/normalization.py`; dependency declaration in `backend/pyproject.toml`. |
| Lead creation | `backend/app/leads/service.py`, `router.py`: ingress validation and safe errors. |
| CRM | `backend/app/integrations/crm_import_service.py`, `field_mapping.py`: normalization-before-dedup and coherent mapping semantics. |
| Corrections | `backend/app/analysis/universal/data_corrections.py`, `backend/app/summarizer.py`: prevent loose ten-digit validation from bypassing canonical writes. |
| Outbound safety | `backend/app/outbound/phone.py` and necessary guard wiring only; adjacent router/service and scheduler regression coverage. |
| Specifications/tests | New normalization requirements, focused ingress tests, and explicit outbound validation-policy delta. Preserve other active/archived contracts. |

The intended outbound spec delta tightens destination eligibility/ambiguity validation; it does not replace the existing manual HTTP 422/no-session/no-provider invariant. Authentication, tenant ownership, feature flags, concurrent-call/cooldown guards, scheduler claims/failure handling, cost confirmation, provider metadata privacy, and retry semantics remain unchanged.

## Non-goals

No bulk legacy cleanup, schema migration, raw-number shadow storage, validity-state column, automatic merges, new edit screen, CSV importer, remediation queue, or frontend redesign. No dedicated CRM backfill/rewrite, carrier lookup, subscriber verification, provider integration change, retry change, deployment, live call, commit, or other Git mutation is authorized by this proposal.

## Success criteria

1. Given explicit `AR` context and supported complete mobile or landline input, every write ingress produces the same canonical E.164; canonicalization is idempotent.
2. Given valid explicit domestic mobile notation with varying Argentine area-code lengths, normalization preserves all area/subscriber digits and performs only documented prefix conversion.
3. Given bare ambiguous geographic digits, missing area/subscriber digits, malformed full input, or parser-only `FIXED_LINE` evidence, API creation/correction rejects and CRM skips with a safe reason; no guessed destination is stored.
4. Given an explicit non-Argentine international number, passing `AR` to the parser does not bypass the country allowlist. Unsupported number types and missing required region context are rejected.
5. Given equivalent accepted CRM spellings, normalization precedes lookup and avoids creating a formatting-only duplicate against a canonical match in that tenant; another tenant's lead is never matched or changed. Mixed valid/invalid batches report skipped reasons without losing valid rows.
6. Given an invalid post-call correction, the existing phone remains unchanged even through the summarizer write path.
7. Given invalid/ambiguous stored data at manual or shared scheduled dial boundaries, no `CallSession` and no provider request occur. Manual rejection retains HTTP 422; scheduler failure handling and retries are not redesigned.
8. Existing rows are not rewritten by rollout or dialing, ordinary CRM sync remains bounded, and rejection diagnostics do not introduce raw phone-bearing logs or storage.
9. Later implementation supplies isolated strict-TDD evidence for these behaviors and relevant guard regressions with mocked providers. No passing tests or reachability are claimed in this proposal phase.

## Risks and mitigations

- **False acceptance:** Argentina's overlapping fixed/mobile representations and lenient parser extraction can select the wrong destination. Reject ambiguity and test full-input grammar independently of library classification (research R4–R7).
- **More rejected intake:** Conservative policy will skip previously accepted CRM data and reject loose corrections. Report actionable non-PII reasons through existing responses; do not silently add repair UI or invalid storage.
- **Legacy duplication:** Old noncanonical spellings can remain unmatched. Document this first-slice limitation rather than smuggling in backfill or merge behavior.
- **Metadata/version drift:** Research used mutable upstream branches, not pinned releases. Python `9.0.39` was observed on `dev`, not verified as published, installed, or suitable to pin. Google `1.0-SNAPSHOT` is build-parent metadata, not a runtime release. Select and verify an available supported dependency during design/implementation; retain deterministic regression fixtures.
- **Evidence limits:** Government guidance was modified in 2023, not a complete current allocation database. ENACOM retrieval failed; successful government/upstream sources support the retained claims. Exact fetch timestamps were unavailable, so research records honest bounds. Validation does not establish ownership, assignment, or reachability (R8).
- **Review workload:** Exploration estimated roughly 330–470 changed lines before detailed planning; this is not a measured diff. Refine during design/tasks. If the 400-line budget remains at risk, pause for the parent's `ask-on-risk` delivery decision before implementation; no chain or exception is inferred.

## Rollback

No data migration is proposed. A later authorized rollback can revert ingress/parser integration and dependency changes together while retaining existing canonical values; restoring original spellings is neither possible nor required without raw shadow storage. Do not mass-rewrite leads or reverse CRM payloads. Preserve the pre-session/pre-provider guard, including fail-closed ambiguity handling; do not use an unsafe regex fallback as rollback. If safe dialing cannot be maintained, stop and request operator action rather than silently changing flags or allowing charges.

## Next step

Proceed to specifications and design under the confirmed policy, then bounded test-first tasks. No unresolved product question blocks this proposal: ambiguity is already approved for rejection. Any newly discovered need to accept ambiguous forms or expand scope must return to the orchestrator, not become a silent design choice.