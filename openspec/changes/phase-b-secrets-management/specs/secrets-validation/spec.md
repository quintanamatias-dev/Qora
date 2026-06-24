# Secrets Validation Specification

## Purpose

Defines the startup validation contract for all secrets and credentials loaded by Qora. The system MUST fail fast with a clear, actionable error before serving any request when a required secret is absent or invalid. Secrets are classified by tier; each tier has a defined failure mode.

## Secret Tier Classification

| Variable | Tier | Owner | Validation Rule |
|---|---|---|---|
| `OPENAI_API_KEY` | CRITICAL | Qora (global) | Hard fail — always |
| `ELEVENLABS_API_KEY` | CRITICAL | Qora (global) | Hard fail — always |
| `QORA_API_KEY` | HIGH | Qora (platform) | Required — hard fail always |
| `QORA_WEBHOOK_SECRET` | HIGH | Qora (platform) | Required if `QORA_WEBHOOK_AUTH_ENABLED=true` |
| `{CLIENT}_AIRTABLE_API_KEY` | HIGH | Per-client CRM | Hard fail if `crm.yaml` references the var |
| `DATABASE_URL` | MEDIUM | Infrastructure | Optional — defaults to SQLite |
| All OPTIONAL / FUTURE vars | LOW | — | Silent — defaults apply |

## Requirements

### Requirement: Critical Secret Fail-Fast

The system MUST validate `OPENAI_API_KEY` and `ELEVENLABS_API_KEY` during application startup, before any HTTP request is accepted.

If either variable is absent or empty, the system MUST abort startup and emit an error message naming the missing variable.

#### Scenario: App starts with all critical secrets present

- GIVEN `OPENAI_API_KEY` and `ELEVENLABS_API_KEY` are set to non-empty values
- WHEN the application starts
- THEN startup completes and the app serves requests normally

#### Scenario: App starts with OPENAI_API_KEY missing

- GIVEN `OPENAI_API_KEY` is not set or is an empty string
- WHEN the application starts
- THEN startup aborts before serving any request
- AND the error message names `OPENAI_API_KEY` as the missing variable

#### Scenario: App starts with ELEVENLABS_API_KEY missing

- GIVEN `ELEVENLABS_API_KEY` is not set or is an empty string
- WHEN the application starts
- THEN startup aborts before serving any request
- AND the error message names `ELEVENLABS_API_KEY` as the missing variable

---

### Requirement: Platform API Key Required

The system MUST require `QORA_API_KEY` in all environments, including local development.

If `QORA_API_KEY` is absent or empty, the system MUST abort startup with a clear error.

#### Scenario: QORA_API_KEY is set in local dev

- GIVEN `QORA_API_KEY` is set to any non-empty value (including a simple local placeholder)
- WHEN the application starts
- THEN startup succeeds

#### Scenario: QORA_API_KEY is missing in any environment

- GIVEN `QORA_API_KEY` is not set or is an empty string
- WHEN the application starts
- THEN startup aborts
- AND the error message names `QORA_API_KEY` as the missing variable

---

### Requirement: Conditional Webhook Secret

The system MUST validate `QORA_WEBHOOK_SECRET` if and only if `QORA_WEBHOOK_AUTH_ENABLED` is `true`.

If webhook auth is enabled and `QORA_WEBHOOK_SECRET` is absent or empty, the system MUST abort startup.

#### Scenario: Webhook auth disabled — secret absent

- GIVEN `QORA_WEBHOOK_AUTH_ENABLED` is `false` or not set
- AND `QORA_WEBHOOK_SECRET` is not set
- WHEN the application starts
- THEN startup succeeds without a webhook secret error

#### Scenario: Webhook auth enabled — secret missing

- GIVEN `QORA_WEBHOOK_AUTH_ENABLED` is `true`
- AND `QORA_WEBHOOK_SECRET` is not set
- WHEN the application starts
- THEN startup aborts with an error naming `QORA_WEBHOOK_SECRET`

---

### Requirement: Placeholder Value Rejection

The system MUST NOT accept known weak placeholder values (e.g., `change-me-before-production`) for HIGH or CRITICAL secrets.

If a HIGH or CRITICAL secret is set to a known placeholder, the system MUST abort startup and identify the offending variable and value pattern.

#### Scenario: Placeholder detected for a critical secret

- GIVEN `OPENAI_API_KEY` is set to `change-me-before-production`
- WHEN the application starts
- THEN startup aborts
- AND the error message identifies `OPENAI_API_KEY` as containing a weak placeholder

#### Scenario: Valid non-placeholder value accepted

- GIVEN `OPENAI_API_KEY` is set to a non-placeholder, non-empty value
- WHEN the application starts
- THEN startup does not reject the value based on content

---

### Requirement: Settings as Sole Env Authority

The system MUST route all reads of declared environment variables through the `Settings` class. Direct `os.getenv()` calls in application code for variables declared in `Settings` MUST NOT exist.

#### Scenario: CORS origins read via Settings

- GIVEN `QORA_ALLOWED_ORIGINS` is set in the environment
- WHEN the CORS middleware is configured at startup
- THEN the value is read from `settings.qora_allowed_origins`, not via `os.getenv()` directly

#### Scenario: Docs toggle read via Settings

- GIVEN `QORA_DOCS_ENABLED` is set in the environment
- WHEN FastAPI is configured at startup
- THEN the value is read from `settings.qora_docs_enabled`, not via `os.getenv()` directly
