/**
 * CallHistoryList — right-rail timeline (design: screens-lead.jsx `.tl`/`.tl-i`)
 *
 * Presentational — receives real call sessions. Clicking an item opens the
 * real CallDrawer (transcript + analysis). "Ver detalle" still links to the
 * full /calls/:sessionId page.
 */

import { useParams, Link } from 'react-router'
import type { CallSession } from '@/api/types'
import { formatDuration } from '@/lib/format-duration'
import { parseUTC } from '@/lib/parse-utc'

interface CallHistoryListProps {
  sessions: CallSession[]
  onOpenSession: (session: CallSession) => void
}

const DATE_FMT = new Intl.DateTimeFormat('es-AR', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const TIME_FMT = new Intl.DateTimeFormat('es-AR', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })

export function formatCallDate(isoOrNull: string | null): string {
  if (!isoOrNull) return '—'
  try {
    return DATE_FMT.format(parseUTC(isoOrNull))
  } catch {
    return isoOrNull
  }
}

export function truncateSummary(summary: string | null, maxLength = 100): string {
  if (!summary) return ''
  return summary.length > maxLength ? `${summary.slice(0, maxLength)}…` : summary
}

function statusLabel(status: CallSession['status']): string {
  switch (status) {
    case 'completed': return 'Completada'
    case 'abandoned': return 'Abandonada'
    case 'failed': return 'Fallida'
    case 'in_progress': return 'En curso'
    default: return 'Iniciada'
  }
}

export function CallHistoryList({ sessions, onOpenSession }: CallHistoryListProps) {
  const { clientId } = useParams<{ clientId: string }>()

  if (sessions.length === 0) {
    return <div className="empty">No calls yet</div>
  }

  return (
    <div className="tl">
      {sessions.map((session) => {
        const started = session.started_at ? parseUTC(session.started_at) : null
        const isAbandoned = session.status === 'abandoned' || session.status === 'failed'

        return (
          <div key={session.id} data-testid="call-history-item" className="tl-i" onClick={() => onOpenSession(session)}>
            <i className={isAbandoned ? 'tl-dot ab' : 'tl-dot'} />
            <div style={{ minWidth: 0 }}>
              <div className="tl-h">
                <b>{formatCallDate(session.started_at)}</b>
                {started && <span className="muted" style={{ fontSize: 12 }}>{TIME_FMT.format(started)}</span>}
                <span className="mono muted" style={{ fontSize: 11.5, marginLeft: 'auto' }}>
                  {session.duration_seconds != null ? formatDuration(session.duration_seconds) : '—'}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                <span className={isAbandoned ? 'tag ghost' : 'tag teal'}>{statusLabel(session.status)}</span>
              </div>
              {session.summary && <p className="tl-s">{session.summary}</p>}
              <Link
                to={`/app/${clientId}/calls/${session.id}`}
                data-testid="call-detail-link"
                onClick={(e) => e.stopPropagation()}
                style={{ fontSize: 12, color: 'var(--qd-teal)', marginTop: 4, display: 'inline-block' }}
              >
                Ver detalle →
              </Link>
            </div>
          </div>
        )
      })}
    </div>
  )
}
