/**
 * AppLayout — Root shell layout
 *
 * `.app` / `.app.collapsed` grid (244px / 68px sidebar, see dashboard.css)
 * containing Sidebar + a `.main` rounded panel (TopBar + PageContainer/<Outlet/>).
 * Collapsed state is persisted in localStorage via useSidebarCollapsed.
 */

import { Outlet, useParams } from 'react-router'
import { Sidebar, TopBar, PageContainer, useSidebarCollapsed } from './design/components'
import { UserMenu } from './features/auth/user-menu'

export function AppLayout() {
  const { clientId } = useParams<{ clientId: string }>()
  const id = (clientId ?? 'demo-client').toLowerCase()
  const [collapsed, toggleCollapsed] = useSidebarCollapsed()

  return (
    <div className={collapsed ? 'app collapsed' : 'app'}>
      <Sidebar clientId={id} collapsed={collapsed} onCollapseToggle={toggleCollapsed} />
      <div className="main">
        <TopBar clientId={id}>
          <UserMenu />
        </TopBar>
        <PageContainer>
          <Outlet />
        </PageContainer>
      </div>
    </div>
  )
}
