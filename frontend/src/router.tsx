/**
 * Router — React Router v7 route definitions
 *
 * Route structure:
 *  /                              → redirect to /app/demo-client/dashboard
 *  /app/:clientId                 → AppLayout (Sidebar + TopBar + Outlet)
 *    index                        → redirect to dashboard
 *    /app/:clientId/dashboard     → DashboardPage (placeholder)
 *    /app/:clientId/leads         → LeadsPage (placeholder)
 *    /app/:clientId/leads/:leadId → LeadDetailPage (placeholder)
 *    /app/:clientId/import        → ImportPage (placeholder)
 *  *                              → redirect to /app/demo-client/dashboard
 *
 * Design: export `routes` so that tests can wrap the same config in
 * createMemoryRouter (avoids browser history dependency in test environments).
 * The production `router` uses createBrowserRouter for real navigation.
 */

import { createBrowserRouter, Navigate } from 'react-router'
import type { RouteObject } from 'react-router'
import { AppLayout } from './app-layout'
import { DashboardPage } from './features/dashboard/page'
import { LeadsPage } from './features/leads/page'
import { LeadDetailPage } from './features/leads/detail-page'
import { ImportPage } from './features/import/page'

/**
 * Shared route definitions — used by both the production router and test helpers.
 * Exporting allows tests to wrap with createMemoryRouter without duplicating routes.
 */
export const routes: RouteObject[] = [
  {
    // Root redirect — spec requires /app/demo-client/dashboard
    index: true,
    path: '/',
    element: <Navigate to="/app/demo-client/dashboard" replace />,
  },
  {
    path: '/app/:clientId',
    element: <AppLayout />,
    children: [
      {
        index: true,
        element: <Navigate to="dashboard" replace />,
      },
      {
        path: 'dashboard',
        element: <DashboardPage />,
      },
      {
        path: 'leads',
        element: <LeadsPage />,
      },
      {
        path: 'leads/:leadId',
        element: <LeadDetailPage />,
      },
      {
        path: 'import',
        element: <ImportPage />,
      },
    ],
  },
  {
    // Catch-all → redirect to demo-client dashboard for dev convenience
    path: '*',
    element: <Navigate to="/app/demo-client/dashboard" replace />,
  },
]

/**
 * Production router — uses browser history.
 * Do NOT import this in tests; use `routes` with createMemoryRouter instead.
 */
export const router = createBrowserRouter(routes)
