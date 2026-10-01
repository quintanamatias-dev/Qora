/**
 * Router — React Router v7 route definitions
 *
 * Route structure:
 *  /login                         → LoginPage (public, no RequireAuth)
 *  /                              → RequireAuth + RoleHome (superadmin → /admin,
 *                                   client → /app/{their client}/dashboard)
 *  /app/:clientId                 → RequireAuth + AppRoleGuard + AppLayout
 *    index                        → redirect to dashboard
 *    /app/:clientId/dashboard     → DashboardPage (placeholder)
 *    /app/:clientId/leads         → LeadsPage (placeholder)
 *    /app/:clientId/leads/:leadId → LeadDetailPage (placeholder)
 *    /app/:clientId/import        → ImportPage (placeholder)
 *  /admin                         → RequireAuth + AdminRoleGuard + AdminLayout
 *  *                              → RequireAuth + RoleHome
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
import { AdminLayout } from './features/admin/admin-layout'
import { AdminPage } from './features/admin/page'
import { ClientDetailPage } from './features/admin/client-detail-page'
import { AnalyticsRoute } from './features/analytics/page'
import { CallDetailPage } from './features/calls/call-detail-page'
import { LoginPage } from './features/auth/login-page'
import { RequireAuth } from './features/auth/require-auth'
import { RoleHome, AdminRoleGuard, AppRoleGuard } from './features/auth/role-routing'

/**
 * Shared route definitions — used by both the production router and test helpers.
 * Exporting allows tests to wrap with createMemoryRouter without duplicating routes.
 */
export const routes: RouteObject[] = [
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    // Root redirect — role-based (multi-tenant-auth §9)
    index: true,
    path: '/',
    element: (
      <RequireAuth>
        <RoleHome />
      </RequireAuth>
    ),
  },
  {
    path: '/app/:clientId',
    element: (
      <RequireAuth>
        <AppRoleGuard>
          <AppLayout />
        </AppRoleGuard>
      </RequireAuth>
    ),
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
      {
        path: 'analytics',
        element: <AnalyticsRoute />,
      },
      {
        path: 'calls/:sessionId',
        element: <CallDetailPage />,
      },
    ],
  },
  {
    path: '/admin',
    element: (
      <RequireAuth>
        <AdminRoleGuard>
          <AdminLayout />
        </AdminRoleGuard>
      </RequireAuth>
    ),
    children: [
      {
        index: true,
        element: <AdminPage />,
      },
      {
        path: 'clients/:clientId',
        element: <ClientDetailPage />,
      },
    ],
  },
  {
    // Catch-all — role-based (multi-tenant-auth §9)
    path: '*',
    element: (
      <RequireAuth>
        <RoleHome />
      </RequireAuth>
    ),
  },
]

/**
 * Production router — uses browser history.
 * Do NOT import this in tests; use `routes` with createMemoryRouter instead.
 */
export const router = createBrowserRouter(routes)
