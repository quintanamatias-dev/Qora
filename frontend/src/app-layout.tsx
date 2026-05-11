/**
 * AppLayout — Root layout
 * Contains: Sidebar (fixed left) + TopBar (sticky top) + <Outlet/> (page content)
 */

import { Outlet, useParams } from 'react-router'
import { Sidebar, TopBar, PageContainer } from './design/components'

export function AppLayout() {
  const { clientId } = useParams<{ clientId: string }>()
  const id = (clientId ?? 'demo-client').toLowerCase()

  return (
    <div className="min-h-screen bg-background">
      <TopBar clientId={id} />
      <Sidebar clientId={id} />
      <PageContainer>
        <Outlet />
      </PageContainer>
    </div>
  )
}
