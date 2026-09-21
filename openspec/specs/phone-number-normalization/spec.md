# Phone Number Normalization Specification

## Purpose

Defines safe, Argentina-only normalization of lead phone values at approved write and comparison boundaries. It produces canonical E.164 values without guessing a destination or asserting subscriber reachability.

## Requirements

### Requirement: Explicit Region and Destination Policy

The system MUST require an explicit `AR` region context for every normalization request. The region context MUST be used only to interpret supported domestic input; it MUST NOT act as a destination-country allowlist. The destination policy MUST independently allow only Argentine mobile and fixed-line numbers. A missing region, a non-Argentine explicit international destination, or an unsupported number type MUST be rejected with a stable, non-PII reason.

#### Scenario: Explicit international country does not bypass the allowlist

- GIVEN explicit `AR` context and the complete synthetic input `+56 9 5555 0101`
- WHEN the value is normalized
- THEN it is rejected as an unsupported destination country
- AND the rejection reason contains no raw phone value

#### Scenario: Missing region is not silently defaulted

- GIVEN a domestic-form input `011 15 5555-0101` and no region context
- WHEN the value is normalized
- THEN it is rejected for missing required region context
- AND the system does not infer `AR` from a tenant, CRM record, or model context

### Requirement: Strict Supported Full-Number Syntax

The system MUST accept only a complete, full-number input in one of these supported forms, after accepting only ordinary visual separators (spaces, hyphens, and parentheses) within the number:

| Eligible destination | Supported form | Canonical result shape |
|---|---|---|
| Argentine mobile | Explicit international `+54 9 AC SN` | `+549ACSN` |
| Argentine fixed line | Explicit international `+54 AC SN` | `+54ACSN` |
| Argentine mobile | Complete domestic `0AC15SN` or `AC15SN` | `+549ACSN` |

`AC` is a supplied valid Argentine area code and `SN` is a supplied valid subscriber number; their lengths MUST be validated against Argentine numbering metadata rather than a fixed area-code split. The full input MUST contain no extension, prose, vanity letters, URI prefix, or omitted component. The system MUST validate the complete normalized number and its eligible mobile or fixed-line class; parser success, possible length, or a parser-only `FIXED_LINE` classification MUST NOT independently establish eligibility.

#### Scenario: Complete domestic mobile preserves all supplied digits

- GIVEN explicit `AR` context and the synthetic input `0341 15 555-0101`
- WHEN the value is normalized
- THEN the eligible mobile result is `+5493415550101`
- AND the supplied area and subscriber digits are preserved

#### Scenario: Explicit international fixed line is eligible

- GIVEN explicit `AR` context and the synthetic input `+54 (11) 5555-0102`
- WHEN the value is normalized
- THEN the eligible fixed-line result is `+541155550102`
- AND the result is a numbering-format classification, not a guarantee that a subscriber is assigned or reachable

#### Scenario: Text and extension syntax fail closed

- GIVEN explicit `AR` context and an input such as `Call +54 9 11 5555 0101 ext 7` or `1-800-QORA`
- WHEN the value is normalized
- THEN it is rejected with a stable, non-PII reason
- AND the system does not extract, convert, or retain a phone substring

### Requirement: Ambiguity and Incompleteness Are Rejected

The system MUST reject bare geographic digits, including trunk-prefixed values without the explicit domestic mobile `15` marker, whenever the syntax does not establish mobile or fixed-line intent. The system MUST reject local-only, incomplete, malformed, and otherwise invalid values. It MUST NOT prepend a mobile `9`, invent an area code, add subscriber digits, or infer intent from tenant, CRM, parser, or model context.

#### Scenario: Bare trunk form is not promoted to a fixed line

- GIVEN explicit `AR` context and the synthetic input `011 5555-0101` without `15`
- WHEN the parser can classify the digits as `FIXED_LINE`
- THEN normalization rejects the value as ambiguous
- AND it does not emit `+541155550101` or `+5491155550101`

#### Scenario: Local-only form is not completed

- GIVEN explicit `AR` context and the synthetic input `5555-0101`
- WHEN the value is normalized
- THEN it is rejected as incomplete or ambiguous
- AND no area code or missing digits are created

### Requirement: Canonical E.164 Result

For every accepted value, the system MUST return the E.164 representation containing exactly a leading `+` followed by the canonical country and national digits, with no formatting separators. Normalization of an already accepted canonical value MUST return the identical value. Acceptance and canonicalization MUST NOT claim ownership, assignment, dialability, or subscriber reachability.

#### Scenario: Canonicalization is idempotent

- GIVEN explicit `AR` context and the accepted synthetic mobile input `+54 9 11 5555 0101`
- WHEN it is normalized once and the result is normalized again
- THEN both results are exactly `+5491155550101`
- AND neither result represents a guarantee of subscriber reachability

### Requirement: Lead Creation and CRM Import Boundaries

The lead-creation API MUST normalize and validate a submitted phone before storage and MUST reject an invalid or ambiguous value through a safe validation response without creating a lead. CRM pull import MUST normalize a source phone before tenant-scoped phone comparison. It MUST match equivalent accepted spellings to the same canonical phone only within that tenant, continue processing other valid rows, and skip invalid or ambiguous rows with stable non-PII reasons and accurate skip accounting.

Canonical comparison MUST NOT rewrite existing rows, merge leads, or resolve historical noncanonical duplicates. A CRM row from one tenant MUST NOT match or change a lead in another tenant.

#### Scenario: API input is rejected before storage

- GIVEN a lead-create request with explicit `AR` context and `011 5555-0101`
- WHEN the API validates the phone
- THEN the API returns its safe validation rejection
- AND no lead is stored

#### Scenario: CRM comparison occurs after normalization and remains tenant-scoped

- GIVEN tenant A already has canonical synthetic phone `+5491155550101`, tenant B has a different lead, and a CRM batch for tenant A contains `011 15 5555-0101` plus invalid `5555-0101`
- WHEN the batch is imported
- THEN the valid row matches tenant A's canonical phone without a formatting-only duplicate
- AND the invalid row is skipped with a non-PII reported reason and included in skip accounting
- AND tenant B is not matched or changed

### Requirement: Post-Call Phone Corrections

Every post-call phone correction path, including a summarizer-originated correction, MUST validate and normalize a proposed phone before writing it. An invalid or ambiguous correction MUST be rejected and MUST preserve the previously stored phone. This requirement MUST NOT alter unrelated post-call analysis behavior.

#### Scenario: Invalid summarizer correction preserves the old phone

- GIVEN a lead currently stores `+5491155550101` and a summarizer proposes `011 5555-0101`
- WHEN the correction is processed with explicit `AR` context
- THEN the correction is rejected with a non-PII reason
- AND the lead still stores `+5491155550101`

### Requirement: Bounded Normalization Rollout

The system MUST use the same normalization semantics at the approved creation, CRM comparison, and correction boundaries without a bulk legacy cleanup or dedicated CRM rewrite. It MUST NOT add a phone schema field, raw-number shadow storage, validity-state column, new UI, feature flag, provider call, or retry behavior as part of this capability.

#### Scenario: Legacy data is not changed by rollout

- GIVEN an existing lead stores a noncanonical legacy phone and no approved write boundary updates it
- WHEN normalization capability is deployed or an ordinary CRM synchronization runs
- THEN the existing value is not backfilled or rewritten
- AND no new phone-data schema or user-interface workflow is required
