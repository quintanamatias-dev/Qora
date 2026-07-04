# Delta for outbound-call-trigger

## MODIFIED Requirements

### Requirement: Call Attempt Persistence

The system MUST create a `CallSession` record before calling the ElevenLabs API. The
record MUST capture telephony metadata — `provider_call_id`, `telephony_provider`,
`telephony_status`, `telephony_error`, and `provider_metadata` — and update them on
API result or error.

The `CallSession` schema now includes five additional nullable SIP observability columns:
`sip_call_id`, `sip_status_code`, `sip_reason`, `reconciled_at`, and
`reconciliation_source`. These columns are NULL at creation and populated asynchronously
by the post-dial probe or background sweep. Their presence MUST NOT block or delay the
call trigger response.

(Previously: `CallSession` had no SIP observability columns; the record captured only
telephony metadata returned synchronously by the ElevenLabs API.)

#### Scenario: Pre-dial record created

- GIVEN a trigger request passes all guards
- WHEN the ElevenLabs API call is about to be dispatched
- THEN a `CallSession` row with `telephony_status=dialing` exists in the database
- AND the row is visible before the API response arrives

#### Scenario: Successful API response persisted

- GIVEN ElevenLabs returns a `provider_call_id` and optional `provider_metadata`
- WHEN the API response is processed
- THEN `CallSession.provider_call_id` is set
- AND `CallSession.provider_metadata` stores only safe/allowlisted provider fields
   (permitted: `call_id`, `status`, `duration_seconds`, `billed_duration_seconds`, `cost`;
    `message` and all other fields including PII and routing data are dropped —
    free-form provider messages may contain phone numbers, caller names, or SIP addresses)
- AND `telephony_status` is updated to `ringing` or the provider-reported equivalent

#### Scenario: Cost and billed seconds persisted when available

- GIVEN the ElevenLabs response includes `cost` and `billed_duration_seconds`
- WHEN the response is persisted
- THEN both values are stored in `provider_metadata` without transformation

#### Scenario: SIP observability columns present at creation — NULL

- GIVEN a new `CallSession` is created by the trigger
- WHEN the row is committed to the database
- THEN `sip_call_id`, `sip_status_code`, `sip_reason`, `reconciled_at`, and
  `reconciliation_source` are all NULL
- AND the trigger response is returned without waiting for probe results

---

## ADDED Requirements

### Requirement: GET Call Session — SIP Observability Fields in Response

The `GET /calls/{session_id}` admin API response MUST include the five SIP observability
fields when they are present on the `CallSession`. Fields that are NULL MUST be included
in the JSON response as `null` (not omitted).

The response schema MUST add:

| Field | Type | Description |
|---|---|---|
| `sip_call_id` | `string \| null` | ElevenLabs/Telnyx SIP Call-ID (`otb_...`) |
| `sip_status_code` | `integer \| null` | Final SIP response status code |
| `sip_reason` | `string \| null` | Final SIP response reason phrase |
| `reconciled_at` | `ISO 8601 datetime \| null` | UTC timestamp when SIP evidence was captured |
| `reconciliation_source` | `"probe" \| "sweep" \| null` | Which path populated the evidence |

No existing fields in the GET response are modified or removed.

#### Scenario: GET response includes SIP fields when available

- GIVEN a `CallSession` where the probe successfully captured SIP evidence
- WHEN `GET /calls/{session_id}` is called with a valid admin API key
- THEN the response body includes `sip_call_id`, `sip_status_code`, `sip_reason`,
  `reconciled_at`, and `reconciliation_source` with their populated values

#### Scenario: GET response includes SIP fields as null when not yet reconciled

- GIVEN a `CallSession` where `reconciled_at IS NULL`
- WHEN `GET /calls/{session_id}` is called
- THEN the response body includes all five SIP fields as `null`
- AND all existing fields retain their current values
