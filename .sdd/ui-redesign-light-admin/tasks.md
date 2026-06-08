# Tasks: ui-redesign-light-admin

Strict TDD mode: logic changes MUST update tests before implementation. Frontend visual-only tasks may verify via existing Vitest class/render assertions plus manual visual review.

## PR #1 — Visual Foundation (Phases 1–3)

| ID | Phase | Title | Description | Files | Dependencies | Est. lines | Risk | Test strategy |
|---|---:|---|---|---|---|---:|---|---|
| T1 | 1 | Replace Qora design tokens | Rewrite tokens from Obsidian/Material names to Pearl/Paper/Teal/Ink, radius, shadow, motion, and font tokens. Visual-only. | `frontend/src/design/tokens.css` | None | 100 | MEDIUM | Vitest smoke via components; grep no `#0c1324`, `primary`, `on-surface`; manual computed token check. |
| T2 | 1 | Load canonical fonts and globals | Remove Manrope font-face blocks; add Google Fonts links/imports; set body to `var(--bg)`/`var(--ink)` and teal focus-visible. Visual-only. | `frontend/src/design/globals.css`, `frontend/index.html`, `frontend/public/fonts/*` | T1 | 100 | LOW | `npx vitest run`; browser verify Fredoka headings, Inter body, JetBrains Mono badges. |
| T3 | 2 | Update button/card/input primitives | Apply Qora button pill, paper card, input/select/textarea teal focus styles; update assertions. Visual-only. | `button.tsx`, `card.tsx`, `input.tsx`, `select.tsx`, `textarea.tsx` and matching tests | T1 | 180 | MEDIUM | Update Vitest class assertions for teal pill, paper card, focus ring; run component tests. |
| T4 | 2 | Update badge/table/tabs primitives | Apply mono teal badges, paper tables, mist tabs; preserve props/data attributes. Visual-only. | `badge.tsx`, `table.tsx`, `tabs.tsx` and matching tests | T1 | 150 | MEDIUM | Update Vitest assertions for mono uppercase badge, row separators, active tab classes. |
| T5 | 2 | Update layout primitives | Refresh Sidebar, TopBar, PageContainer, Checkbox, Toast to light Qora system; preserve exports. Visual-only. | `sidebar.tsx`, `top-bar.tsx`, `page-container.tsx`, `checkbox.tsx`, `toast.tsx`, `layout.test.tsx`, matching tests | T1,T2 | 190 | MEDIUM | Update layout/toast/checkbox tests; verify no prop or export contract changes in `index.ts`. |
| T6 | 3 | Redesign dashboard shell | Update dashboard page headings, client accent, page background, and layout classes only. Visual-only. | `frontend/src/features/dashboard/page.tsx`, `page.test.tsx` | T1-T5 | 110 | LOW | Update page tests for Pearl/Paper/Ink/Teal classes; verify no API/state changes. |
| T7 | 3 | Redesign dashboard widgets | Update stat cards, metrics grid gaps, status breakdown, and period selector styles only. Visual-only. | `stat-card.tsx`, `metrics-grid.tsx`, `status-breakdown.tsx`, `period-selector.tsx` and tests | T5 | 180 | LOW | Vitest checks for Fredoka metric class, `gap-*`, teal/coral status bars, pill selector. |
| T8 | 3 | PR #1 verification pass | Run frontend tests and scan for prohibited dark/startup-green classes in affected frontend files. | No code expected; affected PR #1 files if fixes needed | T1-T7 | 20 | LOW | `cd frontend && npx vitest run`; grep for `#0c1324`, `surface-container`, `Manrope`, `#4edea3`. |

## PR #2 — Structural + Integrations (Phases 4–6)

