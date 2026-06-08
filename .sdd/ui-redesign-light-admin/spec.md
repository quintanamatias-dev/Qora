# Delta Specs: ui-redesign-light-admin

## Capability Map

| Capability | Type | Spec Sections |
|---|---|---|
| `design-system-tokens` | MODIFIED | §1 |
| `design-primitives` | MODIFIED | §2 |
| `dashboard` | MODIFIED | §3 |
| `admin-client-detail` | NEW | §4 |
| `integration-config` | NEW (backend) | §5 |
| `integrations-panel` | NEW (frontend) | §6 |

---

## §1 — Delta for `design-system-tokens`

## MODIFIED Requirements

### Requirement: Canvas Background Tokens

`tokens.css` MUST define `--bg` as `#F2F4F3` (Pearl) and `--bg-2` / `--surface` as `#FFFFFF` (Paper). Dark Obsidian surface tokens (`--color-background: #0c1324`, `--color-surface-container-*`) MUST be removed.
(Previously: dark Obsidian palette — `--color-background: #0c1324`, five dark surface containers)

#### Scenario: Light canvas renders on page load

- GIVEN the app loads with the updated `tokens.css`
- WHEN any page is rendered
- THEN the root background MUST be `#F2F4F3` (Pearl), not `#0c1324`

### Requirement: Ink Hierarchy Tokens

`tokens.css` MUST define `--ink` `#0E1217`, `--ink-2` `#44474D`, `--ink-3` `#767880`, `--ink-4` `#B5B7BC` as text tokens.
(Previously: `--color-on-surface: #e2e8f0` and `--color-on-surface-variant: #bbcabf`)

### Requirement: Brand Teal Tokens

`tokens.css` MUST include `--teal #1A8B7A`, `--teal-deep #0E4E45`, `--teal-bright #2EC9B0`, `--teal-navy #031A17`, `--teal-faint rgba(26,139,122,0.08)`, `--teal-line rgba(26,139,122,0.28)`. Startup-green primary (`--color-primary: #4edea3`) MUST be removed.
(Previously: `--color-primary: #4edea3` — startup green)

### Requirement: Accent Coral Tokens

`tokens.css` MUST include `--coral #E0764F`, `--coral-soft #FBE2D6`, `--coral-faint`, `--coral-line`. Purple secondary tokens (`--color-secondary: #d0bcff`) MUST be removed.
(Previously: purple secondary — `--color-secondary: #d0bcff`)

### Requirement: Shape Tokens

`tokens.css` MUST define `--r-sm: 6px`, `--r-md: 12px`, `--r-lg: 20px`, `--r-xl: 32px`, `--r-full: 999px`. The existing `--radius-DEFAULT: 0.25rem` (4px max, pills prohibited) MUST be removed.
(Previously: `--radius-DEFAULT: 0.25rem` with pill radii explicitly prohibited)

### Requirement: Shadow Tokens

`tokens.css` MUST define `--shadow-sm`, `--shadow-md`, `--shadow-lg`, `--shadow-xl` per design system §4.3. All shadows MUST use carbon with opacity — no colored shadows.
(Previously: no shadow tokens defined)

### Requirement: Font Stack Tokens

`tokens.css` MUST define `--font-display` as `'Fredoka'`, `--font-body` as `'Inter'`, `--font-mono` as `'JetBrains Mono'`. Manrope MUST be removed from all font stacks.
(Previously: `--font-display: 'Manrope'`, `--font-mono: ui-monospace, 'Cascadia Code'`)

#### Scenario: Correct fonts load

- GIVEN the app loads
- WHEN a heading (H1–H4) or large metric number is rendered
- THEN `font-family` resolves to `Fredoka`, not `Manrope`
- AND body text resolves to `Inter`
- AND mono/badge text resolves to `JetBrains Mono`

### Requirement: Hardcoded Colors Removed from globals.css

`globals.css` MUST NOT contain `background-color: #0c1324` or `color: #e2e8f0` on the `html, body` rule. Base colors MUST reference `var(--bg)` and `var(--ink)` tokens.
(Previously: `background-color: #0c1324; color: #e2e8f0` hardcoded on body)

#### Scenario: Token swap changes body background

