# Delta for outbound-call-trigger

## ADDED Requirements

### Requirement: Strict Canonical Destination Guard

Before any manual or scheduled outbound dial path creates a `CallSession` or contacts a provider, the shared outbound guard MUST approve the stored lead phone only when it is already the exact canonical E.164 output of the approved phone-normalization policy under explicit `AR` context. The guard MUST enforce the Argentina-only mobile and fixed-line destination policy and reject malformed, unsupported, incomplete, or ambiguous stored values.

The guard MUST NOT normalize, repair, convert domestic `15` notation, infer an area code or mobile token, or backfill legacy storage at dial time. A rejected manual trigger MUST retain the existing HTTP 422 behavior. A rejected scheduled path MUST not create a session or provider request and MUST use its established failure handling without introducing or changing retry behavior.

#### Scenario: Manual trigger rejects a legacy noncanonical value before session creation

- GIVEN outbound calls are otherwise permitted and a lead stores synthetic legacy phone `011 15 5555-0101`
- WHEN a manual outbound trigger is requested
- THEN the endpoint returns HTTP 422
- AND no `CallSession` is created
- AND no provider request is made
- AND the stored phone remains `011 15 5555-0101`

#### Scenario: Scheduled path rejects an ambiguous stored value without dialing

- GIVEN a scheduled outbound path reaches its shared dial guard for a lead storing synthetic `011 5555-0101`
- WHEN the guard evaluates the value under explicit `AR` context
- THEN the value is rejected as ambiguous
- AND no `CallSession` is created
- AND no provider request is made
- AND the path does not add or alter retry behavior

#### Scenario: Canonical eligible number proceeds to existing guards

- GIVEN a lead stores synthetic canonical mobile `+5491155550101` and the required feature, authorization, concurrency, and consent guards pass
- WHEN manual or scheduled outbound evaluates the shared destination guard
- THEN the guard permits the existing outbound flow to continue unchanged
- AND that permission is a numbering-format classification, not a guarantee of subscriber assignment or reachability
