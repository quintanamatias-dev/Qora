/**
 * AdminLayout — Internal admin panel layout
 *
 * No Sidebar — admin uses Tabs for navigation within pages.
 * Full-width layout with its own header and content wrapper.
 * Uses design tokens for background-shift elevation (no borders).
 */

import { Outlet } from 'react-router'

export function AdminLayout() {
  return (
    <div className="min-h-screen bg-background">
      {/* Admin header — no Sidebar, no TopBar clientId */}
      <header
        data-testid="admin-header"
        className="sticky top-0 z-40 bg-surface-container-low h-14 flex items-center px-6"
      >
        <div>
          <span className="font-display text-base font-bold text-on-surface tracking-tight">
            QORA Admin
          </span>
          <span className="ml-3 text-xs text-on-surface-variant font-body">
            Internal management panel
          </span>
        </div>
      </header>

      {/* Page content — full width, no sidebar offset */}
      <main className="min-h-full bg-background p-6">
        <Outlet />
      </main>
    </div>
  )
}
