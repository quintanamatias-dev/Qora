# Design: Multi-Tenant Auth

This file is the contract between the backend and frontend work. Both sides
implement exactly what is written here. Change the contract here first.

## 1. Flow

```
Browser                    Qora backend                         WorkOS
  | GET /login (SPA page)        |                                  |
  | click "Iniciar sesión"       |                                  |
  |-- GET /api/v1/auth/login --->| set qora_auth_state cookie       |
  |<-- 302 authorize URL --------|                                  |
  |------------------------------------------ AuthKit hosted login ->|
  |<----------------- 302 /api/v1/auth/callback?code&state ----------|
  |-- GET /api/v1/auth/callback->| check state cookie               |
  |                              |-- POST /user_management/authenticate ->|
  |                              |<- user, organization_id, tokens -|
  |                              | map identity, create session row |
  |<-- 302 return_to + Set-Cookie qora_session (httpOnly) ----------|
  |-- GET /api/v1/... (cookie + X-Qora-Client: web) -->| session -> CallerIdentity
```

The WorkOS access/refresh tokens are used once at login and never stored,
except the WorkOS session id (`sid` claim of the access token, read without
signature verification because it came straight from the WorkOS API over TLS),
which is kept only to build the logout URL.

## 2. Settings (`app/core/config.py`)

| Env var | Field | Default | Notes |
|---|---|---|---|
| `WORKOS_API_KEY` | `workos_api_key: SecretStr \| None` | `None` | Server secret (`sk_...`). |
| `WORKOS_CLIENT_ID` | `workos_client_id: str \| None` | `None` | Public (`client_...`). |
| `QORA_AUTH_REDIRECT_URI` | `qora_auth_redirect_uri: str \| None` | `None` | Dev: `http://localhost:5173/api/v1/auth/callback` (through the Vite proxy). Must be registered in the WorkOS dashboard. |
| `QORA_SUPERADMIN_EMAILS` | `qora_superadmin_emails: str` | `""` | Comma-separated, case-insensitive. |
| `QORA_AUTH_SESSION_TTL_HOURS` | `qora_auth_session_ttl_hours: int` | `12` | Absolute session lifetime; must be >= 1. |

- `Settings.login_enabled` (property): all three of api key, client id and
  redirect URI are set.
- `Settings.auth_cookie_secure` (property): `qora_env == "production"` or the
  redirect URI starts with `https://`.
- `validate_production_hardening` adds: `WORKOS_API_KEY`, `WORKOS_CLIENT_ID`
  and `QORA_AUTH_REDIRECT_URI` must be set, and the redirect URI must start with
  `https://`.

## 3. Data model (Alembic `20260930_0013_multi_tenant_auth`)

- `clients.workos_organization_id`: `String`, nullable, unique.
- `auth_sessions` table (model in `app/auth/models.py`):

| Column | Type | Notes |
|---|---|---|
| `id` | `String` PK | uuid4 |
| `token_hash` | `String`, unique, indexed | SHA-256 hex of the cookie value. The raw token is never stored. |
| `workos_user_id` | `String` | |
| `email` | `String` | |
| `display_name` | `String`, nullable | "First Last" when available |
| `role` | `String` | `superadmin` \| `client` |
| `client_ids` | `Text` | JSON array snapshot taken at login |
| `workos_session_id` | `String`, nullable | For the logout URL |
| `created_at` | `DateTime(timezone=True)` | |
| `expires_at` | `DateTime(timezone=True)` | `created_at + TTL` |
| `revoked_at` | `DateTime(timezone=True)`, nullable | Set on logout |

Session token: `secrets.token_urlsafe(32)`.

## 4. Identity mapping (at callback)

1. `email.lower()` is in `QORA_SUPERADMIN_EMAILS` **and** `user.email_verified`
   is true → role `superadmin`, `client_ids = []`.
2. Otherwise `organization_id` from the authenticate response matches an
   **active** client's `workos_organization_id` → role `client`,
   `client_ids = [client.id]`.
3. Otherwise → no session; redirect `/login?error=no_access`.

AuthKit only proves identity and membership. Authorization stays in
`CallerIdentity` / `app.core.access` / entitlements. A superadmin keeps "no
plan bypass".

## 5. Cookies

| Name | Value | Attributes |
|---|---|---|
| `qora_session` | session token | `HttpOnly; SameSite=Lax; Path=/; Max-Age=TTL; Secure` when `auth_cookie_secure` |
| `qora_auth_state` | `secrets.token_urlsafe(24)` | `HttpOnly; SameSite=Lax; Path=/api/v1/auth; Max-Age=600` (+Secure) |
| `qora_auth_return` | sanitized `return_to` | same as above |

