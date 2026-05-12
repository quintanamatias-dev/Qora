/**
 * AdminPage — Main admin page with Clients and Agents tabs
 *
 * Container component: manages active tab state.
 * Tab style matches old static admin: underline indicator, border-bottom nav.
 * Renders ClientsPanel or AgentsPanel based on selected tab.
 */

import { useState } from 'react'
import { ClientsPanel } from './clients-panel'
import { AgentsPanel } from './agents-panel'

const ADMIN_TABS = [
  { key: 'clients', label: 'Clients' },
  { key: 'agents', label: 'Agents & Voice Config' },
]

export function AdminPage() {
  const [activeTab, setActiveTab] = useState('clients')

  return (
    <div className="space-y-6">
      {/* Underline tab navigation — old admin style */}
      <nav
        className="flex border-b border-outline-variant/30 -mx-0"
        role="tablist"
        aria-label="Admin sections"
      >
        {ADMIN_TABS.map((tab) => {
          const isActive = tab.key === activeTab
          return (
            <button
              key={tab.key}
              role="tab"
              aria-selected={isActive}
              data-active={isActive ? 'true' : 'false'}
              data-tab-key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={[
                'px-5 py-2.5 text-[0.82rem] font-medium transition-colors duration-150',
                'border-b-2 -mb-px focus:outline-none',
                isActive
                  ? 'text-on-surface border-primary'
                  : 'text-on-surface-variant border-transparent hover:text-on-surface',
              ].join(' ')}
            >
              {tab.label}
            </button>
          )
        })}
      </nav>

      {/* Tab content */}
      {activeTab === 'clients' && <ClientsPanel />}
      {activeTab === 'agents' && <AgentsPanel />}
    </div>
  )
}
