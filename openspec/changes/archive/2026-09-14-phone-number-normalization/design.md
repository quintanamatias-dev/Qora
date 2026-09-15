# Design: Canonical phones at intake, unchanged destinations at dialing

Use one pure `phonenumbers` engine with mandatory explicit region and a separate Argentina destination allowlist. Normalize approved writes; outbound only accepts an already-canonical value. Do not guess intent, area codes, or missing digits.

## Authority and scope

This design consumes the transported SDD Session Preflight: auto, hybrid, ask-on-risk, 400 changed lines; no chain strategy or size exception selected. Parent-supplied native status recommends design; its planning dependency exception does not authorize execution. Scope is explicitly Qora `backend`, not `packages/coding-agent`. Only this design artifact is written in this phase.

Inputs read directly: proposal.md (also Engram observation 2916), both change specifications, research.md revision 2, and the boundary code listed below. Research R1–R8 supplies format/parser evidence, not release availability or reachability. Skill resolution: paths-injected (`/Users/mati/.agents/skills/cognitive-doc-design/SKILL.md`). No additional phase-skill path was supplied; executor role instructions supply phase discipline. Installed model routing is unchanged; no model configuration or child delegation is performed.

## Decisions and contracts

| Decision | Contract |
|---|---|
| Neutral engine | New `backend/app/phones/normalization.py` and empty package initializer; no ORM, tenant lookup, logger, LLM, network, or provider dependency. |
| Public function | `normalize_phone(raw: str, *, region: str) -> str`; missing/empty context fails closed, never defaults internally. Boundary adapters explicitly pass `region="AR"` as current approved application policy, not inferred tenant metadata. |
| Country policy | Separate immutable allowed regions `{AR}` and allowed types `{MOBILE, FIXED_LINE}`. Validate parsed destination independently of parsing context. Do not accept `FIXED_LINE_OR_MOBILE`, unknown, premium, toll-free, VoIP, satellite/non-geographic forms outside the approved syntax. |
| Errors | `PhoneNormalizationError(ValueError)` with `.reason`; message `Invalid phone: <reason>` only. No raw input, parser exception text, or chained input-bearing exception in diagnostics. |
| No framework | Small AR syntax proof plus metadata parser and policy checks; no plugin registry, country configuration schema, generic correction framework, or new UI. Future countries require explicit policy/spec/tests. |

Stable reasons: `region_required`, `unsupported_region`, `invalid_syntax`, `ambiguous_or_incomplete`, `invalid_number`, `unsupported_country`, `unsupported_type`. Outbound adds `noncanonical_phone`. Check region first, full-input lexical syntax second, then explicit-country policy, metadata validity/type and representation proof. A missing Python keyword naturally raises TypeError; explicit None/empty produces `region_required`. Invalid types/empty raw values yield `invalid_syntax`; do not stringify CRM numbers or booleans.

## Strict syntax and metadata algorithm

1. Consume the entire string. Permit ASCII digits, a single leading `+`, ASCII spaces, hyphens, and balanced non-nested parentheses around digit groups. Spaces at edges may be trimmed for intake; separator-only values, empty parentheses, dangling hyphens, misplaced plus signs, nested/unbalanced parentheses, tabs/newlines, Unicode digits, dots, slashes, URI prefixes, extensions, prose and vanity letters are rejected. A small lexical full-match/group check establishes this before removing permitted visual separators. It does not encode area codes.
2. For explicit `+` input, parse with `phonenumbers.parse(compact, region, keep_raw_input=False)`. Reject a parsed country outside the separate allowlist, then require `is_valid_number` and `is_valid_number_for_region(..., "AR")`. Require an eligible exact number type. E.164 formatting must equal the compact original, preventing lenient removal of trunk prefixes or other supplied destination digits.
3. International mobile additionally requires `+549` followed by exactly ten supplied geographic digits, and MOBILE classification. International fixed line requires `+54` followed by exactly ten supplied geographic digits and FIXED_LINE classification. The explicit international form establishes the approved notation; classification alone never makes domestic bare digits eligible.
4. For domestic input, parse the compact digits with explicit AR and let library national-prefix metadata perform `0AC15`/`AC15` conversion. Require a valid AR MOBILE result with national significant digits `9` plus ten geographic digits. Never search for a `15` substring or split at a fixed area-code length.
5. Prove domestic representation using metadata's public NATIONAL formatter: strip only its visual separators, remove at most its optional trunk `0`, and require original compact input to equal that metadata-generated full mobile national form with or without one leading `0`. The AR NATIONAL mobile format supplies `AC15SN`; this round trip proves marker position and supplied area/subscriber preservation. Reject all mismatches as `ambiguous_or_incomplete`, including bare geographic input that the parser classifies FIXED_LINE. No handmade area-code table or reconstruction by scanning digits is allowed.
6. Return E.164 only after the proof succeeds. Re-normalizing canonical output is identical. The implementation release qualification must verify NATIONAL round-trip behavior for 2-, 3-, and 4-digit area codes; if that public API cannot establish the proof, stop with a bounded technical blocker rather than substitute a `15` heuristic or silently broaden syntax.

