# Design: UI Redesign — Light Admin

## Technical Approach

Replace the current "Sovereign Interface" dark theme (Obsidian palette + Manrope + Material naming) with the canonical Qora Design System (Pearl/Paper light base + Fredoka/Inter/JetBrains Mono + Qora-native tokens). Restructure admin from flat tab layout to route-based client drill-down. Add integrations API exposing `crm.yaml` config via REST.

This is a token-first migration: changing `tokens.css` flips the entire palette at once, then each component is refined individually to match the design system's border-radius, shadows, and font specifications.

## Architecture Decisions

### Decision: Token Naming Convention

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Keep Material names (`surface-container-low`, `on-surface`, `primary`) mapped to Qora values | Zero component class changes; naming is misleading (no Material involved) | **Rejected** |
| Switch to Qora-native names (`pearl`, `paper`, `teal`, `ink`, `mist`, `smoke`) | Every component Tailwind class must be updated; names match design system 1:1 | **Chosen** |

**Rationale**: The design system document uses Qora-native names exclusively (sections 1 & 10). Material naming creates a translation layer that causes bugs. One-time migration cost, permanent clarity. The `@theme` block in `tokens.css` IS the single source of truth — class names throughout components will use `bg-pearl`, `text-ink`, `border-line`, etc.

### Decision: Font Loading

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Self-hosted woff2 | Full offline control; must manage files; current approach | **Rejected** |
| Google Fonts CDN | Design system section 11 specifies this exactly; faster global delivery; no font file management | **Chosen** |

**Rationale**: Design system section 11 provides the exact `<link>` tag. Self-hosted woff2 for Fredoka + JetBrains Mono would require sourcing and managing 10+ font files. CDN matches spec with `display=swap`.

### Decision: Admin Route Architecture

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Keep flat tabs in `/admin` | Simple but won't support deep-linking to clients; integrations panel has nowhere to live per-client | **Rejected** |
| Route-based: `/admin` → client list, `/admin/clients/:clientId` → detail | URL-addressable; browser back works; sections are scoped to a client | **Chosen** |

Client detail uses **stacked sections with Disclosure** (expand/collapse). Agents and Integrations are collapsible panels within the detail page — one scroll, no tab switching, everything visible.

### Decision: Integrations Backend

| Option | Tradeoff | Decision |
|--------|----------|----------|
| New DB table for integrations | Schema migration; adds storage layer; crm.yaml becomes stale | **Rejected** |
| Read/write crm.yaml via API | Extends existing pattern; zero migration; YAML is already the config source | **Chosen** |

API key stays as env var reference (`api_key_env`). New endpoints read/write `crm.yaml`, validate structure, and test connectivity. No secrets stored or transmitted.

### Decision: Border Radius Migration

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Keep 4px max (current Sovereign) | Violates Qora design system (requires 6px–999px scale) | **Rejected** |
| Adopt full Qora radius scale (`r-sm` 6px through `r-full` 999px) | Major visual change; buttons become pills; cards get 20px radius | **Chosen** |

**Rationale**: Design system section 4.1 is explicit. Buttons use `r-full` (999px = pill), cards use `r-lg` (20px), inputs use `r-md` (12px).

## Data Flow

```
Integrations Config Flow:

  crm.yaml (filesystem)
       │
       ▼
  crm_config_router.py ──── GET  /api/v1/clients/{id}/integrations
       │                     PUT  /api/v1/clients/{id}/integrations
       │                     POST /api/v1/clients/{id}/integrations/test
       ▼
  Frontend API layer (integrations.ts)
       │
       ▼
  useIntegrationConfig() hook (TanStack Query)
       │
       ▼
  IntegrationsSection (inside ClientDetailPage)
```

