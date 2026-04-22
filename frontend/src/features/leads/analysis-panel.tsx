/**
 * AnalysisPanel — Presentational component for call analysis display
 *
 * Spec: sdd/qora-post-call-analysis/spec — Requirements:
 *   - Detected Interests Chips
 *   - Identified Problem Card
 *
 * Design: Pure presentational — receives DetectedInterests | null and IdentifiedProblem | null
 *   - Renders nothing when both are null/empty (graceful degradation)
 *   - Shows product/need/signal chips when detected_interests has items
 *   - Shows problem card with primary_need, pain_points, and urgency indicator
 */

import type { DetectedInterests, IdentifiedProblem, Urgency } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Urgency label mapping (centralized)
// ──────────────────────────────────────────────────────────────────────────────

const URGENCY_STYLES: Record<Urgency, string> = {
  high: 'text-error',
  medium: 'text-warning',
  low: 'text-on-surface-variant',
}

// ──────────────────────────────────────────────────────────────────────────────
// Props
// ──────────────────────────────────────────────────────────────────────────────

interface AnalysisPanelProps {
  interests: DetectedInterests | null | undefined
  problem: IdentifiedProblem | null | undefined
}

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function hasInterests(interests: DetectedInterests | null | undefined): boolean {
  if (!interests) return false
  return (
    interests.products.length > 0 ||
    interests.specific_needs.length > 0 ||
    interests.buying_signals.length > 0
  )
}

function Chip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 text-xs rounded-full bg-surface-container text-on-surface-variant border border-outline/20">
      {label}
    </span>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// AnalysisPanel
// ──────────────────────────────────────────────────────────────────────────────

export function AnalysisPanel({ interests, problem }: AnalysisPanelProps) {
  const showInterests = hasInterests(interests)
  const showProblem = !!problem

  // Graceful degradation — pre-Phase-5 calls with no analysis data
  if (!showInterests && !showProblem) return null

  return (
    <div className="space-y-3 mt-3">
      {/* Detected Interests chips */}
      {showInterests && interests && (
        <div data-testid="analysis-interests" className="space-y-1.5">
          <p className="text-xs text-on-surface-variant uppercase tracking-wider">
            Detected Interests
          </p>
          <div className="flex flex-wrap gap-1.5">
            {interests.products.map((product) => (
              <Chip key={`product-${product}`} label={product} />
            ))}
            {interests.specific_needs.map((need) => (
              <Chip key={`need-${need}`} label={need} />
            ))}
            {interests.buying_signals.map((signal) => (
              <Chip key={`signal-${signal}`} label={signal} />
            ))}
          </div>
        </div>
      )}

      {/* Identified Problem card */}
      {showProblem && problem && (
        <div data-testid="analysis-problem" className="space-y-1.5">
          <p className="text-xs text-on-surface-variant uppercase tracking-wider">
            Identified Problem
          </p>
          <div className="bg-surface-container-low rounded-md p-3 space-y-2">
            {/* Primary need */}
            <p className="text-sm text-on-surface">{problem.primary_need}</p>

            {/* Urgency indicator */}
            <p className={['text-xs font-medium uppercase', URGENCY_STYLES[problem.urgency]].join(' ')}>
              {problem.urgency} urgency
            </p>

            {/* Pain points */}
            {problem.pain_points.length > 0 && (
              <ul className="space-y-0.5">
                {problem.pain_points.map((point) => (
                  <li key={point} className="text-xs text-on-surface-variant flex items-start gap-1">
                    <span className="mt-0.5 text-on-surface-variant/60">•</span>
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