The ordinary ten-digit geographic shape comes from research R1, not a claim that all library MOBILE numbers are ordinary Argentine mobile destinations. Metadata owns range validity, area-code variability and prefix conversion. No acceptance guarantees assignment, ownership, or reachability.

## Dependency qualification

`backend/pyproject.toml` requires Python >=3.11 and currently omits phonenumbers. `backend/uv.lock` exists (lock format 1/revision 3, Python >=3.11). Add a mandatory runtime dependency and update this existing lock with a targeted resolution; do not upgrade unrelated packages.

Choose a published, non-yanked stable Python phonenumbers 9.x release whose declared Python support includes the repository runtime, whose public parse/format/validation APIs meet the algorithm, and whose AR metadata passes the regression fixtures. Declaration shape is `phonenumbers>=<verified-9.x-baseline>,<10`; the lock records the exact qualified release and hashes. The lower bound is deliberately not fabricated here. Release/index availability, Requires-Python, actual selected version, and metadata round-trip confirmation are mandatory initial implementation tasks before engine acceptance. If no supported 9.x release can be verified, return a dependency blocker and revise the constraint explicitly. Research's dev `9.0.39` is not evidence of a published version; Google `1.0-SNAPSHOT` is unrelated build-parent metadata.

Remove optional-import behavior and regex fallback in outbound. Missing dependency must fail installation/startup, never weaken destination validation. No tests, install, release lookup, or lock regeneration occurred in design.

## Boundary data flow and exact changes

| File / function | Change and failure semantics |
|---|---|
| `backend/app/leads/service.py:create_lead` | Normalize with explicit AR before constructing Lead, session.add or flush. Keep signature and unrelated CRUD/custom-field behavior. Seeds bypass this service and remain unchanged legacy data, not silently repaired. |
| `backend/app/leads/router.py:create_new_lead` | Keep auth and client_id resolution first. Catch only PhoneNormalizationError around create_lead; return HTTP 422 `detail={"error":"invalid_phone","reason":reason}` without echoing input. No custom-field writes or commit on rejection. No request schema or frontend changes. |
| `backend/app/integrations/crm_import_service.py:import_leads_from_crm` | After reverse mapping and before `_find_lead_by_phone`, normalize phone and replace `qora_data["phone"]` with canonical output. Missing values also increment skipped and report safe reason. Catch phone error per row, append `Invalid phone for record <id>: <reason>`, increment skipped exactly once, continue without lookup/savepoint/mutation. Retain source record identifier conventions; never use a phone as diagnostic identifier. |
| Same file: `_find_lead_by_phone`, `_create_lead_from_qora_data`, `_update_lead_from_qora_data` | Query still requires client_id AND canonical phone; constructor consumes the canonical dict. Update helper still does not rewrite phone. Preserve savepoints, external-ID handling, forward-only status and custom-field routing. Do not normalize database rows or merge historical duplicates. Same-batch equivalent forms must see prior flushed creates. |
| Same file: lookup error logging | Remove `phone` and input-bearing exception text from the touched phone-lookup failure diagnostic; retain record identifier and safe error category. Avoid converting new validation failures into existing generic mapping exceptions. |
| `backend/app/integrations/field_mapping.py:normalize_phone_e164`, `_coerce_phone` | Retain compatibility helper name, delegate to engine with explicit AR, translate PhoneNormalizationError to safe MappingError without raw/chained parser text. Remove numeric stringify and regex-only logic. `reverse_map` remains a field translation, with import validation owned by import service independent of configured field type. |
| `backend/app/analysis/universal/data_corrections.py:_validate_phone`, `_process_corrections` | Validator delegates to engine and returns existing `(ok, reason)` shape. Phone-specific processing normalizes candidate before idempotency/validation result creation and emits canonical corrected_value when accepted. Reject safely when normalization fails. Non-phone registry, confidence gate and analysis behavior remain unchanged. |
| `backend/app/summarizer.py:_apply_structured_corrections` | Do not trust applied=True from an upstream pipeline/mock/model. After existing applied/registry gates, normalize phone before setattr, update returned correction corrected_value to canonical output, and reject with applied=False/reason on failure while preserving Lead.phone. Do not re-enable already rejected corrections. Non-phone coercion remains unchanged. |
| Same file: `_merge_facts_into_lead` downstream flow | Existing returned correction list feeds facts audit, applied-only profile facts and custom-field writes. Keep this order so rejected phone corrections never become applied profile facts. No new audit/shadow storage; existing correction evidence schema remains intact. |
| `backend/app/outbound/phone.py:validate_e164` | Retain function/ValueError contract. Reject anything not exact ASCII canonical E.164 before calling engine; validate canonical candidate with explicit AR and require equality. Return original unchanged, never a repaired value. Safe ValueError message contains `E.164` and reason only. Rewrite inaccurate carrier/reachability comments. |
| `backend/app/outbound/router.py:trigger_outbound_call`, `service.py:dial_outbound_call` | Existing validator calls already protect manual/shared paths; normally no wiring edit needed. Manual invalid phone remains 422; shared result remains failed, invalid_phone, call_session_id=None. No provider/session creation, no normalization assignment at dial time. |
| `backend/app/scheduler/service.py:_dial_claimed_scheduled_call` | Regression-only surface: real shared guard returns invalid_phone; existing failed-result branch marks ScheduledCall failed and commits. outcome_session_id remains null. No retry or claim changes. |

