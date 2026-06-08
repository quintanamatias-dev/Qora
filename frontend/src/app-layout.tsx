/**
 * AppLayout — Root layout
 * Contains: Sidebar (fixed left, collapsible) + TopBar (sticky top) + <Outlet/> (page content)
 * Base: bg-pearl (Qora Design System light canvas)
 *
 * Manages sidebar collapsed state so PageContainer can mirror the correct margin.
 */

import { useState } from 'react'
import { Outlet, useParams } from 'react-router'
import { Sidebar, TopBar, PageContainer } from './design/components'

export function AppLayout() {
  const { clientId } = useParams<{ clientId: string }>()
  const id = (clientId ?? 'demo-client').toLowerCase()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  return (
    <div className="min-h-screen bg-pearl">
      <TopBar clientId={id} />
      <Sidebar
        clientId={id}
        collapsed={sidebarCollapsed}
        onCollapseToggle={() => setSidebarCollapsed((v) => !v)}
      />
      <PageContainer sidebarCollapsed={sidebarCollapsed}>
        <Outlet />
      </PageContainer>
    </div>
  )
}
