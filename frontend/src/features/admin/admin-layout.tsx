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
    <div className="min-h-screen bg-background">
      {/* Admin header — compact, QORA + badge style matching old static admin */}
      <header
        data-testid="admin-header"
        className="sticky top-0 z-40 bg-surface-container-low border-b border-outline-variant/30 flex items-center px-6 py-3.5 gap-3"
      >
        <span className="font-display text-sm font-bold text-on-surface tracking-tight">
          QORA
        </span>
        <span className="text-[0.65rem] font-medium uppercase tracking-[0.07em] text-on-surface-variant bg-surface-container border border-outline-variant/40 px-2 py-0.5 rounded-sm">
          Admin
        </span>
        <span className="sr-only">Internal management panel</span>
      </header>

      {/* Page content — max-width constrained, matching old admin feel */}
      <main className="min-h-full bg-background">
        <div className="max-w-4xl mx-auto px-6 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
