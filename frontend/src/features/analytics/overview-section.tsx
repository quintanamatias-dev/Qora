/**
 * OverviewSection — "Resultados de llamada" card
 *
 * Horizontal-bar breakdown of call outcomes, sorted by count desc.
 * Design: qora-presentacion/project/dashboard/screens-overview.jsx Analytics
 */

import type { AnalyticsOverviewResponse } from '@/api/types'
import { outcomeLabel } from './outcome-labels'

interface OverviewSectionProps {
  data: AnalyticsOverviewResponse
}

export function OverviewSection({ data }: OverviewSectionProps) {
  const entries = Object.entries(data.outcome_distribution).sort((a, b) => b[1] - a[1])

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h3>Resultados de llamada</h3>
          <p>Cómo terminó cada conversación</p>
        </div>
      </div>
      <div className="card-b" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {entries.length === 0 && <div className="empty">Sin llamadas en este período.</div>}
        {entries.map(([key, count]) => (
          <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13.5 }}>
              <span>{outcomeLabel(key)}</span>
              <span className="num" style={{ whiteSpace: 'nowrap' }}>
                <b style={{ fontWeight: 500 }}>{count}</b>{' '}
                <span className="muted">
                  · {data.total_calls ? Math.round((count / data.total_calls) * 100) : 0}%
                </span>
              </span>
            </div>
            <div className="hbar">
              <i
                style={{
                  width: `${data.total_calls ? (count / data.total_calls) * 100 : 0}%`,
                  background: key === 'callback_requested' ? 'var(--qd-teal)' : 'var(--qd-ink-3)',
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
