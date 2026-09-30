# Design: Multi-Tenant Readiness

## 1. Principal model

```python
@dataclass
class CallerIdentity:
    api_key_hash: str                      # audit only (unchanged)
    role: Literal["superadmin", "client"] = "superadmin"
    client_ids: frozenset[str] = frozenset()   # only meaningful for role="client"

    @property
    def is_superadmin(self) -> bool: ...
    def can_access(self, client_id: str | None) -> bool: ...
```

- `require_api_key` keeps its name and contract and returns a `superadmin`
  principal (the global key is an operator credential).
- The follow-up auth change adds `require_principal`, which accepts either the
  operator key or a user token and returns a `client` principal for tenant
  users. Routers depend on the dependencies below, never on the credential type.

### Dependencies (`app/core/access.py`)

| Dependency | Resolves | Fails |
|---|---|---|
| `require_client_access(client_id, caller)` | `client_id` from path **or** query (FastAPI resolves by name) | 403 `tenant_forbidden` |
| `require_superadmin(caller)` | — | 403 `superadmin_required` |
| `ensure_resource_access(caller, resource_client_id)` | plain function for ID-based routes after loading the row | 404 (same body as "not found") |

`client_id` comparison is case-insensitive, matching `analytics/router.py`,
which lower-cases the path value.

## 2. Route policy

| Router | Client principal | Superadmin only |
|---|---|---|
| `clients` | `GET /clients/{id}` | list, create, patch, delete |
| `agents` | list, get | create, patch, sync, deactivate, make-default |
| `crm_config_router` (integrations) | list, available, fields | put, test, mappings, connect, disconnect |
| `crm_router` | import | — |
| `leads` | all (list/create scoped by `client_id`; ID routes ownership-checked) | — |
| `calls` | list, metrics, active (scoped); ID routes ownership-checked | `POST /calls/{conversation_id}/end` (operator tool; no panel uses it) |
| `analytics`, `scheduler`, `outbound` | all (scoped by path `client_id`) | — |
| `tenants` | `GET /tenants/{id}` (was **unauthenticated**) | — |
| `voice/signed-url` | — | yes (was **unauthenticated**; unused by any UI) |
| `entitlements` | `GET /clients/{id}/entitlements` | `PUT` |
| `demo`, `voice` webhooks | unchanged (public by design / webhook secret) | — |

`GET /clients` returns only the accessible tenants for a client principal
instead of 403, so the panel can resolve "my tenant" with the same endpoint.

## 3. Plans & entitlements

### Catalog (`app/entitlements/catalog.py`)

Features (boolean):

| Key | Gates |
|---|---|
| `outbound_calls` | Manual "Call now" (`dial_outbound_call` with `scheduled_call=None`) |
| `auto_dialer` | Auto-dialer (`dial_outbound_call` with a `ScheduledCall`) |
| `crm_integration` | `crm_config_router`, `crm_router` (CRM import). CSV import is not gated: it uses the same `POST /leads` as manual lead creation. |
| `analytics` | `/analytics/*` |
| `live_monitor` | `GET /calls/active` |

Limits (`int | None`, `None` = unlimited):

| Key | Counted as | Enforced at |
|---|---|---|
| `max_agents` | active agents for the client | `POST /clients/{id}/agents` |
| `max_concurrent_calls` | client sessions in `{dialing, ringing, connected}` | `dial_outbound_call` |
| `max_monthly_calls` | `CallSession` rows started this calendar month (client TZ) | `dial_outbound_call` |
| `max_monthly_minutes` | `ceil(sum(duration_seconds)/60)` this month | `dial_outbound_call` |

Plans (from `docs/pricing.md` §4):

| | pilot | starter | pro | business |
|---|---|---|---|---|
| outbound_calls | ✓ | ✓ | ✓ | ✓ |
| auto_dialer | ✓ | ✗ | ✓ | ✓ |
| crm_integration | ✓ | ✗ | ✓ | ✓ |
| analytics | ✓ | ✓ | ✓ | ✓ |
| live_monitor | ✓ | ✗ | ✓ | ✓ |
| max_agents | ∞ | 1 | 3 | 10 |
| max_concurrent_calls | ∞ | 1 | 3 | 10 |
| max_monthly_minutes | ∞ | 200 | 1000 | 5000 |
| max_monthly_calls | ∞ | ∞ | ∞ | ∞ |

`pricing.md` lists "Analysis: Basic/Full" and "CRM: Webhook/Airtable/Custom";
only the enforceable subset is modelled. Values are product defaults and can be
edited in one reviewed file.

### Storage

Migration `0012_client_plan_entitlements`:

- `clients.plan` `String NOT NULL server_default 'pilot'`
- `clients.entitlement_overrides` `Text NULL` — JSON
  `{"features": {key: bool}, "limits": {key: int|null}}`

Overrides are validated against the catalog on write (unknown keys → 422).

### Resolution

`resolve_entitlements(client) -> Entitlements(plan, features, limits)` =
plan defaults ⊕ overrides. Unknown plan in DB (manual edit) falls back to
`starter` (fail-closed to the most restrictive paid plan) and logs
`entitlements_unknown_plan`.

### Enforcement

- **HTTP gates**: `require_feature(key)` is a dependency factory built on
  `require_client_access`. It loads the client and returns 403
  `{"error": "feature_not_in_plan", "feature": key}`.
- **Dial gate**: new Guard 1b in `dial_outbound_call`, after the tenant
  ownership guard and the global `ENABLE_OUTBOUND_CALLS` flag, before any
  `CallSession` is created. It returns a `DialResult` with
  `failure_code="plan_feature_disabled"` or `"plan_limit_reached"`. The outbound
  router maps these to 403 and 429. The scheduler already marks non-dialing
  results `failed` and logs the `failure_code` (decision 6).
- **Agent gate**: `create_agent` counts active agents → 403 `plan_limit_reached`.
  The default agent provisioned by `create_client` counts toward the limit.
- **Known gap**: the concurrency cap is checked, not reserved. Two dials that
  start at the same instant for different leads can both pass. The per-lead
  lock and the provider's own concurrency limit bound the impact. A DB-level
  reservation belongs with Postgres (B3).

### API

- `GET /clients/{id}/entitlements` → `{plan, features, limits, usage, overrides}`
- `PUT /clients/{id}/entitlements` (superadmin) → body `{plan, overrides}`
- `GET /entitlements/plans` (superadmin) → catalog for the admin editor

## 4. Frontend

- `useEntitlements(clientId)` (TanStack Query).
- Sidebar hides Analytics / En vivo / Importar when the feature is off. Call-now
  is disabled with a tooltip when `outbound_calls` is off.
- Admin client page: "Plan" section with plan select, per-feature toggles, and
  limit inputs; shows current month usage.
- `/` and `*` redirect to `/admin` (superadmin panel) instead of the
  hard-coded `demo-client`. The follow-up auth change will redirect to the
  user's tenant.

## 5. Production hardening

- `QORA_ENV` setting (`development` default). When `production`:
  `QORA_WEBHOOK_AUTH_ENABLED=true` required, `QORA_ALLOWED_ORIGINS` must not be
  `*`, and `QORA_DOCS_ENABLED` must be false. Startup aborts otherwise, same
  pattern as `validate_outbound_requires_webhook_auth`.

## 6. Auth (decision record — delivered by `multi-tenant-auth`)

See `auth-decision.md`.
