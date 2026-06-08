/**
 * AdminLayout — Internal admin panel layout
 *
 * Visually matches the old backend static admin:
 *  - Compact header with QORA logo + Admin badge
 *  - max-width constrained content area (960px)
 *  - No Sidebar, no TopBar
 */

import { Outlet } from 'react-router'

export function AdminLayout() {
  return (
    <div className="min-h-screen bg-pearl">
      {/* Admin header — compact, Qora brand + Admin badge */}
      <header
        data-testid="admin-header"
        className="sticky top-0 z-40 bg-paper border-b border-line flex items-center px-6 py-3.5 gap-3"
      >
        <span className="font-display text-sm font-medium text-teal tracking-tight">
          Qora
        </span>
        <span className="text-[0.65rem] font-mono font-medium uppercase tracking-[0.07em] text-ink-3 bg-mist border border-line px-2 py-0.5 rounded-full">
          Admin
        </span>
        <span className="sr-only">Internal management panel</span>
      </header>

      {/* Page content — full-width with comfortable horizontal padding */}
      <main className="min-h-full bg-pearl">
        <div className="px-8 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
