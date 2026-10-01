# Proposal: Multi-Tenant Auth (WorkOS AuthKit login)

## Intent

`multi-tenant-readiness` shipped the authorization layer (`CallerIdentity`,
tenant access helpers, plans). The browser still authenticates with the global
`QORA_API_KEY`, which Vite inlines into the public bundle through
`VITE_API_KEY`. Anyone who opens the panel can extract it and act as a
superadmin on every tenant. Qora cannot be deployed publicly until that key
leaves the browser.

This change adds real user login with WorkOS AuthKit (decision:
`openspec/changes/multi-tenant-readiness/auth-decision.md`) and removes
`VITE_API_KEY` from the frontend.

## Scope

### In Scope

1. **Server-side login flow**: backend-driven AuthKit authorization-code flow.
   The backend exchanges the code with the WorkOS API key and issues its own
   opaque, httpOnly session cookie. No tokens reach browser JavaScript.
2. **Identity mapping**: a WorkOS organization maps to one Qora client through
   `clients.workos_organization_id`. Verified emails listed in
   `QORA_SUPERADMIN_EMAILS` map to the superadmin role.
3. **Cookie-aware `require_api_key`**: the existing dependency accepts either
   the Bearer API key (unchanged, superadmin, for scripts/ops) or a session
   cookie. Routers stay unchanged.
4. **Admin-provisioned access**: superadmin API + UI to link a client to a
   WorkOS organization and invite users by email (WorkOS sends the email).
5. **Frontend**: login page, auth guard, role-based routing, logout, and
   removal of `VITE_API_KEY`.
6. **Production guard**: `QORA_ENV=production` requires WorkOS settings and an
   https redirect URI.

### Out of Scope

- Removing member users from an organization (use the WorkOS dashboard).
- Users that belong to several Qora clients at once (first mapped org wins at
  login; organization switching is a follow-up).
- Revoking other users' live sessions from the UI (sessions expire after
  `QORA_AUTH_SESSION_TTL_HOURS`).
- Postgres, deploy (B2).

## Rollout

1. Merge with WorkOS unset: the API key keeps working for scripts; the panel
   shows "login not configured" until WorkOS env vars are present.
2. Operator registers the redirect URI in the WorkOS dashboard and sets
   `WORKOS_API_KEY`, `WORKOS_CLIENT_ID`, `QORA_AUTH_REDIRECT_URI`,
   `QORA_SUPERADMIN_EMAILS`.
3. Operator links each client to an organization and invites its users.

## Rollback

Revert the merge. `alembic downgrade -1` drops `auth_sessions` and
`clients.workos_organization_id`. Scripts using the API key are unaffected
throughout.
