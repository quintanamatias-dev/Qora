/**
 * CallDetailPage — Container page for call detail view
 *
 * Shows full transcript + all 12 analysis dimensions for a specific call session.
 * Design: Container-presentational pattern — reads sessionId from URL params,
 *   fetches analysis + transcript, renders CallAnalysisPanel + TranscriptViewer.
 *
 * Route: /app/:clientId/calls/:sessionId
 */

import { useParams, useNavigate } from 'react-router'
import { useCallAnalysis } from '@/api/hooks'
import { CallAnalysisPanel } from './call-analysis-panel'
import { TranscriptViewer } from '../leads/transcript-viewer'
import { Badge } from '@/design/components/badge'

// ──────────────────────────────────────────────────────────────────────────────
// CallDetailPage
// ──────────────────────────────────────────────────────────────────────────────

export function CallDetailPage() {
  const { sessionId } = useParams<{ clientId: string; sessionId: string }>()
  const navigate = useNavigate()

  const {
    data: analysis,
    isLoading,
  } = useCallAnalysis(sessionId ?? '')

  const resolvedSessionId = sessionId ?? ''

  return (
    <div className="space-y-6">
      {/* Back navigation */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="text-sm text-ink-3 hover:text-ink transition-colors"
      >
        ← Back
      </button>

      {/* Page header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-xl font-medium text-ink">
            Call Detail
          </h1>
          <p className="text-xs text-ink-3 mt-0.5 font-mono">
            {resolvedSessionId}
          </p>
        </div>
        {analysis?.classification && (
          <Badge
            status={
              analysis.classification.includes('positive')
                ? 'success'
                : analysis.classification.includes('negative') || analysis.classification === 'hostile'
                  ? 'error'
                  : 'neutral'
            }
          >
            {analysis.classification.replace(/_/g, ' ')}
          </Badge>
        )}
      </div>

      {/* Two-column layout: transcript + analysis */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Transcript column */}
        <section>
          <h2 className="text-base font-semibold text-ink mb-3">Transcript</h2>
          <div className="bg-mist rounded-md border border-line max-h-[700px] overflow-y-auto">
            <TranscriptViewer sessionId={resolvedSessionId} />
          </div>
        </section>

        {/* Analysis column */}
        <section>
          <h2 className="text-base font-semibold text-ink mb-3">Analysis</h2>
          <CallAnalysisPanel analysis={analysis} isLoading={isLoading} />
        </section>
      </div>
    </div>
  )
}
