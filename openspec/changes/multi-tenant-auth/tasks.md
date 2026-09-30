# Tasks: Multi-Tenant Auth

Contract: `design.md`. Strict TDD (RED → GREEN) for every behavior.

## Backend A1 — login core

- [ ] Settings fields, `login_enabled`, `auth_cookie_secure`, production guard (design §2)
- [ ] Alembic migration + `AuthSession` model + `Client.workos_organization_id` (§3)
- [ ] `app/auth/workos.py` client: authorize URL, authenticate, logout URL (§7)
- [ ] Identity mapping + session create/lookup/revoke (§4, §5)
- [ ] `require_api_key` cookie path + CSRF header check; `CallerIdentity` fields (§6)
- [ ] `/api/v1/auth` router: config, login, callback, me, logout (§7)

## Backend A2 — superadmin access API

- [ ] WorkOS organizations, users, invitations calls (§8)
- [ ] `/api/v1/clients/{client_id}/access` routes (§8)

## Frontend B1 — login

- [x] `apiFetch` without `VITE_API_KEY`, `X-Qora-Client`, 401 handler (§9)
- [x] `src/api/auth.ts` + MSW handlers
- [x] `/login` page, `RequireAuth`, role-based routing, user menu + logout

## Frontend B2 — access admin

- [x] Access API hooks + "Acceso" section in the client detail page

## Close-out

- [ ] Full backend + frontend suites, lint, build
- [ ] Independent security review
- [ ] Docs: `.env.example`, `docs/running-locally.md`, `docs/ROADMAP.md`
