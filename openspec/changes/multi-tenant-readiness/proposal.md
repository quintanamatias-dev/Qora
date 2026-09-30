# Proposal: Multi-Tenant Readiness (pre-deploy)

## Intent

Qora is multi-tenant in its **data** (every row carries `client_id`) and in its
**voice runtime** (sessions keyed by `(client_id, conversation_id)`, tool
dispatcher tenant check), but it is still single-tenant in its **access
model**:

| Gap | Evidence | Impact |
|---|---|---|
| One global admin key, shipped to the browser | `frontend/src/api/client.ts` reads `VITE_API_KEY`, which Vite inlines into the public bundle | Anyone who opens the panel can read and mutate every tenant |
| Tenant chosen by URL | `/app/:clientId` trusts the path | No user → client binding |
| ID-based routes skip ownership checks (IDOR) | `GET /calls/{id}`, `/transcript`, `/analysis`, `/status`, `POST /calls/{conv}/end`, `GET/PATCH /leads/{id}`, `/history`, `/context-preview` | Violates `phase-b-api-authentication/specs/tenant-isolation` "Direct resource access for unauthorized tenant" |
| Unauthenticated routes | `GET /tenants/{client_id}`, `GET /voice/signed-url` | Config disclosure; free ElevenLabs sessions against our account |
| No plans / entitlements | No per-client feature or usage limits | Cannot differentiate plans (docs/pricing.md) or cap cost exposure per tenant |
| Webhook auth optional in prod | `QORA_WEBHOOK_AUTH_ENABLED=false` default | Unauthenticated callers can burn OpenAI tokens on `/voice/*` |

This change closes every gap **except** end-user authentication itself, which
is designed here and delivered as a follow-up (`multi-tenant-auth`) once the
provider decision is made.

## Scope

### In Scope

1. **Tenant access layer** — `CallerIdentity` becomes a principal with a role
   (`superadmin` | `client`) and an allowed-tenant set. New dependencies:
   `require_client_access` (tenant in the path/query) and `require_superadmin`.
   Ownership helper for ID-based routes. The current API key maps to
   `superadmin`, so behaviour is unchanged today and every router is ready for
   a JWT-backed principal tomorrow.
2. **IDOR closure** — every ID-based route verifies the resource's `client_id`
   against the principal. Cross-tenant → 404 (no existence disclosure).
3. **Unauthenticated route closure** — `/tenants/{id}` and `/voice/signed-url`
   require auth.
4. **Plans & entitlements** — a code-owned plan catalog (`pilot`, `starter`,
   `pro`, `business`) with features and limits, a per-client `plan` plus JSON
   `entitlement_overrides`, a resolver, usage counters, and enforcement at the
   real chokepoints (`dial_outbound_call`, agent creation, CRM routes, analytics,
   live monitor). `GET /clients/{id}/entitlements` exposes
   plan + usage to the panel; `PUT` is superadmin-only.
5. **Frontend entitlements** — hook + nav/feature gating + plan editor in the
   admin client page.
6. **Production hardening** — fail startup when `QORA_ENV=production` without
   webhook auth; stop redirecting `/` to `demo-client`.
7. **Auth design** (document only) — build vs buy decision record.

### Out of Scope

| Non-goal | Why |
|---|---|
| Login, users table, JWT verification | Follow-up change `multi-tenant-auth`, blocked on provider decision (see design §Auth) |
| Billing / invoicing / overage charging | Roadmap E1; limits here are hard caps, not billing |
| Self-service signup | Onboarding requires ElevenLabs agent + number + prompt files; invitation-based onboarding is the agreed direction |
| Per-tenant OpenAI/ElevenLabs keys | Shared platform keys are acceptable for launch |
| PostgreSQL | Roadmap B3 |

## Settled Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Extend `CallerIdentity` instead of introducing a new type | Every admin router already depends on `require_api_key`; the docstring already reserves this as the Phase C seam. Zero signature churn. |
| 2 | Cross-tenant resource by ID → **404**; explicit foreign `client_id` → **403** | 404 on IDs avoids confirming a resource exists; 403 on an explicit tenant is honest and debuggable. Both allowed by the tenant-isolation spec. |
| 3 | Existing and new clients default to plan **`pilot`** (all features, no limits) | Preserves current behaviour for Quintana and all tests; paid plans are assigned explicitly by a superadmin. |
| 4 | Plans live in code; per-client overrides live in the DB | Plans change with product decisions and deserve review; overrides are operational and need no deploy. |
| 5 | Limits are **hard caps** enforced before dialing | Protects cost exposure now; overage billing is a later product decision. |
| 6 | Auto-dialer rows blocked by a plan limit are marked `failed` with `failure_code=plan_limit_reached` | Leaving them `pending` would re-claim and re-log every tick. |
| 7 | Inbound calls are never blocked by limits | Rejecting a live caller mid-initiation is worse than a small overage. |