```
Admin Route Flow:

  /admin ──→ AdminLayout ──→ Outlet
                              ├── index ──→ AdminClientsListPage
                              └── clients/:clientId ──→ ClientDetailPage
                                                         ├── AgentsSection
                                                         └── IntegrationsSection
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/design/tokens.css` | **Rewrite** | Replace Material/Obsidian tokens with Qora Design System tokens (section 10). New naming: `--color-pearl`, `--color-paper`, `--color-teal`, `--color-ink`, etc. Add radius scale, shadow scale, motion easings, layout tokens. |
| `frontend/src/design/globals.css` | **Modify** | Remove Manrope `@font-face` blocks. Add Google Fonts `@import` for Fredoka + Inter + JetBrains Mono. Update base body styles: `background-color: #F2F4F3` (Pearl), `color: #0E1217` (Ink). Add teal focus ring (`box-shadow: 0 0 0 3px var(--teal-faint)`) to `:focus-visible`. |
| `frontend/index.html` | **Modify** | Add Google Fonts preconnect + stylesheet `<link>` tags per design system section 11. Remove self-hosted font references if any. |
| `frontend/src/design/components/button.tsx` | **Modify** | Variants: `primary` → solid teal bg + `r-full` pill + white text. `secondary` → ghost with `border-line-2` + `r-full`. `tertiary` → no border, `text-ink-2`. Remove gradient. |
| `frontend/src/design/components/card.tsx` | **Modify** | `bg-paper` + `border border-line` + `rounded-lg` (20px) + `shadow-md` + `p-7`. Remove `stripe` prop (Qora prohibits left-border-color accent, anti-pattern #21). |
| `frontend/src/design/components/input.tsx` | **Modify** | `bg-paper` + `border border-line-2` + `rounded-md` (12px). Focus: `border-teal` + `shadow-[0_0_0_3px_var(--color-teal-faint)]`. Remove violet focus glow. |
| `frontend/src/design/components/badge.tsx` | **Modify** | Add `teal` status (teal-faint bg + teal text + teal-line border). Use `r-full` (pill). Add `font-mono` + `text-[11px]` + `uppercase tracking-[0.20em]` per badge/pill spec section 5.4. |
| `frontend/src/design/components/tabs.tsx` | **Modify** | Container: `bg-mist` + `rounded-md`. Active: `bg-paper text-ink font-semibold`. Inactive: `text-ink-2 hover:text-ink`. |
| `frontend/src/design/components/table.tsx` | **Modify** | Head: `bg-mist text-ink-3`. Rows: `border-b border-line`. Hover: `bg-pearl/50`. Text: `text-ink`. |
| `frontend/src/design/components/select.tsx` | **Modify** | Same treatment as input: `bg-paper` + `border-line-2` + `rounded-md`. Focus: teal ring. |
| `frontend/src/design/components/checkbox.tsx` | **Modify** | `accent-teal`. Label: `text-ink`. |
| `frontend/src/design/components/textarea.tsx` | **Modify** | Same treatment as input. |
| `frontend/src/design/components/toast.tsx` | **Modify** | `bg-paper` + `border border-line` + `rounded-lg` + `shadow-lg`. Success: teal dot. Error: coral dot. |
| `frontend/src/design/components/sidebar.tsx` | **Modify** | `bg-paper` + `border-r border-line`. Active: `bg-teal-faint text-teal font-medium`. Remove left-stripe pattern. Brand area: Fredoka wordmark "Qora" in `text-teal`. |
| `frontend/src/design/components/top-bar.tsx` | **Modify** | `bg-paper` + `border-b border-line`. Brand: Fredoka 500 `text-ink` (or `text-teal` for accent). |
| `frontend/src/design/components/page-container.tsx` | **Modify** | `bg-pearl`. |
| `frontend/src/app-layout.tsx` | **Modify** | `bg-pearl` base. |
| `frontend/src/features/dashboard/page.tsx` | **Modify** | Update heading: `font-display` → Fredoka. `text-ink` for heading, `text-ink-2` for subtitle. `text-teal` for client accent. |
| `frontend/src/features/dashboard/stat-card.tsx` | **Modify** | `bg-paper` + `rounded-lg` + `border border-line` + `shadow-md`. Accent: `text-teal` for primary, `text-coral` for error. Display value: Fredoka. |
| `frontend/src/features/dashboard/metrics-grid.tsx` | **Modify** | Token class updates (no structural change). |
| `frontend/src/features/dashboard/status-breakdown.tsx` | **Modify** | Completed bar: `bg-teal`. Abandoned: `bg-coral`. Background: `bg-mist`. |
| `frontend/src/features/dashboard/period-selector.tsx` | **Modify** | Active: `bg-teal-faint text-teal`. Inactive: `text-ink-3`. |
| `frontend/src/features/admin/admin-layout.tsx` | **Modify** | `bg-pearl` base. Header: `bg-paper border-b border-line`. Brand: Fredoka "Qora" + teal badge. Widen max-width to `max-w-6xl` for detail pages. |
| `frontend/src/features/admin/page.tsx` | **Rewrite → AdminClientsListPage** | Remove tab navigation. Render client list as table with clickable rows → navigates to `/admin/clients/:clientId`. Keep create-client form. |
| `frontend/src/features/admin/clients-panel.tsx` | **Delete** | Absorbed into `AdminClientsListPage`. |
| `frontend/src/features/admin/agents-panel.tsx` | **Modify → AgentsSection** | Remove client selector (clientId comes from route param). Wrap in Disclosure (collapsible). Token updates. |
| `frontend/src/features/admin/client-detail-page.tsx` | **Create** | Container component: reads `:clientId` from route. Renders header with client info + breadcrumb. Stacked sections: `<AgentsSection>` and `<IntegrationsSection>`. |
| `frontend/src/features/admin/integrations-section.tsx` | **Create** | Displays current CRM config (provider, base_id, table_id, field count, api_key_env). Edit form. Test connection button. |
| `frontend/src/router.tsx` | **Modify** | Add routes: `/admin/clients/:clientId` → `ClientDetailPage`. Import new components. |
| `frontend/src/api/integrations.ts` | **Create** | `fetchIntegrationConfig()`, `updateIntegrationConfig()`, `testIntegrationConnection()` typed API functions. |
| `frontend/src/api/types.ts` | **Modify** | Add `IntegrationConfig`, `UpdateIntegrationPayload`, `IntegrationTestResult` interfaces. |
| `frontend/src/api/hooks.ts` | **Modify** | Add `useIntegrationConfig()`, `useUpdateIntegration()`, `useTestIntegration()` hooks. |
| `frontend/src/api/index.ts` | **Modify** | Add `export * from './integrations'`. |
| `backend/app/integrations/crm_config_router.py` | **Create** | Three endpoints: `GET /api/v1/clients/{client_id}/integrations` reads crm.yaml → JSON. `PUT /api/v1/clients/{client_id}/integrations` writes validated config → crm.yaml. `POST /api/v1/clients/{client_id}/integrations/test` attempts Airtable API call with 1-record limit. |
| `backend/app/main.py` | **Modify** | Register `crm_config_router` on the API. |
| `frontend/public/fonts/` | **Delete contents** | Remove Manrope + Inter woff2 files (replaced by CDN). |

## Interfaces / Contracts

### New Token Mapping (tokens.css @theme)

```css
@theme {
  /* Canvas */
  --color-pearl: #F2F4F3;
  --color-paper: #FFFFFF;
  --color-mist: #E8ECEB;
  --color-smoke: #D6DAD9;

  /* Ink hierarchy */
  --color-ink: #0E1217;
  --color-ink-2: #44474D;
  --color-ink-3: #767880;
  --color-ink-4: #B5B7BC;

  /* Brand */
  --color-teal: #1A8B7A;
  --color-teal-deep: #0E4E45;
  --color-teal-bright: #2EC9B0;
  --color-teal-faint: rgba(26,139,122,0.08);
  --color-teal-line: rgba(26,139,122,0.28);

  /* Accent */
  --color-coral: #E0764F;
  --color-coral-soft: #FBE2D6;
  --color-coral-faint: rgba(224,118,79,0.09);
  --color-coral-line: rgba(224,118,79,0.30);

  /* Lines */
  --color-line: rgba(14,18,23,0.08);
  --color-line-2: rgba(14,18,23,0.14);
  --color-line-3: rgba(14,18,23,0.24);

  /* Status (semantic aliases) */
  --color-success: #1A8B7A;
  --color-warning: #f59e0b;
  --color-error: #E0764F;

  /* Typography */
  --font-display: 'Fredoka', ui-rounded, system-ui, sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;

  /* Radius */
  --radius-sm: 6px;
  --radius-DEFAULT: 12px;
  --radius-md: 12px;
  --radius-lg: 20px;
  --radius-xl: 32px;
  --radius-full: 999px;

  /* Shadows */
  --shadow-sm: 0 1px 0 rgba(14,18,23,0.08);
  --shadow-md: 0 12px 28px rgba(14,18,23,0.06);
  --shadow-lg: 0 24px 60px -45px rgba(14,18,23,0.30);
  --shadow-xl: 0 30px 70px -40px rgba(14,18,23,0.35);

  /* Layout */
  --spacing-sidebar: 14rem;
  --spacing-topbar: 3.5rem;
}
```

### Integration API Contract

```typescript
// GET /api/v1/clients/{client_id}/integrations → IntegrationConfig
interface IntegrationConfig {
  provider: string            // "airtable"
  base_id: string             // "appXXX"
  table_id: string            // "tblXXX"
  api_key_env: string         // env var NAME, never the secret
  match_field: string         // "lead_id"
  field_count: number         // computed: field_mappings.length
  status_mapping: Record<string, string>
  import_status_mapping: Record<string, string>
}

// PUT /api/v1/clients/{client_id}/integrations → IntegrationConfig
interface UpdateIntegrationPayload {
  provider?: string
  base_id?: string
  table_id?: string
  api_key_env?: string
  match_field?: string
  status_mapping?: Record<string, string>
  import_status_mapping?: Record<string, string>
}

// POST /api/v1/clients/{client_id}/integrations/test → IntegrationTestResult
interface IntegrationTestResult {
  success: boolean
  message: string             // "Connected. Found 42 records." or error
  record_count?: number
}
```

### New Route Tree

```typescript
// router.tsx additions
{
  path: '/admin',
  element: <AdminLayout />,
  children: [
    { index: true, element: <AdminClientsListPage /> },
    { path: 'clients/:clientId', element: <ClientDetailPage /> },
  ],
}
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Token mapping produces correct Tailwind classes | Vitest: render component, assert class names contain `bg-paper`, `text-teal`, etc. |
| Unit | `IntegrationConfig` type guards and API functions | Vitest: mock fetch, verify request/response shapes |
| Unit | Existing component tests (13 test files) pass with new tokens | Run existing test suite — update snapshot/class assertions |
| Integration | Admin route navigation: list → detail → back | Vitest + React Router memory router |
| Integration | Integration config CRUD flow | MSW mock: GET config → render → PUT update → verify |
| E2E | Full admin flow: create client → view detail → configure integration | Manual verification against running backend |

## Migration Order

**PR#1 — Foundation + Primitives + Dashboard (Phases 1-3)**

1. `tokens.css` — full rewrite (everything changes visually at once)
2. `globals.css` — remove Manrope, add Google Fonts import, update body styles
3. `index.html` — add font preconnect links
4. Delete `public/fonts/` woff2 files
5. Each of the 13 design primitives — update Tailwind classes one by one
6. Update all 13 component test files for new class names
7. Dashboard page + sub-components — token updates
8. `app-layout.tsx` — `bg-pearl`

**PR#2 — Admin + Backend + Integrations (Phases 4-6)**

1. `AdminClientsListPage` — rewrite from `page.tsx` + `clients-panel.tsx`
2. `ClientDetailPage` — new file with stacked sections
3. `AgentsSection` — refactor from `agents-panel.tsx` (remove client selector)
4. `IntegrationsSection` — new file
5. `router.tsx` — add new admin routes
6. `crm_config_router.py` — new backend endpoints
7. `backend/app/main.py` — register router
8. `frontend/src/api/integrations.ts` + types + hooks
9. Update test files

## Open Questions

- [ ] Should the `card.tsx` `stripe` prop be removed entirely (anti-pattern #21) or kept but restyled with a non-left-border approach? **Recommendation**: Remove it; use a subtle teal `bg-teal-faint` background instead for "active" cards.
- [ ] The `agents-panel.tsx` edit form references `text-success` and `text-warning` — should these keep amber warning or switch to coral for error/urgency per design system? **Recommendation**: Keep warning as amber (not in the prohibited list), use coral for error/urgency.
