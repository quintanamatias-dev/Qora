/**
 * Sidebar — Qora dashboard shell (ported from ui.jsx Sidebar)
 *
 * Rendered inside the `.app`/`.app.collapsed` wrapper (see app-layout.tsx);
 * collapsed-state styling is driven entirely by the ancestor `.collapsed`
 * class from dashboard.css, not by local conditional rendering.
 *
 * No fake user identity: the design's footer "Juan Quintana / Administrador"
 * block has no backing data source, so the footer only renders the theme
 * toggle.
 */

import { NavLink } from 'react-router'
import { useClient, useLeads, useAgents } from '../../api/hooks'
import { Icon } from './icon'
import { useTheme } from './theme'

interface SidebarProps {
  clientId: string
  collapsed?: boolean
  onCollapseToggle?: () => void
}

const navItems = [
  { label: 'Resumen', path: 'dashboard', icon: 'grid' as const },
  { label: 'Analítica', path: 'analytics', icon: 'chart' as const },
  { label: 'Leads', path: 'leads', icon: 'users' as const },
  { label: 'Importar', path: 'import', icon: 'import' as const },
]

export function Sidebar({ clientId, collapsed = false, onCollapseToggle }: SidebarProps) {
  const { data: client } = useClient(clientId)
  const { data: leads } = useLeads(clientId)
  const { data: agents } = useAgents(clientId)
  const [theme, toggleTheme] = useTheme()

  return (
    <nav className="sb" aria-label="Main navigation">
      <div className="sb-top">
        <span className="wordmark">Qora</span>
        <button
          type="button"
          className="ib"
          title={collapsed ? 'Expandir' : 'Colapsar'}
          onClick={onCollapseToggle}
        >
          <Icon name="sidebar" size={17} />
        </button>
      </div>

      <button type="button" className="ws" title="Cambiar de cliente">
        <span className="ws-av">Q</span>
        <span className="ws-t">
          <b>{client?.name ?? clientId}</b>
          <span>{clientId}</span>
        </span>
        <span className="ic-sm muted">
          <Icon name="chevUD" size={15} />
        </span>
      </button>

      <div className="nav">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={`/app/${clientId}/${item.path}`}
            title={item.label}
            className={({ isActive }) => (isActive ? 'on' : '')}
          >
            <Icon name={item.icon} size={18} />
            <span>{item.label}</span>
            {item.path === 'leads' && leads !== undefined && (
              <em className="count">{leads.length}</em>
            )}
          </NavLink>
        ))}
      </div>

      <div className="sb-agents">
        <div className="nav-l">Agentes</div>
        {agents?.map((agent) => {
          const live = agent.is_active && agent.is_conversation_ready
          return (
            <div key={agent.agent_id} className="sb-agent" title={agent.name}>
              <i className={`dot ${live ? 'live' : 'setup'}`} />
              <span>{agent.name}</span>
              <em>{live ? 'En línea' : 'Config.'}</em>
            </div>
          )
        })}
      </div>

      <div className="sb-foot">
        <button
          type="button"
          className="ib"
          title="Cambiar tema"
          onClick={toggleTheme}
        >
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={17} />
        </button>
      </div>
    </nav>
  )
}
