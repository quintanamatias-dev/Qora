/**
 * Sidebar — Sovereign Interface layout primitive
 *
 * Fixed left column with surface-container-low background (per DESIGN.md REQ-3.5).
 * Active nav item: surface-bright bg + 2px primary (emerald) left stripe.
 * Inactive items: no border, no stripe.
 */

import { NavLink } from 'react-router'

interface SidebarProps {
  clientId: string
}

const navItems = [
  { label: 'Dashboard', path: 'dashboard' },
  { label: 'Leads', path: 'leads' },
  { label: 'Import', path: 'import' },
]

export function Sidebar({ clientId }: SidebarProps) {
  return (
    <nav
      aria-label="Main navigation"
      className={[
        'fixed left-0 top-0 h-full',
        'w-56',
        'bg-surface-container-low',
        'flex flex-col',
        'pt-14', // space for TopBar
        'z-40',
      ].join(' ')}
    >
      {/* Brand / Logo area */}
      <div className="px-4 py-6">
        <span className="text-xs uppercase tracking-widest text-on-surface-variant font-medium">
          Client
        </span>
        <p className="text-sm text-on-surface font-display font-semibold mt-0.5 truncate">
          {clientId}
        </p>
      </div>

      {/* Navigation links */}
      <ul className="flex flex-col gap-0.5 px-2">
        {navItems.map((item) => (
          <li key={item.path}>
            <NavLink
              to={`/app/${clientId}/${item.path}`}
              className={({ isActive }) =>
                [
                  'flex items-center gap-3',
                  'px-3 py-2.5',
                  'rounded-sm',
                  'text-sm font-medium',
                  'transition-all duration-150',
                  isActive
                    ? 'bg-surface-bright text-primary border-l-2 border-l-primary pl-[calc(0.75rem-2px)]'
                    : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface',
                ].join(' ')
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
