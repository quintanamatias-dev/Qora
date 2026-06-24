# Env File Conventions Specification

## Purpose

Defines the single-source-of-truth `.env` convention for Qora, the structure and classification rules for `.env.example`, the handling of dead/unused env vars, and the documented behavior of frontend build-time env injection. One authoritative file, zero silent divergence.

## Requirements

### Requirement: Root `.env` as Single Authority

The repository MUST designate the root `.env` as the single authoritative source for all runtime secrets. No second copy of the same secrets shall exist without a documented relationship to the root file.

`backend/.env` MUST either be a symlink to `../.env` OR the project documentation MUST explicitly state the copy-and-sync convention with divergence risks documented.

Docker Compose MUST continue to read secrets from the root `.env` via `env_file: .env` — no change required for Docker.

#### Scenario: Local dev using symlink convention

- GIVEN `backend/.env` is a symlink pointing to `../.env`
- WHEN the backend application loads environment variables
- THEN it reads from the root `.env` transparently
- AND no duplication or divergence is possible

#### Scenario: Developer edits root .env

- GIVEN the developer edits `/.env`
- AND `backend/.env` is a symlink
- WHEN the application restarts
- THEN the backend reflects the updated values without any additional step

#### Scenario: Copy convention documented when symlinks unsupported

- GIVEN the operator is on a platform where symlinks are problematic (e.g., some Windows setups)
- WHEN setting up local dev
- THEN the `.env.example` and `docs/ops/secrets-management.md` document the explicit copy fallback
- AND warn that manual sync is required when the root file changes

> **B8 implementation note:** The symlink approach was rejected in favor of updating `load_dotenv()` in `backend/app/main.py` and backend scripts to resolve three `.parent` levels to the repo root. `backend/.env` is neither created nor read. Operators copy root `.env.example` to root `.env`.

---

### Requirement: Classified .env.example

The root `.env.example` (at the repo root — NOT `backend/.env.example`, which is deleted as of B8) MUST classify every known env variable with one of these tier labels: `REQUIRED`, `OPTIONAL`, `PER_CLIENT`, or `FUTURE`.

Each REQUIRED variable MUST include a human-readable comment explaining what it is and where to obtain it.

The file MUST be organized into labeled sections in this order:
1. `## REQUIRED — Critical Platform Secrets`
2. `## REQUIRED — Platform Auth`
3. `## OPTIONAL — Platform Config`
4. `## PER_CLIENT — Integration Credentials`
5. `## FUTURE / Not Yet Wired`

> **B8 implementation note:** `backend/.env.example` was deleted and replaced by root `.env.example`. The backend `load_dotenv()` path was updated to read from the repo root. Operators copy root `.env.example` to root `.env`.

#### Scenario: Operator sets up environment from .env.example

- GIVEN a new operator copies root `.env.example` to root `.env`
- WHEN they read the file
- THEN they can identify every REQUIRED variable, where to get its value, and what happens if it is missing
- AND no variable is present without a tier label

#### Scenario: Every active variable has a section and comment

- GIVEN root `.env.example` is inspected
- WHEN searching for any variable listed in the Secret Classification Table from the proposal
- THEN it appears in exactly one section with its tier label and at least one comment line

---

### Requirement: Dead Variable Cleanup

Env vars that have no active consumer in the application code (`N8N_*`, `TWILIO_*`, `BROKER_NAME`, and any similar orphaned vars) MUST NOT appear in the active REQUIRED or OPTIONAL sections of `.env.example`.

These variables MUST be moved to the `## FUTURE / Not Yet Wired` section or removed entirely if no future integration is planned.

#### Scenario: N8N variables are in the FUTURE section

- GIVEN root `.env.example` is read
- WHEN searching for `N8N_*` variables
- THEN they appear only under `## FUTURE / Not Yet Wired`
- AND are not present in REQUIRED or OPTIONAL sections

#### Scenario: BROKER_NAME is absent or marked clearly

- GIVEN root `.env.example` is read
- WHEN searching for `BROKER_NAME`
- THEN it either does not appear, or appears under `## FUTURE / Not Yet Wired` with a comment explaining why it is not active
- AND it does not appear in any REQUIRED or OPTIONAL section

---

### Requirement: Frontend Env Separation and VITE_API_KEY Warning

`frontend/.env.example` MUST be maintained as a separate file covering only frontend build-time variables.

`VITE_API_KEY` MUST be documented with an explicit warning that it is baked into the browser bundle at build time and is therefore visible to any user with browser developer tools.

The documentation MUST state that `VITE_API_KEY` is a Phase B only mechanism and MUST be replaced by JWT-based authentication in Phase C.

#### Scenario: Developer reads frontend .env.example

- GIVEN a developer opens `frontend/.env.example`
- WHEN they read the `VITE_API_KEY` entry
- THEN a comment clearly states it is browser-visible and lists the Phase C replacement path

#### Scenario: Frontend env variables do not leak into root .env.example

- GIVEN root `.env.example` is read
- WHEN searching for `VITE_*` variables
- THEN none are present — frontend variables are documented only in `frontend/.env.example`

---

### Requirement: Operator Runbook Exists

The system MUST include `docs/ops/secrets-management.md` covering: local dev setup (symlink or copy), Docker deploy steps, secret rotation procedure, and the VITE_API_KEY browser-visibility warning.

The runbook MUST be discoverable from root `.env.example` via a comment reference.

#### Scenario: Operator performs first local setup

- GIVEN `docs/ops/secrets-management.md` exists
- WHEN the operator follows the local dev setup section
- THEN they can complete environment setup without consulting anyone
- AND the steps cover both symlink and copy fallback paths

#### Scenario: Operator rotates a secret

- GIVEN the runbook's rotation procedure section
- WHEN the operator follows the steps
- THEN they know to update the root `.env`, run `check-secrets.py`, and restart the container
- AND no other undocumented steps are required
