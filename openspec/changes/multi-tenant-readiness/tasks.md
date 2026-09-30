# Tasks: Multi-Tenant Readiness

Strict TDD (RED → GREEN) per task group.
Backend gate: `cd backend && uv run pytest tests/ -q`.
Frontend gate: `cd frontend && npm test -- --run && npm run build`.

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | WU1 ~450, WU2 ~700, WU3 ~350, WU4 ~80, WU5 docs |
| 400-line budget risk | High overall — split into chained PRs |
| Chained PRs recommended | Yes |
| Suggested split | PR A (WU1 + WU4 backend) → PR B (WU2) → PR C (WU3 + frontend WU4) → PR D (WU5 docs) |

## WU1 — Tenant access layer + IDOR closure

- [x] 1.1 RED: `tests/unit/core/test_access.py` — principal roles, `can_access`, `require_client_access` 403, `require_superadmin` 403, `ensure_resource_access` 404, case-insensitive match.
- [x] 1.2 GREEN: extend `CallerIdentity`; add `app/core/access.py`.
- [x] 1.3 RED: `tests/unit/test_tenant_isolation_routes.py` — with a `client` principal for tenant A:
  - tenant-B resources by ID return 404 (calls: get, status, transcript, analysis, end; leads: get, patch status, history, context-preview, dimension-rollups)
  - tenant-B scoped lists return 403 (leads, calls, metrics, active, analytics, scheduler, outbound, agents, integrations, crm import, clients get)
  - superadmin-only routes return 403 (clients list-create-patch-delete, agent writes, integration writes, signed-url)
  - tenant-A access keeps working
  - `GET /clients` returns only tenant A
- [x] 1.4 GREEN: wire dependencies per design §2.
- [x] 1.5 RED/GREEN: `/tenants/{id}` and `/voice/signed-url` return 401 without a key.

## WU2 — Plans & entitlements (backend)

- [x] 2.1 RED: catalog + resolver tests (plan defaults, overrides merge, unknown plan → starter, override validation).
- [x] 2.2 GREEN: `app/entitlements/{catalog,service}.py`.
- [x] 2.3 Migration `0012_client_plan_entitlements` + model columns; migration test (existing rows → `pilot`).
- [x] 2.4 RED/GREEN: usage counters (monthly calls, monthly minutes, concurrent, active agents), month boundary in client timezone.
- [x] 2.5 RED/GREEN: Guard 1b in `dial_outbound_call` (feature + limits); router maps to 403/429; scheduler records `failure_code`.
- [x] 2.6 RED/GREEN: `require_feature` on analytics, live, CRM routes; `max_agents` on agent create.
- [x] 2.7 RED/GREEN: `GET/PUT /clients/{id}/entitlements`, `GET /entitlements/plans`.

## WU3 — Frontend entitlements

- [x] 3.1 API client + `useEntitlements` hook (tests).
- [x] 3.2 Sidebar gating + call-now gating (tests).
- [x] 3.3 Admin client page "Plan" section (tests).

## WU4 — Production hardening

- [x] 4.1 RED/GREEN: `QORA_ENV=production` validator (webhook auth, CORS, docs).
- [x] 4.2 Frontend: `/` and `*` → `/admin`.

## WU5 — Auth decision record

- [x] 5.1 `auth-decision.md`: options, recommendation, integration seam, migration plan.
