/**
 * Sidebar — Qora Design System layout primitive
 *
 * bg-paper + border-r border-line.
 * Active nav item: bg-teal-faint text-teal font-medium.
 * Inactive items: text-ink-2, hover: text-ink.
 * Brand: Fredoka "Qora" in text-teal (expanded) or "Q" (collapsed).
 * Left-stripe pattern PROHIBITED (anti-pattern #21).
 *
 * Collapsible: collapsed = icons only (~64px), expanded = icons + labels (~224px).
 * Toggle button at the bottom expands/collapses.
 * Shadow on right edge for depth.
 */

import { NavLink } from 'react-router'

interface SidebarProps {
  clientId: string
  collapsed?: boolean
  onCollapseToggle?: () => void
}

// ── Nav icons (inline SVG, 20×20, 1.5px stroke, rounded — Qora icon spec §9) ──

function IconDashboard() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2" y="2" width="7" height="7" rx="1.5" />
      <rect x="11" y="2" width="7" height="7" rx="1.5" />
      <rect x="2" y="11" width="7" height="7" rx="1.5" />
      <rect x="11" y="11" width="7" height="7" rx="1.5" />
    </svg>
  )
}

function IconAnalytics() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="2,14 7,9 11,12 18,5" />
      <line x1="2" y1="18" x2="18" y2="18" />
    </svg>
  )
}

function IconLeads() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="10" cy="7" r="3.5" />
      <path d="M3 17.5c0-3.5 3.1-6 7-6s7 2.5 7 6" />
    </svg>
  )
}

function IconImport() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10 2v10m0 0l-3.5-3.5M10 12l3.5-3.5" />
      <path d="M4 15h12" />
      <path d="M4 18h12" />
    </svg>
  )
}

function IconChevronLeft() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="10,3 5,8 10,13" />
    </svg>
  )
}

function IconChevronRight() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="6,3 11,8 6,13" />
    </svg>
  )
}

const navItems = [
  { label: 'Dashboard', path: 'dashboard', Icon: IconDashboard },
  { label: 'Analytics', path: 'analytics', Icon: IconAnalytics },
  { label: 'Leads', path: 'leads', Icon: IconLeads },
  { label: 'Import', path: 'import', Icon: IconImport },
]

export function Sidebar({ clientId, collapsed = false, onCollapseToggle }: SidebarProps) {
  return (
    <nav
      aria-label="Main navigation"
      data-collapsed={collapsed}
      className={[
        'fixed left-0 top-0 h-full',
        collapsed ? 'w-16' : 'w-56',
        'bg-paper',
        'border-r border-line',
        'flex flex-col',
        'pt-14', // space for TopBar
        'z-40',
        'transition-[width] duration-200 ease-[cubic-bezier(.4,0,.2,1)]',
        // Depth shadow on the right edge
        'shadow-[4px_0_16px_rgba(14,18,23,0.06)]',
      ].join(' ')}
    >
      {/* Brand / Logo area */}
      <div className={[
        'flex items-center',
        collapsed ? 'justify-center px-2 py-6' : 'px-4 py-6',
        'gap-2',
      ].join(' ')}>
        {collapsed ? (
          <span className="font-display font-medium text-xl text-teal tracking-tight select-none">
            Q
          </span>
        ) : (
          <div className="min-w-0">
            <span className="font-display font-medium text-xl text-teal tracking-tight">
              Qora
            </span>
            <p className="text-xs text-ink-3 font-mono uppercase tracking-widest mt-1 truncate">
              {clientId}
            </p>
          </div>
        )}
      </div>

      {/* Navigation links */}
      <ul className={['flex flex-col gap-0.5', collapsed ? 'px-1.5' : 'px-2'].join(' ')}>
        {navItems.map((item) => (
          <li key={item.path}>
            <NavLink
              to={`/app/${clientId}/${item.path}`}
              className={({ isActive }) =>
                [
                  'flex items-center',
                  collapsed ? 'justify-center px-2 py-2.5' : 'gap-3 px-3 py-2.5',
                  'rounded-md',
                  'text-sm font-medium',
                  'transition-all duration-150',
                  isActive
                    ? 'bg-teal-faint text-teal font-medium'
                    : 'text-ink-2 hover:bg-mist hover:text-ink',
                ].join(' ')
              }
              title={collapsed ? item.label : undefined}
            >
              <item.Icon />
              {!collapsed && (
                <span>{item.label}</span>
              )}
            </NavLink>
          </li>
        ))}
      </ul>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Toggle button — bottom-right corner of the sidebar */}
      <div className="flex justify-end px-2 pb-3">
        <button
          type="button"
          onClick={onCollapseToggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className={[
            'flex items-center justify-center',
            'w-8 h-8 rounded-md',
            'text-ink-3 hover:bg-mist hover:text-ink',
            'transition-colors duration-150',
          ].join(' ')}
        >
          {collapsed ? <IconChevronRight /> : <IconChevronLeft />}
        </button>
      </div>
    </nav>
  )
}
