/**
 * AdminPage — Main admin page with Clients and Agents tabs
 *
 * Container component: manages active tab state.
 * Renders ClientsPanel or AgentsPanel based on selected tab.
 */

import { useState } from 'react'
import { Tabs } from '@/design/components'
import { ClientsPanel } from './clients-panel'
import { AgentsPanel } from './agents-panel'

const ADMIN_TABS = [
  { key: 'clients', label: 'Clients' },
  { key: 'agents', label: 'Agents' },
]

export function AdminPage() {
  const [activeTab, setActiveTab] = useState('clients')

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="font-display text-2xl font-bold text-on-surface">Admin</h1>
        <p className="text-sm text-on-surface-variant mt-1">
          Manage clients and agents
        </p>
      </div>

      {/* Tab navigation */}
      <Tabs
        tabs={ADMIN_TABS}
        activeKey={activeTab}
        onTabChange={setActiveTab}
        className="w-fit"
      />

      {/* Tab content */}
      {activeTab === 'clients' && <ClientsPanel />}
      {activeTab === 'agents' && <AgentsPanel />}
    </div>
  )
}
