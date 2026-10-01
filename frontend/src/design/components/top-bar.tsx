/**
 * TopBar — Qora dashboard shell (ported from ui.jsx Topbar)
 *
 * Breadcrumbs: client name > current page label.
 * Lead detail route is a special case per design: client > Leads (link) > the
 * real lead name (fetched via useLead from the route params).
 */

import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useClient, useLead } from '../../api/hooks'
import { Icon } from './icon'

interface TopBarProps {
  clientId: string
  children?: React.ReactNode
}

const PAGE_LABELS: Record<string, string> = {
  dashboard: 'Resumen',
  analytics: 'Analítica',
  leads: 'Leads',
  import: 'Importar',
}

interface Crumb {
  label: string
  to?: string
}

function buildCrumbs(pathname: string, clientId: string, clientName: string, leadName: string | undefined): Crumb[] {
  const prefix = `/app/${clientId}/`
  const rest = pathname.startsWith(prefix) ? pathname.slice(prefix.length) : ''
  const segments = rest.split('/').filter(Boolean)

  if (segments[0] === 'leads' && segments[1]) {
    return [{ label: clientName }, { label: 'Leads', to: `/app/${clientId}/leads` }, { label: leadName ?? 'Lead' }]
  }

  const label = PAGE_LABELS[segments[0]] ?? segments[0] ?? ''
  return [{ label: clientName }, { label }]
}

export function TopBar({ clientId, children }: TopBarProps) {
  const { data: client } = useClient(clientId)
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  const prefix = `/app/${clientId}/`
  const segments = (pathname.startsWith(prefix) ? pathname.slice(prefix.length) : '').split('/').filter(Boolean)
  const leadId = segments[0] === 'leads' ? segments[1] : undefined
  const { data: lead } = useLead(clientId, leadId ?? '')

  const crumbs = buildCrumbs(pathname, clientId, client?.name ?? clientId, lead?.name)

  const goToLeadsSearch = () => {
    navigate(`/app/${clientId}/leads?q=${encodeURIComponent(query)}`)
  }

  return (
    <header role="banner" className="top">
      <div className="crumbs">
        {crumbs.map((c, i) =>
          i < crumbs.length - 1 ? (
            <span key={i} style={{ display: 'contents' }}>
              {c.to ? (
                <button type="button" onClick={() => navigate(c.to as string)}>
                  {c.label}
                </button>
              ) : (
                <span>{c.label}</span>
              )}
              <Icon name="chevR" size={13} />
            </span>
          ) : (
            <b key={i}>{c.label}</b>
          ),
        )}
      </div>
      <label className="search">
        <Icon name="search" size={15} />
        <input
          placeholder="Buscar leads, llamadas…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') goToLeadsSearch()
          }}
        />
        <span className="kbd">⌘K</span>
      </label>
      {children}
    </header>
  )
}