- GIVEN only `tokens.css` is changed
- WHEN the page renders
- THEN `body` background reflects the new `--bg` value (Pearl)

### Requirement: Motion Tokens

`tokens.css` MUST define `--ease-out: cubic-bezier(.2,.8,.2,1)` and `--ease-inout: cubic-bezier(.4,0,.2,1)`.

**Constraints:**
- MUST NOT add warm/cream backgrounds (`#F6F5F0`, `#FAF7F0`, or any warm off-white)
- MUST NOT add startup-green variants
- MUST NOT include colored shadow values
- Dark mode tokens MAY be preserved under `[data-theme='dark']` for future use but are NOT required for this change

---

## §2 — Delta for `design-primitives`

## MODIFIED Requirements

### Requirement: Button Component — Solid Primary

The `<Button>` solid/primary variant MUST render with `background: var(--teal)`, `color: #ECFAF3`, `font: 500 14px/1 Inter`, `padding: 12px 22px`, `border-radius: var(--r-full)` (pill shape). Hover MUST apply `background: var(--teal-deep)` and `transform: translateY(-1px)`.
(Previously: dark surface background, square/minimal radius, Manrope font)

#### Scenario: Primary button renders as teal pill

- GIVEN the updated Button component
- WHEN a `variant="primary"` or solid button is rendered
- THEN border-radius equals `999px` (pill)
- AND background is `var(--teal)` (`#1A8B7A`)

### Requirement: Card Component

The `<Card>` MUST render with `background: var(--paper)` (`#FFFFFF`), `border: 1px solid var(--line)`, `border-radius: var(--r-lg)` (20px), `padding: 28px`, `box-shadow: var(--shadow-md)`.
(Previously: dark surface background, no border, minimal or no radius)

### Requirement: Input Component

The `<Input>` MUST render with `background: var(--paper)`, `border: 1px solid var(--line-2)`, `border-radius: var(--r-md)` (12px), `padding: 12px 16px`, `font: 400 16px/1.5 Inter`, `color: var(--ink)`. Focus MUST apply `border-color: var(--teal)` and `box-shadow: 0 0 0 3px var(--teal-faint)`.
(Previously: dark background, no visible focus ring beyond outline removal)

#### Scenario: Input focus state shows teal ring

- GIVEN the updated Input component
- WHEN the input receives keyboard focus
- THEN border color becomes `var(--teal)`
- AND a 3px teal-faint box-shadow appears

### Requirement: Badge Component

The `<Badge>` MUST render with `background: var(--teal-faint)`, `color: var(--teal)`, `border: 1px solid var(--teal-line)`, `border-radius: var(--r-full)`, `font: 500 11px/1 'JetBrains Mono'`, `letter-spacing: 0.20em`, `text-transform: uppercase`.
(Previously: no mono font, potentially square radius)

### Requirement: Table Component

The `<Table>` MUST render on `var(--paper)` background with `1px solid var(--line)` row separators. Header row MUST use `var(--ink-3)` text with `var(--t-mono)` styling (JetBrains Mono uppercase).
(Previously: dark surface background)

### Requirement: Sidebar Component

The `<Sidebar>` MUST render with `var(--bg)` or `var(--surface)` background (light). Active navigation item MUST use `var(--teal)` color and `var(--teal-faint)` background highlight.
(Previously: dark surface background)

### Requirement: TopBar Component

The `<TopBar>` MUST render with `var(--paper)` or `var(--bg)` background with `var(--shadow-sm)` bottom border. The Qora wordmark MUST render in Fredoka 500, color `var(--ink)` or `var(--teal)`.
(Previously: dark background)

**Constraints:**
- MUST NOT change component props, data attributes, or behavior contracts
- MUST NOT add new props — visual changes only (CSS/className)
- Existing test selectors (data-testid, aria-*) MUST remain unchanged

---

## §3 — Delta for `dashboard`

## MODIFIED Requirements

### Requirement: Dashboard Page Background

All dashboard pages and layout wrappers MUST render on `var(--bg)` (Pearl) backgrounds, not dark surfaces. No `#0c1324`, `#151b2d`, or equivalent dark values MAY remain.
(Previously: Obsidian dark backgrounds)

### Requirement: StatCard Metric Display

