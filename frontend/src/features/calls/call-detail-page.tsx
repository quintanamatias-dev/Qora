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
    isError,
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

      {/*
        Two-region layout: transcript (left, narrow, sticky) + analysis (right,
        wide). The transcript is a self-contained sticky column so it stays in
        view while the analysis region scrolls — this avoids the previous large
        empty gray area below a short transcript. The analysis region takes the
        wider share of the page (3/5 on lg) and flows its own dense card grid.
      */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 items-start">
        {/* Transcript column — narrow + sticky so it tracks the analysis scroll */}
        <section
          data-testid="transcript-region"
          className="lg:col-span-2 lg:sticky lg:top-24"
        >
          <h2 className="text-base font-semibold text-ink mb-3">Transcript</h2>
          <div className="bg-mist rounded-md border border-line max-h-[calc(100vh-9rem)] overflow-y-auto">
            <TranscriptViewer sessionId={resolvedSessionId} />
          </div>
        </section>

        {/* Analysis region — wide, fills the page area alongside/below transcript */}
        <section data-testid="analysis-region" className="lg:col-span-3 min-w-0">
          <h2 className="text-base font-semibold text-ink mb-3">Analysis</h2>
          {isError ? (
            <div
              data-testid="analysis-error"
              className="py-6 text-center border border-error/30 bg-error/5 rounded-md"
            >
              <p className="text-error text-sm">
                Failed to load analysis. Please try again.
              </p>
            </div>
          ) : (
            <CallAnalysisPanel analysis={analysis} isLoading={isLoading} />
          )}
        </section>
      </div>
    </div>
  )
}
