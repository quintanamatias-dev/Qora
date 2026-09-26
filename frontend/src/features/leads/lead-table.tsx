/**
 * LeadTable — Leads list table (design: screens-leads.jsx `Leads` table)
 *
 * Columns: Lead (avatar + name + phone) · Estado · Llamadas · Última llamada ·
 * Datos para cotizar (real quote_fields progress + n/N) · Próxima acción ·
 * Llamar (real call trigger — CallNowCell, guards untouched).
 */

import type { Lead, LeadStatus, QuoteField } from '@/api/types'
import { deriveNextAction } from './next-action'
import { CallNowCell } from './call-now-cell'
import { parseUTC } from '@/lib/parse-utc'

// ──────────────────────────────────────────────────────────────────────────────
// Props
// ──────────────────────────────────────────────────────────────────────────────

interface LeadTableProps {
  clientId: string
  leads: Lead[]
  onSelectLead: (leadId: string) => void
}

// ──────────────────────────────────────────────────────────────────────────────
// Pure helpers
// ──────────────────────────────────────────────────────────────────────────────

export function initials(name: string): string {
  return name.split(' ').filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase()
}

const LAST_CALLED_FMT = new Intl.DateTimeFormat('es-AR', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

export function formatLastCalled(isoOrNull: string | null): string {
  if (!isoOrNull) return 'Nunca'
  try {
    return LAST_CALLED_FMT.format(parseUTC(isoOrNull))
  } catch {
    return 'Nunca'
  }
}

const LEAD_STATUS_LABELS: Record<LeadStatus, string> = {
  new: 'Nuevo',
  called: 'Llamado',
  quoted: 'Cotizado',
  interested: 'Interesado',
  not_interested: 'No interesado',
  follow_up: 'Seguimiento',
}

const LEAD_STATUS_CLASS: Record<LeadStatus, string> = {
  new: 'tag',
  called: 'tag',
  quoted: 'tag teal',
  interested: 'tag teal',
  not_interested: 'tag ghost',
  follow_up: 'tag teal',
}

export function LeadStatusTag({ status }: { status: LeadStatus }) {
  return <span className={LEAD_STATUS_CLASS[status] ?? 'tag'}>{LEAD_STATUS_LABELS[status] ?? status}</span>
}

function quoteReadyFields(fields: QuoteField[] | undefined): QuoteField[] {
  return (fields ?? []).filter((f) => f.in_quote_ready_fields)
}

function QuoteProg({ fields }: { fields: QuoteField[] }) {
  return (
    <div className="prog">
      {fields.map((f) => (
        <i key={f.field_key} className={f.filled ? 'on' : ''} />
      ))}
    </div>
  )
}

function NextActionCell({ lead }: { lead: Lead }) {
  const { label, badge } = deriveNextAction(lead)
  const flagged = badge === 'error' || badge === 'warning'
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 7, whiteSpace: 'nowrap' }}>
        {flagged && <i className="dot coral" />}
        {label}
      </span>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// LeadTable
// ──────────────────────────────────────────────────────────────────────────────

export function LeadTable({ clientId, leads, onSelectLead }: LeadTableProps) {
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>Lead</th>
            <th>Estado</th>
            <th className="r">Llamadas</th>
            <th>Última llamada</th>
            <th>Datos para cotizar</th>
            <th>Próxima acción</th>
            <th>Llamar</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => {
            const readyFields = quoteReadyFields(lead.quote_fields)
            const filledCount = readyFields.filter((f) => f.filled).length
            const values = readyFields.filter((f) => f.filled && f.current_value).map((f) => f.current_value as string)

            return (
              <tr key={lead.id} className="click" role="row" onClick={() => onSelectLead(lead.id)}>
                <td>
                  <div className="lead-cell">
                    <span className="avatar">{initials(lead.name)}</span>
                    <div className="t">
                      <b>{lead.name}</b>
                      <span>{lead.phone}</span>
                    </div>
                  </div>
                </td>
                <td><LeadStatusTag status={lead.status} /></td>
                <td className="r num">{lead.call_count}</td>
                <td className="num" style={{ whiteSpace: 'nowrap' }}>{formatLastCalled(lead.last_called_at)}</td>
                <td>
                  {readyFields.length > 0 ? (
                    <>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <QuoteProg fields={readyFields} />
                        <span
                          className="mono num"
                          style={{ fontSize: 11.5, color: filledCount === readyFields.length ? 'var(--qd-teal)' : 'var(--qd-ink-3)' }}
                        >
                          {filledCount}/{readyFields.length}
                        </span>
                      </div>
                      <div
                        className="muted"
                        style={{ fontSize: 12, marginTop: 4, maxWidth: 220, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                      >
                        {values.length ? values.join(' · ') : 'Sin datos todavía'}
                      </div>
                    </>
                  ) : (
                    <span className="muted">Sin datos configurados</span>
                  )}
                </td>
                <td><NextActionCell lead={lead} /></td>
                <td className="r" onClick={(e) => e.stopPropagation()}>
                  <CallNowCell clientId={clientId} lead={lead} />
                </td>
              </tr>
            )
          })}
          {leads.length === 0 && (
            <tr>
              <td colSpan={7}>
                <div className="empty">No hay leads que coincidan con la búsqueda.</div>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