`<StatCard>` metric numbers MUST use Fredoka 500, large size (≥32px). Labels MUST use Inter 400, `var(--ink-3)`. The card MUST use the updated `<Card>` component (Paper bg, r-lg, shadow-md).
(Previously: dark card surface, Manrope font for metrics)

#### Scenario: StatCard renders with Fredoka metric

- GIVEN the updated StatCard
- WHEN a numeric metric is displayed (e.g. "142 llamadas")
- THEN the number renders in Fredoka font family
- AND the card background is `var(--paper)` (`#FFFFFF`)

### Requirement: MetricsGrid Spacing

`<MetricsGrid>` MUST use `gap: 16px` or `gap: 24px` between cards. No margin-based layout.
(Previously: potentially tighter or margin-based gaps)

### Requirement: PeriodSelector Style

The `<PeriodSelector>` MUST render as a pill-style selector using `var(--r-full)` for the active option and `var(--teal)` for the selected state background.
(Previously: dark tab style)

**Constraints:**
- MUST NOT change any data-fetching, state logic, or API calls
- MUST NOT change prop interfaces or component composition
- Dashboard logic changes are out of scope for this change

---

## §4 — New Spec for `admin-client-detail`

## Requirements

### Requirement: Client Detail Route

The application MUST register a route at `/admin/clients/:clientId`. Navigating to this route MUST render a `<ClientDetailPage>` component.

#### Scenario: Route resolves for valid client

- GIVEN the admin is authenticated
- WHEN the user navigates to `/admin/clients/quintana-seguros`
- THEN `<ClientDetailPage>` renders with `clientId = "quintana-seguros"`

#### Scenario: Back navigation returns to client list

- GIVEN the user is on `/admin/clients/quintana-seguros`
- WHEN the user activates the back navigation control
- THEN the route changes to `/admin`

### Requirement: Client List Entry Point

The `/admin` route MUST display clients as a list or card grid. Each client entry MUST be clickable/navigable to `/admin/clients/:clientId`.

#### Scenario: Client card navigates to detail

- GIVEN the admin list shows clients
- WHEN the user clicks a client card
- THEN the router navigates to `/admin/clients/:clientId`
- AND URL state replaces the local dropdown/tab state

### Requirement: Client Detail Layout

`<ClientDetailPage>` MUST render: (1) a client info header (name, ID), (2) an Agents section, (3) an Integrations section. Each section MAY be collapsible.

### Requirement: Agents Section in Detail

The Agents section MUST list all agents for the given `clientId`. Each agent MUST have an edit control. A "New agent" or "Add agent" action MUST be present.

#### Scenario: Agent list renders for client

- GIVEN the user is on `/admin/clients/quintana-seguros`
- WHEN the Agents section loads
- THEN all agents configured under `quintana-seguros` are listed

### Requirement: URL-Based State Management

Admin navigation MUST use URL route params (`/admin/clients/:clientId`) as the source of truth. Local dropdown or tab state for client selection MUST be removed.
(This is a NEW capability — no existing behavior to reference)

**Constraints:**
- MUST NOT remove the existing `/admin` route
- Existing agent edit flows MUST remain functional after refactor
- No auth logic changes are in scope

---

## §5 — New Spec for `integration-config`

## Requirements

### Requirement: List Integrations Endpoint

`GET /api/v1/clients/{client_id}/integrations` MUST return an array of integration objects for the given client. If no `crm.yaml` exists for the client, MUST return `[]`. If `crm.yaml` exists, MUST return one entry with: `provider`, `status` (`connected` | `disconnected`), `masked_token` (last 4 chars of actual token, e.g. `••••••••a3f9`).

#### Scenario: Client with crm.yaml returns integration

- GIVEN `quintana-seguros` has a `crm.yaml` with `provider: airtable` and `api_key_env: QUINTANA_AIRTABLE_API_KEY`
- WHEN `GET /api/v1/clients/quintana-seguros/integrations` is called
- THEN the response is `[{ "provider": "airtable", "status": "connected", "masked_token": "••••a3f9" }]`
- AND the actual token value is NOT present in the response

#### Scenario: Client without crm.yaml returns empty array

- GIVEN a client has no `crm.yaml`
- WHEN `GET /api/v1/clients/{client_id}/integrations` is called
- THEN the response is `[]` with HTTP 200

