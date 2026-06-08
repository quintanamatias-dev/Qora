# Proposal: UI Redesign — Light Admin

## Intent

The Qora admin UI uses a dark "Obsidian" palette, Manrope font, and a flat tab-based admin structure that does not match the Qora brand and does not scale as a product. This change replaces the visual identity (tokens, fonts, components) with the canonical Qora Design System, restructures the admin for a drill-down client-centric UX, and adds an integrations panel backed by new API endpoints.

## Scope

### In Scope
- Token/palette replacement: Obsidian dark → Qora Teal & Pearl light palette
- Font swap: Manrope → Fredoka (display) + Inter (body) + JetBrains Mono (mono)
- All 13 design primitives updated to Qora Design System specs
- Dashboard page redesign: light, airy, large metrics, soft shadows
- Admin restructure: flat tabs → client list with drill-down to ClientDetailPage
- ClientDetailPage: agents config + voice config + integrations in one view
- Integrations panel: Airtable connection with token input and status indicator
- Backend integration config endpoints: `GET`, `PUT` per client + `POST` test connection
- Sidebar and TopBar visual refresh

### Out of Scope
- OAuth flows (token-only auth)
- New analytics features
- Lead management redesign
- Mobile responsiveness beyond current baseline
- New backend business logic beyond integration config CRUD

## Capabilities

> This section is the CONTRACT between proposal and specs phases.

### New Capabilities
- `integration-config`: Token-based integration configuration per client (Airtable). Includes read, save, test-connection API + frontend UI with status indicator.
- `admin-client-detail`: New drill-down ClientDetailPage at `/admin/clients/:clientId` consolidating agents, voice config, and integrations for one client.

### Modified Capabilities
- `design-system-tokens`: Existing token architecture (tokens.css + globals.css) migrated from Obsidian dark palette to Qora Design System (Pearl/Paper/Teal). Font stack updated.
- `design-primitives`: All 13 existing design primitive components visually updated to match Qora Design System specs (radius, borders, shadows, backgrounds, button shape).
- `dashboard`: Existing dashboard page and stat components visually updated for light, airy aesthetic — no logic changes.
- `admin-navigation`: Existing flat Clients/Agents tab admin replaced with client-list entry point + nested route structure.

## Approach

Layered phases — foundation first, then components, then features, then backend. Token-based Tailwind architecture means changing `tokens.css` cascades to all 13 components and all features automatically. Components then get individual visual refinements. Admin restructure uses new nested routes (`/admin/clients/:clientId`) with `AgentsPanel` refactored to receive `clientId` as a prop rather than managing its own selector. Backend integration API follows existing `crm_router.py` pattern.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `frontend/src/design/tokens.css` | Modified | Full palette replacement: Obsidian → Qora Design System |
| `frontend/src/design/globals.css` | Modified | Remove hardcoded `#0c1324`/`#e2e8f0`; add Fredoka + JBM fonts |
| `frontend/src/design/components/` (×13) | Modified | Visual update for all primitives: radius, borders, shadows, backgrounds |
| `frontend/src/features/dashboard/` (×5) | Modified | Light redesign — stat cards, metrics grid, status breakdown |
| `frontend/src/features/admin/` | Modified + New | New ClientDetailPage, refactored AgentsPanel, new IntegrationsSection |
| `frontend/src/router.tsx` | Modified | Add `/admin/clients/:clientId` nested route |
| `frontend/src/api/types.ts` | Modified | Add IntegrationConfig type |
| `frontend/src/api/clients.ts` | Modified | Add integration API functions |
| `backend/app/routers/` | New | `integration_router.py` with GET/PUT/POST endpoints |
| `backend/app/models/` | New | `integration_config.py` Pydantic models |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Admin route refactor breaks existing tests | Medium | Update admin tests alongside route change in Phase 4 |
| API token storage security | High | Mask tokens in GET responses; store as env-var names, not plaintext |
| Font loading causes layout shift | Low | Self-host Fredoka + JBM before Phase 1 ships |
| Component visual tests (snapshots) break | Low | No snapshot tests confirmed; only data-attribute tests exist |

## Rollback Plan

Each phase ships as an independent PR. Roll back any phase by reverting its PR. Token changes (Phase 1) are the widest — reverting restores original `tokens.css` and `globals.css`. Admin route changes (Phase 4) are independent — reverting removes the new route without affecting other features. Backend endpoints (Phase 5) are additive — no existing endpoints are modified.

## Dependencies

- Fredoka and JetBrains Mono font files must be available (CDN or self-hosted) before Phase 1 ships
- Backend integration storage strategy decision: filesystem YAML (consistent with current `crm.yaml`) vs DB — **Decision: filesystem YAML, same pattern as crm.yaml**

## Success Criteria

- [ ] All pages render with Pearl/Paper backgrounds and Teal accents (no dark surfaces visible)
- [ ] Fredoka renders as the display font; JetBrains Mono renders for mono elements
- [ ] Admin: clicking a client navigates to `/admin/clients/:clientId` with agents + integrations visible
- [ ] Integrations panel shows Airtable status (connected/disconnected) and allows token save + test
- [ ] Backend `GET /api/v1/clients/{client_id}/integrations` returns masked config
- [ ] All existing tests pass after each phase

## Phasing

| Phase | Scope | PR Strategy | Budget Risk |
|-------|-------|-------------|-------------|
| 1 — Foundation | tokens.css, globals.css, fonts | Part of PR #1 | Low |
| 2 — Design Primitives | 13 components | Part of PR #1 | Medium |
| 3 — Dashboard | 5 dashboard files | Part of PR #1 | Low |
| 4 — Admin Restructure | routes, ClientDetailPage, refactor | PR #2 | High |
| 5 — Backend API | 2 new files | Part of PR #2 | Low |
| 6 — Integrations Panel | IntegrationsSection + API hooks | Part of PR #2 | Medium |

**Recommended chained PRs**: PR #1 (Phases 1–3) → PR #2 (Phases 4–6)
**Estimated lines**: ~1200–1500 changed across both PRs
