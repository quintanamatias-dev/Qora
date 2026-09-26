/**
 * CallDrawer — call detail overlay (design: screens-lead.jsx `CallDrawer`)
 *
 * Real transcript (useTranscript via TranscriptViewer) + real analysis summary
 * and interests/pain points (AnalysisPanel via useCallAnalysis). No audio
 * player — CallSession/CallAnalysis carry no recording URL, so playback is
 * omitted rather than faked.
 */

import { useEffect } from 'react'
import type { CallSession, Lead, PainPoint } from '@/api/types'
import { useCallAnalysis } from '@/api/hooks'
import { Icon } from '@/design/components'
import { formatDuration } from '@/lib/format-duration'
import { parseUTC } from '@/lib/parse-utc'
import { TranscriptViewer } from './transcript-viewer'
import { AnalysisPanel } from './analysis-panel'

const DATE_FMT = new Intl.DateTimeFormat('es-AR', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const TIME_FMT = new Intl.DateTimeFormat('es-AR', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })

function sessionStatusLabel(status: CallSession['status']): string {
  switch (status) {
    case 'completed': return 'Completada'
    case 'abandoned': return 'Abandonada'
    case 'failed': return 'Fallida'
    case 'in_progress': return 'En curso'
    default: return 'Iniciada'
  }
}

interface CallDrawerProps {
  session: CallSession
  lead: Lead
  onClose: () => void
}

export function CallDrawer({ session, lead, onClose }: CallDrawerProps) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const { data: analysis } = useCallAnalysis(session.id)
  const summary = analysis?.summary ?? session.summary
  const started = session.started_at ? parseUTC(session.started_at) : null

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={`Llamada del ${lead.name}`}>
        <div className="drawer-h">
          <div style={{ flex: 1, minWidth: 0 }}>
            <span className="eyebrow">Llamada · {lead.name}</span>
            <h2 style={{ margin: '10px 0 8px', font: '500 22px/1.15 var(--qd-F)', letterSpacing: '-.02em' }}>
              {started ? DATE_FMT.format(started) : '—'}
              {started && <span className="muted"> · {TIME_FMT.format(started)}</span>}
            </h2>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <span className="tag">{sessionStatusLabel(session.status)}</span>
              <span className="tag mono">{session.duration_seconds != null ? formatDuration(session.duration_seconds) : '—'}</span>
            </div>
          </div>
          <button type="button" className="ib" onClick={onClose} title="Cerrar">
            <Icon name="x" size={18} />
          </button>
        </div>
        <div className="drawer-b">
          <div>
            <div className="sec-l">Resumen</div>
            <p style={{ margin: 0, textWrap: 'pretty' as React.CSSProperties['textWrap'] }}>
              {summary ?? 'Sin resumen disponible.'}
            </p>
          </div>

          <AnalysisPanel
            interests={analysis ? { products: analysis.products ?? [], specific_needs: analysis.specific_needs ?? [], buying_signals: [] } : null}
            problem={analysis ? { pain_points: (analysis.pain_points ?? []) as unknown as PainPoint[] } : null}
          />

          <div>
            <div className="sec-l">Transcripción</div>
            <TranscriptViewer sessionId={session.id} />
          </div>
        </div>
      </aside>
    </>
  )
}