#### Scenario: Connected status requires env var set

- GIVEN `crm.yaml` exists with `api_key_env: SOME_KEY`
- WHEN the env var `SOME_KEY` is not set
- THEN `status` in the response MUST be `"disconnected"`

### Requirement: Save Integration Config Endpoint

`PUT /api/v1/clients/{client_id}/integrations/{provider}` MUST accept a JSON body with `{ "api_key": "<token_value>" }`. The endpoint MUST store the token as an env var NAME in `crm.yaml` (e.g., `CLIENT_AIRTABLE_API_KEY`) and write the actual value to the `.env` file. MUST return the masked token (never the raw value).

#### Scenario: Save persists token securely

- GIVEN a PUT request with `{ "api_key": "patXXXXXXXXXXXXXXXX" }`
- WHEN the endpoint processes the request
- THEN `crm.yaml` is updated with `api_key_env: <CLIENT_PROVIDER_API_KEY>` (env var name)
- AND the actual token value is written to `.env`
- AND the response contains `masked_token` (last 4 chars), not the full token

### Requirement: Test Integration Connection Endpoint

`POST /api/v1/clients/{client_id}/integrations/{provider}/test` MUST attempt to connect to the provider using the stored token. MUST return `{ "success": true }` on success or `{ "success": false, "error": "<reason>" }` on failure.

#### Scenario: Test returns success for valid token

- GIVEN a valid Airtable token is stored for the client
- WHEN `POST /api/v1/clients/{client_id}/integrations/airtable/test` is called
- THEN response is `{ "success": true }` with HTTP 200

#### Scenario: Test returns error for invalid token

- GIVEN an invalid or expired token is stored
- WHEN the test endpoint is called
- THEN response is `{ "success": false, "error": "Authentication failed" }` with HTTP 200 (not 5xx)

**Constraints:**
- MUST NOT return the actual token value in any response
- MUST NOT modify existing CRM sync endpoints
- Token storage pattern MUST be consistent with existing `crm.yaml` + `.env` convention

---

## §6 — New Spec for `integrations-panel`

## Requirements

### Requirement: Empty State

When a client has no integrations configured, the Integrations panel MUST display a "No integrations configured" empty state with a subtle icon. No error state MUST be shown for empty data.

#### Scenario: Empty state renders for new client

- GIVEN the client has no `crm.yaml`
- WHEN the Integrations section loads
- THEN "No integrations configured" text is displayed
- AND no error toast is shown

### Requirement: Connected Integration Card

When a client has an integration configured, the panel MUST display a card with: provider icon (Airtable), provider name, and a green badge/checkmark indicating `connected` status.

#### Scenario: Connected card shows provider and status

- GIVEN `quintana-seguros` has a connected Airtable integration
- WHEN the Integrations section loads
- THEN an Airtable card renders with `connected` indicator (green)

### Requirement: Expandable Config Form

Clicking the integration card MUST expand/reveal a config form with: (1) a masked API token input (default hidden, show/hide toggle), (2) a Save button, (3) a Test Connection button.

#### Scenario: Token input defaults to masked

- GIVEN the integration card is expanded
- WHEN the config form renders
- THEN the token input shows masked characters, not the raw token
- AND a reveal/hide toggle is visible

### Requirement: Save Integration Token

Clicking Save MUST call `PUT /api/v1/clients/{client_id}/integrations/{provider}` with the entered token. On success, MUST display a success toast. On failure, MUST display an error toast.

#### Scenario: Save shows success toast

- GIVEN the user enters a token and clicks Save
- WHEN the PUT request succeeds
- THEN a success toast is displayed
- AND the input reverts to masked state

### Requirement: Test Connection Action

Clicking Test Connection MUST call `POST /api/v1/clients/{client_id}/integrations/{provider}/test`. On success, MUST show a success toast. On failure, MUST show an error toast with the error reason.

#### Scenario: Test failure shows error reason

- GIVEN the stored token is invalid
- WHEN the user clicks Test Connection
- THEN an error toast appears with the reason from the API response

**Constraints:**
- MUST NOT expose the raw token value in the UI after save
- MUST NOT add OAuth flows — token input only
- Integrations panel MUST be rendered within `<ClientDetailPage>`, not as a standalone route
