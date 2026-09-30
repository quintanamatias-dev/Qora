/**
 * LeadsPage — Leads list (design: screens-leads.jsx `Leads`)
 *
 * Header + search (name/phone, accent-insensitive; reads initial ?q= from the
 * URL — the TopBar search navigates here) + Seg status filter with real counts
 * + LeadTable. Polls every 15s (read-only GET).
 */

import { useMemo, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router'
import { useLeads, useClient, useFeature } from '@/api/hooks'
import { PLAN_EXCLUDES_OUTBOUND } from './call-now-cell'
import { Icon } from '@/design/components'
import { LeadTable } from './lead-table'
import type { Lead, LeadStatus } from '@/api/types'

const REALTIME_INTERVAL_MS = 15_000

const OTHER_STATUS_LABELS: Partial<Record<LeadStatus, string>> = {
  quoted: 'Cotizado',
  interested: 'Interesado',
  called: 'Llamado',
  not_interested: 'No interesado',
}

function normalize(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f\s]/g, '')
}

export function LeadsPage() {
  const { clientId } = useParams<{ clientId: string }>()
  const activeClientId = clientId ?? ''
  const canCall = useFeature(activeClientId, 'outbound_calls')
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [q, setQ] = useState(searchParams.get('q') ?? '')
  const [statusFilter, setStatusFilter] = useState<'all' | LeadStatus>('all')

  const { data: client } = useClient(activeClientId)
  const { data: leads, isLoading, isError, refetch } = useLeads(activeClientId, { refetchInterval: REALTIME_INTERVAL_MS })

  const allLeads = leads ?? []

  const countFor = (status: LeadStatus) => allLeads.filter((l) => l.status === status).length

  const otherStatuses = useMemo(() => {
    const present = new Set(allLeads.map((l) => l.status))
    present.delete('new')
    present.delete('follow_up')
    return Array.from(present).filter((status) => allLeads.filter((l) => l.status === status).length > 0)
  }, [allLeads])

  const filtered = useMemo(() => {
    const nq = normalize(q)
    return allLeads.filter((l) => {
      if (statusFilter !== 'all' && l.status !== statusFilter) return false
      if (!nq) return true
      return normalize(`${l.name}${l.phone}`).includes(nq)
    })
  }, [allLeads, statusFilter, q])

  function handleSelectLead(leadId: string) {
    navigate(`/app/${activeClientId}/leads/${leadId}`)
  }

  return (
    <div className="page">
      <div className="ph">
        <div>
          <h1>Leads</h1>
          <p>{allLeads.length} leads de {client?.name ?? activeClientId}. Tocá uno para ver su memoria y sus llamadas.</p>
        </div>
      </div>

      <section className="card">
        <div className="card-h" style={{ flexWrap: 'wrap' }}>
          <label className="search" style={{ margin: 0, width: 'min(320px,100%)', background: 'var(--qd-surface)' }}>
            <Icon name="search" size={15} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar por nombre o teléfono" />
          </label>
          <div className="seg" role="radiogroup" aria-label="Filtrar por estado">
            <button type="button" role="radio" aria-checked={statusFilter === 'all'} className={statusFilter === 'all' ? 'on' : ''} onClick={() => setStatusFilter('all')}>
              Todos · {allLeads.length}
            </button>
            <button type="button" role="radio" aria-checked={statusFilter === 'new'} className={statusFilter === 'new' ? 'on' : ''} onClick={() => setStatusFilter('new')}>
              Nuevos · {countFor('new')}
            </button>
            <button type="button" role="radio" aria-checked={statusFilter === 'follow_up'} className={statusFilter === 'follow_up' ? 'on' : ''} onClick={() => setStatusFilter('follow_up')}>
              Seguimiento · {countFor('follow_up')}
            </button>
            {otherStatuses.map((status) => (
              <button
                key={status}
                type="button"
                role="radio"
                aria-checked={statusFilter === status}
                className={statusFilter === status ? 'on' : ''}
                onClick={() => setStatusFilter(status)}
              >
                {OTHER_STATUS_LABELS[status] ?? status} · {countFor(status)}
              </button>
            ))}
          </div>
        </div>

        {isLoading && (
          <div data-testid="leads-loading" className="empty">Cargando leads…</div>
        )}

        {isError && !isLoading && (
          <div data-testid="leads-error" role="alert" className="empty">
            No pudimos cargar los leads.{' '}
            <button type="button" className="btn sm" onClick={() => refetch()}>Reintentar</button>
          </div>
        )}

        {!isLoading && !isError && allLeads.length === 0 && (
          <div data-testid="leads-empty" className="empty">No se encontraron leads.</div>
        )}

        {!isLoading && !isError && allLeads.length > 0 && (
          <LeadTable
            clientId={activeClientId}
            leads={filtered}
            onSelectLead={handleSelectLead}
            callDisabledReason={canCall ? undefined : PLAN_EXCLUDES_OUTBOUND}
          />
        )}
      </section>
    </div>
  )
}

export type { Lead }
