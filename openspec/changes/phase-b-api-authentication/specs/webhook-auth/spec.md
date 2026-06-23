# Webhook Auth Specification

## Purpose

Shared-secret header verification for ElevenLabs voice webhook endpoints (`/voice/initiation`, `/voice/custom-llm/*`). Protects against unauthorized callers fabricating voice sessions. Opt-in by default to allow coordinated rollout without breaking existing ElevenLabs agents.

## Requirements

### Requirement: Shared-Secret Header Verification

When webhook auth is enabled, the system MUST verify that incoming webhook requests carry a shared secret in the `X-Webhook-Secret` header. Requests with a missing or incorrect secret MUST be rejected with HTTP 401 before any handler logic executes.

The comparison MUST use constant-time string equality to prevent timing attacks.

#### Scenario: Valid webhook secret when auth is enabled

- GIVEN `QORA_WEBHOOK_AUTH_ENABLED=true` and a correct `X-Webhook-Secret` header
- WHEN a voice initiation webhook arrives
- THEN the system processes the request normally

#### Scenario: Missing secret when auth is enabled

- GIVEN `QORA_WEBHOOK_AUTH_ENABLED=true`
- WHEN a request arrives at `/api/v1/voice/initiation` with no `X-Webhook-Secret` header
- THEN the system returns HTTP 401; no session is created

#### Scenario: Incorrect secret when auth is enabled

- GIVEN `QORA_WEBHOOK_AUTH_ENABLED=true` and an incorrect `X-Webhook-Secret` value
- WHEN the webhook request is received
- THEN the system returns HTTP 401 using constant-time comparison

### Requirement: Disabled-by-Default Rollout Flag

Webhook auth MUST be disabled by default (`QORA_WEBHOOK_AUTH_ENABLED=false`). When disabled, all voice webhook endpoints MUST accept requests without a secret header and process them normally.

This ensures existing ElevenLabs agents continue working without reconfiguration until the operator explicitly enables webhook auth and updates the ElevenLabs dashboard with `QORA_WEBHOOK_SECRET`.

#### Scenario: Auth disabled — no secret required

- GIVEN `QORA_WEBHOOK_AUTH_ENABLED=false` (default)
- WHEN a voice initiation webhook arrives without `X-Webhook-Secret`
- THEN the system processes the request normally (no 401)

#### Scenario: Enabling webhook auth

- GIVEN `QORA_WEBHOOK_AUTH_ENABLED` is changed from `false` to `true` and the process restarted
- WHEN a webhook arrives without the secret
- THEN the system returns HTTP 401; the operator must update ElevenLabs dashboard before calls resume

### Requirement: Config-Driven Secret

The webhook shared secret MUST be read from `QORA_WEBHOOK_SECRET` environment variable. The value MUST NOT appear in logs, responses, or error bodies. If `QORA_WEBHOOK_AUTH_ENABLED=true` and `QORA_WEBHOOK_SECRET` is not set, startup MUST fail with a clear configuration error.

#### Scenario: Webhook auth enabled but secret missing

- GIVEN `QORA_WEBHOOK_AUTH_ENABLED=true` and `QORA_WEBHOOK_SECRET` not set
- WHEN the backend attempts to start
- THEN startup fails with a configuration error before serving any requests

### Requirement: Webhook Auth Scope

Webhook auth (`QORA_WEBHOOK_SECRET`) MUST apply only to ElevenLabs voice endpoints. It MUST NOT be used for admin API routes (which use `QORA_API_KEY`) and MUST NOT be confused with or replace bearer token auth.

#### Scenario: Admin route uses bearer token, not webhook secret

- GIVEN webhook auth is enabled
- WHEN `GET /api/v1/clients` is called with `X-Webhook-Secret` but no `Authorization` header
- THEN the system returns HTTP 401 (webhook secret is not accepted on admin routes)
