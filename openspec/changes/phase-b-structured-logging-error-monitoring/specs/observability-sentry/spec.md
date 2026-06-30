# Observability Sentry Specification

## Purpose

Qora MUST support optional error aggregation via Sentry SDK. When `SENTRY_DSN` is
absent, the system MUST start and operate with zero Sentry-related side-effects.
When `SENTRY_DSN` is present, unhandled exceptions and dead-lettered jobs MUST be
captured and PII MUST be filtered before transmission.

## Requirements

### Requirement: Optional Sentry Initialization

The system MUST initialize the Sentry SDK at application startup if and only if the
`SENTRY_DSN` environment variable is set to a non-empty string.

When `SENTRY_DSN` is absent or empty, no Sentry import side-effects, network calls,
or thread spawns SHALL occur.

#### Scenario: Sentry starts when DSN is configured

- GIVEN `SENTRY_DSN` is set to a valid DSN string
- WHEN the application starts
- THEN `sentry_sdk.init()` is called with the FastAPI integration
- AND a startup log line confirms Sentry is active (without logging the DSN value)

#### Scenario: Application starts normally without SENTRY_DSN

- GIVEN `SENTRY_DSN` is unset or empty
- WHEN the application starts
- THEN no Sentry SDK initialization is attempted
- AND the application handles HTTP requests, voice webhooks, and background jobs normally

#### Scenario: SENTRY_DSN set to empty string is treated as absent

- GIVEN `SENTRY_DSN` is set to `""`
- WHEN the application starts
- THEN the system treats it as absent and skips Sentry initialization

---

### Requirement: PII Filter via before_send

The system MUST register a `before_send` callback with the Sentry SDK that scrubs
PII from all events before transmission.

The following data categories MUST be removed or replaced with a placeholder:
- API keys and tokens (any field whose name contains `key`, `token`, `secret`, `password`, or `dsn`)
- Phone numbers (E.164 format, e.g. `+15551234567`)
- Transcript content (any field whose name contains `transcript` or `content`)

#### Scenario: API key in extra data is scrubbed

- GIVEN a Sentry event contains `extra.openai_api_key = "NON_SECRET_SENTINEL"`
- WHEN `before_send` runs
- THEN the field value is replaced with `"[REDACTED]"`
- AND the event is transmitted to Sentry without the original value

#### Scenario: Phone number in event body is scrubbed

- GIVEN a Sentry event contains a phone number string in any field
- WHEN `before_send` runs
- THEN the phone number is replaced with `"[REDACTED]"`

#### Scenario: before_send returns None to drop event (defense in depth)

- GIVEN a Sentry event cannot be safely scrubbed (e.g., scrubbing fails)
- WHEN `before_send` runs
- THEN the callback returns `None` and the event is dropped rather than transmitted raw

#### Scenario: before_send does not alter events when Sentry is disabled

- GIVEN `SENTRY_DSN` is absent and Sentry is not initialized
- WHEN any exception occurs
- THEN `before_send` is never called (it is not registered)

---

### Requirement: Dead-Letter Job Capture

When `SENTRY_DSN` is set, the system MUST capture a Sentry event whenever a background
job transitions to the dead-letter state (all retries exhausted).

The Sentry event MUST include `job_id`, `job_type`, and the final exception as context.

#### Scenario: Dead-lettered job appears in Sentry

- GIVEN `SENTRY_DSN` is configured and a job exhausts all retry attempts
- WHEN the job executor marks the job as dead-lettered
- THEN a Sentry event is captured with `job_id`, `job_type`, and the last exception
- AND the event is tagged so it can be filtered in Sentry by `job_type`

#### Scenario: Dead-lettered job does not raise when Sentry is absent

- GIVEN `SENTRY_DSN` is absent
- WHEN a job is dead-lettered
- THEN no Sentry capture is attempted
- AND the job failure is recorded in the DB and logged as usual (no regression)

---

### Requirement: Unhandled Exception Capture

When `SENTRY_DSN` is set, the system MUST ensure that exceptions caught by the global
`Exception` handler are also captured in Sentry with the active `request_id` as a tag.

#### Scenario: 500 error appears in Sentry with correlation tag

- GIVEN `SENTRY_DSN` is set and a request triggers an unhandled exception
- WHEN the global `Exception` handler runs
- THEN the exception is captured in Sentry
- AND the Sentry event includes a tag `request_id` matching the active correlation ID
