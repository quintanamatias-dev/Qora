# Secrets Preflight Specification

## Purpose

Defines the behavior of `scripts/check-secrets.py`, the operator pre-flight tool that validates secrets before deployment. Operators SHOULD run this script before every `docker compose up --build`. The script is additive — it does not modify any file or environment.

## Requirements

### Requirement: Classification Table Output

The script MUST print a classification table listing every known env variable, its tier (REQUIRED / OPTIONAL / PER_CLIENT / FUTURE), its presence status (SET / MISSING / PLACEHOLDER), and consumed-by context.

#### Scenario: All secrets present and valid

- GIVEN all REQUIRED variables are set to non-empty, non-placeholder values
- WHEN `python scripts/check-secrets.py` is executed
- THEN the script prints the classification table with all entries marked SET
- AND exits with code 0

#### Scenario: Table includes optional and future variables

- GIVEN OPTIONAL or FUTURE variables are absent
- WHEN the script runs
- THEN those variables appear in the table marked MISSING with tier label OPTIONAL or FUTURE
- AND the script does not treat their absence as a failure

---

### Requirement: Required Variable Validation

The script MUST exit with code 1 if any REQUIRED variable is absent, empty, or set to a known placeholder.

The script MUST identify each failing variable by name and explain the failure reason.

#### Scenario: REQUIRED variable is missing

- GIVEN `OPENAI_API_KEY` is not set
- WHEN the script runs
- THEN exit code is 1
- AND the output names `OPENAI_API_KEY` as missing

#### Scenario: REQUIRED variable contains a weak placeholder

- GIVEN `QORA_API_KEY` is set to `change-me-before-production`
- WHEN the script runs
- THEN exit code is 1
- AND the output identifies `QORA_API_KEY` as containing a weak placeholder

#### Scenario: All REQUIRED variables are valid

- GIVEN every REQUIRED variable is set to a non-empty, non-placeholder value
- WHEN the script runs
- THEN exit code is 0

---

### Requirement: Placeholder Detection

The script MUST maintain an internal list of known weak placeholder patterns (e.g., `change-me-before-production`, `your-key-here`, `TODO`, `REPLACE_ME`) and MUST flag any HIGH or CRITICAL secret that matches.

#### Scenario: Known placeholder detected on a HIGH secret

- GIVEN `QORA_API_KEY` equals a known weak placeholder string
- WHEN the script runs
- THEN the output flags the variable with reason PLACEHOLDER
- AND exit code is 1

#### Scenario: Unknown string that is not a placeholder

- GIVEN `QORA_API_KEY` is set to a non-empty string that does not match any placeholder pattern
- WHEN the script runs
- THEN no placeholder warning is emitted for that variable

---

### Requirement: Per-Client CRM Credential Check

The script MUST read all `backend/clients/*/crm.yaml` files, extract referenced env var names, and validate that each referenced variable is set and not a placeholder.

A missing or placeholder-valued CRM credential MUST cause exit code 1.

#### Scenario: crm.yaml references an env var that is set

- GIVEN `backend/clients/quintana/crm.yaml` references `QUINTANA_AIRTABLE_API_KEY`
- AND `QUINTANA_AIRTABLE_API_KEY` is set to a valid value
- WHEN the script runs
- THEN no CRM credential error is reported

#### Scenario: crm.yaml references an env var that is missing

- GIVEN `backend/clients/quintana/crm.yaml` references `QUINTANA_AIRTABLE_API_KEY`
- AND `QUINTANA_AIRTABLE_API_KEY` is not set
- WHEN the script runs
- THEN exit code is 1
- AND the output names `QUINTANA_AIRTABLE_API_KEY` as missing for client `quintana`

#### Scenario: Client with no crm.yaml

- GIVEN a client directory exists with no `crm.yaml`
- WHEN the script runs
- THEN no CRM validation error is raised for that client

---

### Requirement: Exit Codes and Machine-Readable Output

The script MUST exit with code 0 when all REQUIRED checks pass, and code 1 when any REQUIRED check fails.

The script SHOULD support a `--json` flag that emits results as JSON for CI pipeline consumption.

#### Scenario: CI pipeline consumes JSON output

- GIVEN the script is invoked with `--json`
- WHEN checks complete (pass or fail)
- THEN output is valid JSON with fields: `status` (`ok` | `fail`), `failures` (array of variable names), `warnings` (array)
- AND exit code follows the same 0/1 convention
