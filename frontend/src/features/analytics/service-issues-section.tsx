/**
 * ServiceIssuesSection — "Problemas de servicio" ranked list
 *
 * Design: qora-presentacion/project/dashboard/screens-overview.jsx Analytics
 * Labels resolved via the dimension-label registry (backend codes stay English).
 */

import type { AnalyticsServiceIssuesResponse } from '@/api/types'
import { resolveLabel } from '@/config/dimension-labels'

interface ServiceIssuesSectionProps {
  data: AnalyticsServiceIssuesResponse
}

export function ServiceIssuesSection({ data }: ServiceIssuesSectionProps) {
  const maxIssue = Math.max(1, ...data.issues.map((s) => s.count))

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h3>Problemas de servicio</h3>
          <p>Detectados en las conversaciones</p>
        </div>
      </div>
      {data.issues.length === 0 ? (
        <div className="empty">Sin problemas de servicio en este período.</div>
      ) : (
        <div className="rows">
          {data.issues.map((s, i) => {
            const label = resolveLabel(s.issue, 'es')
            return (
            <div key={s.issue} className="row" style={{ padding: '16px 20px' }}>
              <span className="mono muted" style={{ fontSize: 11, width: 22 }}>
                {String(i + 1).padStart(2, '0')}
              </span>
              <div className="t" style={{ gap: 8 }}>
                <b>
                  {label}
                  {label !== s.issue && (
                    <span className="mono muted" style={{ fontSize: 11, fontWeight: 400, marginLeft: 4 }}>
                      {s.issue}
                    </span>
                  )}
                </b>
                <div className="hbar">
                  <i style={{ width: `${(s.count / maxIssue) * 100}%` }} />
                </div>
              </div>
              <span style={{ font: '500 20px/1 var(--qd-F)', width: 32, textAlign: 'right' }} className="num">
                {s.count}
              </span>
            </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