| ID | Phase | Title | Description | Files | Dependencies | Est. lines | Risk | Test strategy |
|---|---:|---|---|---|---|---:|---|---|
| T9 | 4 | Add admin nested route tests | RED: assert `/admin` renders client list and `/admin/clients/:clientId` renders detail with route param/back navigation. | `frontend/src/router.test.tsx` or admin route tests, `page.test.tsx` | T1-T8 | 90 | MEDIUM | Failing Vitest with memory router before implementation. |
| T10 | 4 | Convert admin page to client list | Rewrite `AdminPage` as client-list entry point with clickable rows/cards; remove flat tab state and keep create-client flow. | `frontend/src/features/admin/page.tsx`, `clients-panel.tsx`, `page.test.tsx`, `clients-panel.test.tsx` | T9 | 220 | HIGH | Make T9 pass; test client click navigates to `/admin/clients/:clientId`; existing create-client tests pass. |
| T11 | 4 | Create client detail page | Add `ClientDetailPage` reading `clientId`, header/breadcrumb/back link, stacked Agents and Integrations placeholders. | `client-detail-page.tsx`, `client-detail-page.test.tsx`, `router.tsx` | T10 | 180 | HIGH | Vitest route-param and back-navigation scenarios; no auth changes. |
| T12 | 4 | Refactor agents into route-scoped section | Change `AgentsPanel` to `AgentsSection` driven by `clientId` prop/route, remove local client selector, preserve edit/new agent flows. | `agents-panel.tsx` or `agents-section.tsx`, `agents-panel.test.tsx`, imports | T11 | 220 | HIGH | Tests list agents for `quintana-seguros`, edit controls, add agent action; no dropdown/tab state. |
| T13 | 5 | Add backend integration API tests | RED: cover GET empty/configured/disconnected, PUT masked token persistence, POST success/failure without leaking raw token. | `backend/tests/unit/integrations/test_crm_config_router.py` | None | 220 | HIGH | `cd backend && python -m pytest backend/tests/unit/integrations/test_crm_config_router.py` fails first. |
| T14 | 5 | Implement CRM config router | Create router/models for integration config using `crm.yaml` + `.env`; mask tokens; support Airtable test with non-5xx failures. | `backend/app/integrations/crm_config_router.py`, optional model file | T13 | 300 | HIGH | Make T13 pass; assert raw token never appears in responses/log-safe errors. |
| T15 | 5 | Register backend router | Mount integration router under `/api/v1/clients`; keep existing CRM import endpoints untouched. | `backend/app/main.py`, router import tests if present | T14 | 30 | MEDIUM | Backend targeted tests plus full `python -m pytest` when feasible. |
| T16 | 6 | Add frontend integration API tests/types | RED: define IntegrationConfig/payload/result types, API functions, and hook tests with fetch/MSW mocks. | `frontend/src/api/types.ts`, `integrations.ts`, `hooks.ts`, `index.ts`, API tests | T13 | 180 | MEDIUM | Failing Vitest verifies GET/PUT/POST paths and response shapes. |
| T17 | 6 | Implement frontend integration API/hooks | Implement typed API functions and TanStack Query hooks for fetch/update/test integration config. | `frontend/src/api/integrations.ts`, `types.ts`, `hooks.ts`, `index.ts` | T16,T15 | 180 | MEDIUM | Make T16 pass; verify cache invalidation after save/test. |
| T18 | 6 | Build IntegrationsSection UI | Add empty state, connected Airtable card, expandable masked token form, save/test buttons, success/error toasts. | `frontend/src/features/admin/integrations-section.tsx`, `integrations-section.test.tsx` | T17,T11 | 260 | HIGH | Vitest/MSW scenarios from spec §6; assert raw token is never rendered after save. |
| T19 | 6 | Wire integrations into detail page | Render `IntegrationsSection` inside `ClientDetailPage`; update detail tests to cover agents + integrations together. | `client-detail-page.tsx`, `client-detail-page.test.tsx` | T18,T12 | 80 | MEDIUM | Vitest detail page shows header, Agents, Integrations for route client. |
| T20 | 6 | PR #2 verification pass | Run backend and frontend suites; scan for token leaks and broken admin routes. | No code expected; affected PR #2 files if fixes needed | T9-T19 | 30 | MEDIUM | `cd backend && python -m pytest`; `cd frontend && npx vitest run`; manual admin flow smoke. |

## Review Workload Forecast

| Field | Value |
|---|---|
| Total estimated changed lines | ~3,020 |
| PR #1 estimated lines | ~1,030 |
| PR #2 estimated lines | ~1,990 |
| Chained PRs recommended | Yes |
| Threshold | 800 lines per PR |
| 800-line budget risk | High |
| Delivery strategy | auto-forecast |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
800-line budget risk: High

### Suggested split

- PR #1a: T1–T2 foundation (~200 lines).
- PR #1b: T3–T5 primitives (~520 lines), based on PR #1a.
- PR #1c: T6–T8 dashboard + visual verification (~310 lines), based on PR #1b.
- PR #2a: T9–T12 admin restructure (~710 lines), based on PR #1c or main after PR #1.
- PR #2b: T13–T15 backend integration API (~550 lines), independent after main.
- PR #2c: T16–T20 frontend integrations wiring (~730 lines), based on PR #2a + PR #2b.