Ordinary CRM push uses the existing mapper/sync lifecycle: valid values yield canonical payloads, invalid legacy values yield existing mapping-failure handling. It never assigns Lead.phone or runs a dedicated rewrite/backfill. Preserve the sync authority and transaction policy.

Phone-specific correction logs must omit current/corrected values in idempotency, rejection, and application messages (including the summarizer's existing raw corrected_value fields). Reasons are stable codes; do not copy NumberParseException strings. Existing correction evidence/audit fields are not a new diagnostics store and are not expanded into raw phone shadow storage. Non-phone logging is outside this bounded change.

## Guard ordering that must not move

Manual execution order in actual code: API-key dependency; feature flag; client existence; lead existence/tenant ownership; cooldown; phone validation; default agent resolution; active-session query; record cooldown attempt; shared dial. Thus cooldown can still return 429 ahead of invalid-phone 422, and unauthorized/missing/foreign lead cases do not expose phone validity.

Shared dial order: feature flag; phone; agent external ID; agent phone ID; per-lead lock; active session; in-progress scheduled overlap excluding current claim; durable CallSession; dynamic variables; provider and existing outcome/retry handling. An invalid phone fails before lock, session construction, dynamic variables or provider construction.

Scheduled wrapper retains allowed-hours rescheduling, do_not_call cancellation and agent resolution before shared dial. Its claim may already exist/commit; the guarantee is no CallSession/provider request, not zero ScheduledCall writes. Preserve flags, consent/cost controls, ownership, metadata privacy, locks, cooldown and retries exactly; do not add new consent logic in this slice.

## Synthetic test matrix and test locations

Fixtures below are synthetic pattern-test candidates, never live-call targets and not guaranteed unassigned. Qualify metadata-dependent positives against the selected locked release before using them; tests assert literal expected outputs rather than computing expected values with the implementation.

| Input | Expected result / purpose |
|---|---|
| `+54 9 11 5555 0101`, `011 15 5555-0101`, `11 15 5555-0101` | `+5491155550101`; two-digit AC, equivalent spellings, idempotency. |
| `0341 15 555-0101`, `341155550101` | `+5493415550101`; three-digit AC, optional trunk, no hardcoded Buenos Aires split. |
| `02966 15 550101`, `296615550101` | Candidate `+5492966550101`; four-digit AC; confirm range metadata in release qualification. |
| `+54 (11) 5555-0102` | `+541155550102`; explicit fixed line preserved without adding 9. |
| `011 5555-0101`, `1155550101`, `5555-0101`, `15 5555-0101` | Reject ambiguity/local-only input regardless of parser-only FIXED_LINE classification. |
| `011 15 555-010`, `+549115555010`, `+54911555501011` | Reject missing/extra subscriber digits, never pad/truncate. |
| `011 5515-0101` | Reject bare number even though subscriber contains 15; defeats substring heuristic. |
| `+54 011 5555-0102`, `0054 9 11 5555 0101`, `5491155550101` | Reject unsupported international trunk/access/bare-country spellings despite lenient parse. |
| `+56 9 5555 0101` with AR | unsupported_country; parse context is not policy. |
| `+54 800 555 0101` | Qualified toll-free candidate: unsupported_type, never landline based only on length. |
| `Call +54 9 11 5555 0101 ext 7`, `tel:+5491155550101`, `1-800-QORA`, dots, newline, Unicode digit, malformed parentheses | invalid_syntax; full-input consumption and no extraction/vanity conversion. |
| None/empty region, non-AR region, integer/bool phone | Required context/type rejection with no value in error. |

Create `backend/tests/unit/phones/test_normalization.py` for grammar, type/country, metadata conversion, preservation, idempotency and error privacy. Use real locked phonenumbers for these tests, not a mock of the parser; targeted mocks may supplement unsupported-type/error translation branches, never replace metadata evidence.

Add `backend/tests/unit/leads/test_phone_normalization.py` for service and HTTP adapter: canonical response/persistence; invalid request creates no Lead, custom fields, flush or commit; existing client_id error precedes phone errors. Use an isolated database test where it strengthens the no-write assertion.

Extend `backend/tests/unit/integrations/test_crm_import.py` and `test_field_mapping.py`: mixed valid/invalid batch exact counts; spy confirms canonical argument before lookup; two equivalent rows in an empty tenant create then update; canonical existing match in tenant A; identical phone in tenant B untouched; legacy noncanonical row unchanged; savepoint failure still isolates rows; invalid push mapping safe and non-mutating. Re-run `backend/tests/integration/integrations/test_crm_sync_service.py` for unchanged lifecycle.

Extend `backend/tests/test_data_corrections.py` and `test_summarizer_corrections.py`: canonical accepted correction, formatting-equivalent idempotency, malformed/ambiguous rejected candidate, direct applied=True bypass attempt, old value unchanged, safe reason, applied-only fact exclusion, unrelated name/business correction still works. Capture logs to prove candidate digits are absent from touched diagnostics.

Extend `backend/tests/unit/outbound/test_phone_validator.py` plus existing outbound router/service guard suites; add focused scheduler regression alongside `backend/tests/unit/scheduler/test_auto_dialer_claim.py`. Do not mock validate_e164 in normalization integration cases. Mock provider/probe/network, inspect persisted CallSession count and provider call count (both zero for rejection), preserve stored input exactly. A scheduled wrapper test must invoke real shared dial guard, not return a fabricated DialResult. Assert failed scheduled status/null outcome/no retry. Canonical positive tests use qualified AR fixtures; change old foreign/short happy-path fixtures only where stricter policy makes them invalid. Preserve flag/auth/tenant/cooldown/agent/concurrency precedence and provider metadata/retry regressions.

Strict TDD during authorized implementation: failing engine cases, minimum engine, then failing boundary cases and integrations; record commands/results per work unit and run relevant existing suites. No tests were run in this design phase.

## Rollout, rollback and review budget

Deploy dependency/lock and boundary integration together only after tests and authorization. No legacy migration, schema, seed rewrite, flag, new UI, dedicated CRM rewrite, carrier lookup, deployment or live call is authorized by design. Old noncanonical rows may not deduplicate and must fail outbound rather than being repaired. Rollback does not restore original spellings or mass-rewrite canonical values. Keep safe outbound rejection in any rollback; never restore environment-dependent permissive regex fallback. If safe operation cannot be retained, return to operator authority rather than toggle flags silently.

Updated forecast (not measured diff): engine/adapter production 210–310 changed lines; focused tests and fixture adjustments 230–380; dependency/lock and documentation 30–70 excluding this design and already-authored planning artifacts. Likely implementation total 470–760, with aggregate change larger when planning artifacts are counted. Existing outbound module removal counts as changed lines too; do not hide deletions, generated lock changes or tests to claim 400.

This materially exceeds the 400-line ask-on-risk budget. Parent must pause for a delivery decision before implementation: explicitly selected chaining (with strategy then chosen) or explicit size:exception acceptance. No artificial compression, dropped assertions, inferred exception or preselected chain. Tasks may refine reviewable work units, but cannot bypass this delivery gate. Preserve unrelated worktree changes with targeted edits; this phase did not inspect or reset a Git diff and claims no clean-worktree verification.

## Next step

Parent validates hybrid design persistence, obtains the ask-on-risk delivery choice, and creates bounded tasks including release qualification and metadata proof. No unresolved product ambiguity remains: unsupported or ambiguous input is rejection. Technical inability to prove the accepted syntax is a blocker, not permission to guess.
