/**
 * CallDetailPage — Container page for call detail view
 *
 * Shows full transcript + all 12 analysis dimensions for a specific call session.
 * Design: Container-presentational pattern — reads sessionId from URL params,
 *   fetches analysis + transcript, and composes the Transcript card together
 *   with AnalysisSectionCards in ONE shared responsive masonry (CSS-columns)
 *   flow so analysis cards fill the space below a short transcript.
 *
 * Route: /app/:clientId/calls/:sessionId
 */

import { useParams, useNavigate } from 'react-router'
import { useCallAnalysis } from '@/api/hooks'
import { AnalysisSectionCards } from './call-analysis-panel'
import { TranscriptViewer } from '../leads/transcript-viewer'
import { Badge } from '@/design/components/badge'
import { Card } from '@/design/components/card'

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
        Unified masonry flow (NOT sticky, NOT a separate floated region):
        the Transcript and ALL analysis sections live in ONE shared CSS-columns
        area. The Transcript is simply the FIRST card in that flow, so it lands
        top-left, and the analysis cards flow through the same balanced columns —
        which means short analysis cards (Profile Facts, Notes, Data Corrections,
        …) fill the empty space BELOW a short transcript in the left column
        instead of all analysis staying to the right.

        Columns: 1 on small, 2 on `lg`, 3 on `2xl`. `[column-fill:balance]`
        keeps the columns roughly equal height so cards fan out evenly rather
        than piling into one tall column. Each card uses `break-inside-avoid` so
        it never splits across a column boundary.

        The transcript stays internally scrollable (max-height + overflow) so a
        very long transcript does not dominate the column, but it is never
        `sticky`/`fixed` — it scrolls away with the rest of the page.
      */}
      <div
        data-testid="call-detail-content"
        className="columns-1 lg:columns-2 2xl:columns-3 gap-4 [column-fill:balance]"
      >
        {/* Transcript — FIRST card in the shared flow (top-left), not pinned */}
        <section
          data-testid="transcript-region"
          className="mb-4 break-inside-avoid min-w-0"
        >
          <Card className="p-0 overflow-hidden">
            <h2 className="text-base font-semibold text-ink px-4 pt-4 pb-3">
              Transcript
            </h2>
            <div className="bg-mist border-t border-line max-h-[calc(100vh-12rem)] overflow-y-auto">
              <TranscriptViewer sessionId={resolvedSessionId} />
            </div>
          </Card>
        </section>

        {/*
          Analysis sections — flat cards in the SAME column flow as the
          transcript above. No separate floated/sticky region and no fixed grid
          column: the cards simply continue the masonry, filling space under the
          transcript and across the remaining columns.
        */}
        {isError ? (
          <section data-testid="analysis-region" className="mb-4 break-inside-avoid min-w-0">
            <div
              data-testid="analysis-error"
              className="py-6 text-center border border-error/30 bg-error/5 rounded-md"
            >
              <p className="text-error text-sm">
                Failed to load analysis. Please try again.
              </p>
            </div>
          </section>
        ) : (
          <AnalysisSectionCards analysis={analysis} isLoading={isLoading} />
        )}
      </div>
    </div>
  )
}