`return_to` sanitizing: must start with `/`, must not start with `//` or `/\`,
must not start with `/api/`, max 512 chars; otherwise `/`.

## 6. Authentication dependency (`app/core/auth.py`)

`require_api_key` keeps its name (routers unchanged) and becomes `async`, with
an extra `db: AsyncSession = Depends(get_session)` parameter. Order:

1. `_TESTING_BYPASS` → superadmin (unchanged).
2. `Authorization` header present → existing Bearer API-key logic, unchanged
   (401 on any problem). Returns `auth_method="api_key"`.
3. Else `qora_session` cookie present → look up `token_hash`, not revoked,
   `expires_at > now`. Missing/expired/revoked → 401
   `{"error": "authentication_required", "message": "Session expired or invalid"}`.
   For `POST|PUT|PATCH|DELETE`, the header `X-Qora-Client: web` is required,
   otherwise 403 `{"error": "csrf_check_failed", "message": "Missing X-Qora-Client header"}`
   (checked after the session is found).
4. Else → 401 `{"error": "authentication_required", "message": "Authentication required"}`.

`CallerIdentity` gains `auth_method: Literal["api_key", "session"] = "api_key"`
and `email: str | None = None`. For sessions, `api_key_hash` is
`"session:" + session.id[:8]` (audit only).

## 7. HTTP API — `/api/v1/auth` (router `app/auth/router.py`)

All error redirects go to the SPA route `/login?error=<code>`.

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/auth/config` | public | `200 {"login_enabled": bool}` |
| GET | `/auth/login?return_to=` | public | Not enabled → 302 `/login?error=auth_not_configured`. Else set state + return cookies, 302 to `https://api.workos.com/user_management/authorize?response_type=code&provider=authkit&client_id=..&redirect_uri=..&state=..` |
| GET | `/auth/callback?code&state` or `?error=` | public | Validate state cookie with `secrets.compare_digest` (`invalid_state`); WorkOS `error` param → `login_failed`; exchange code; `organization_selection_required` → that code; other WorkOS/network failure → `login_failed`; mapping failure → `no_access`. Success: create session, set `qora_session`, delete state cookies, 302 to the return cookie or `/`. |
| GET | `/auth/me` | `require_api_key` | `200 {"auth_method": "session"\|"api_key", "role": "superadmin"\|"client", "email": str\|null, "name": str\|null, "client_ids": [str]}` |
| POST | `/auth/logout` | public, cookie optional | Requires `X-Qora-Client: web` (403 as above). Revokes the session if found, clears `qora_session`. `200 {"logout_url": str\|null}`, where `logout_url` is `https://api.workos.com/user_management/sessions/logout?session_id=<sid>` when a sid is known. |

Error codes (frontend maps them to messages): `auth_not_configured`,
`invalid_state`, `login_failed`, `organization_selection_required`,
`no_access`.

WorkOS calls go through `app/auth/workos.py` (`httpx.AsyncClient`, base
`https://api.workos.com`, 10 s timeout, `Authorization: Bearer <api key>`).
Tests mock it with `respx`. Never log tokens, codes or the API key.

## 8. Superadmin access API — `/api/v1/clients/{client_id}/access`

All routes depend on `require_superadmin`. `503 {"error": "auth_not_configured"}`
when WorkOS is not configured, `404` for an unknown client, and
`502 {"error": "identity_provider_error"}` for WorkOS failures.

| Method | Path | Behavior |
|---|---|---|
| GET | `/access` | `200 AccessState` |
| POST | `/access/organization` | Idempotent. If linked, return state. Else `GET /organizations/external_id/{client_id}`; if 404, `POST /organizations {name: client.name, external_id: client.id}`. Store id. `200 AccessState` |
| POST | `/access/invitations` body `{"email": str}` | 409 `{"error": "organization_not_linked"}` if not linked. `POST /user_management/invitations {email, organization_id}`. `201 Invitation` |
| DELETE | `/access/invitations/{invitation_id}` | Fetch invitation; 404 unless it belongs to this org. `POST /user_management/invitations/{id}/revoke`. `204` |

```
AccessState = {
  "organization_id": str | null,
  "members": [{"user_id": str, "email": str, "name": str | null}],
  "invitations": [Invitation]   // only state == "pending"
}
Invitation = {"id": str, "email": str, "state": str, "expires_at": str}
```

Members: `GET /user_management/users?organization_id=<org>&limit=100`.
Invitations: `GET /user_management/invitations?organization_id=<org>&limit=100`.
Members/invitations are empty lists when not linked.

## 9. Frontend

- `apiFetch` (`src/api/client.ts`): delete `VITE_API_KEY`. Always send
  `X-Qora-Client: web` and `credentials: 'same-origin'`. On a 401 from any path
  except `/api/v1/auth/*`, call the registered unauthorized handler (redirects
  to `/login?return_to=<current path+search>`), then still throw `ApiError`.
- `src/api/auth.ts`: `getAuthConfig()`, `getMe()`, `logout()` (POST, then
  `window.location.assign(logout_url ?? '/login')`), and the query hook
  `useMe()` with key `['auth', 'me']`, no retry on 401.
- Routes:
  - `/login` (public, no layout): Qora-branded card, button "Iniciar sesión"
    → `window.location.assign('/api/v1/auth/login?return_to=' + encodeURIComponent(returnTo))`.
    Shows a message for `?error=`; shows "El inicio de sesión no está configurado"
    when `login_enabled` is false.
  - Everything else is wrapped in `RequireAuth`: loading state while `me` loads;
    401 → `/login?return_to=...`.
  - `/` and `*`: superadmin → `/admin`; client → `/app/{client_ids[0]}/dashboard`.
  - `/admin/*`: superadmin only; client → own dashboard.
  - `/app/:clientId/*`: superadmin any; client only for a `clientId` in
    `client_ids`, else own dashboard.
- User menu in both layouts: email + "Cerrar sesión".
- Admin client detail: "Acceso" section (link organization button, members
  list, pending invitations with revoke, invite-by-email form).
- UI copy is Spanish, matching the existing panel.
- MSW handlers for `/api/v1/auth/*` and `/access` in `tests/mocks`.
