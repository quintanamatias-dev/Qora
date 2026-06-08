/**
 * AnalysisPanel — Presentational component for call analysis display
 *
 * Spec: sdd/qora-post-call-analysis/spec — Requirements:
 *   - Detected Interests Chips
 *   - Identified Problem Card (qora-problem: ProblemAxis / PainPoint)
 *
 * Design: Pure presentational — receives DetectedInterests | null and ProblemAxis | null
 *   - Renders nothing when both are null/empty (graceful degradation)
 *   - Shows product/need/signal chips when detected_interests has items
 *   - Shows pain point cards: primary highlighted, others listed with category + description
 */

import type { DetectedInterests, ProblemAxis, PainPoint } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Urgency label mapping (centralized)
// ──────────────────────────────────────────────────────────────────────────────

const URGENCY_STYLES: Record<string, string> = {
  high: 'text-error',
  medium: 'text-warning',
  low: 'text-ink-3',
  unknown: 'text-ink-3',
}

// Category display labels
const CATEGORY_LABELS: Record<string, string> = {
  cost: 'Costo',
  coverage: 'Cobertura',
  renewal: 'Renovación',
  bad_experience: 'Mala experiencia',
  lack_of_clarity: 'Falta de claridad',
  new_need: 'Nueva necesidad',
  risk_exposure: 'Exposición al riesgo',
  comparison: 'Comparación',
  deadline: 'Plazo / Urgencia',
  dissatisfaction: 'Insatisfacción',
  other: 'Otro',
}

// ──────────────────────────────────────────────────────────────────────────────
// Props
// ──────────────────────────────────────────────────────────────────────────────

interface AnalysisPanelProps {
  interests: DetectedInterests | null | undefined
  problem: ProblemAxis | null | undefined
}

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function hasInterests(interests: DetectedInterests | null | undefined): boolean {
  if (!interests) return false
  return (
    (interests.products?.length ?? 0) > 0 ||
    (interests.specific_needs?.length ?? 0) > 0 ||
    (interests.buying_signals?.length ?? 0) > 0
  )
}

function hasProblem(problem: ProblemAxis | null | undefined): boolean {
  if (!problem) return false
  return (problem.pain_points?.length ?? 0) > 0
}

function Chip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 text-xs rounded-full bg-mist text-ink-3 border border-line">
      {label}
    </span>
  )
}

function CategoryBadge({ category }: { category: string }) {
  const label = CATEGORY_LABELS[category] ?? category
  return (
    <span
      data-testid="pain-point-category"
      className="inline-flex items-center px-1.5 py-0.5 text-xs rounded bg-mist text-ink-3"
    >
      {label}
    </span>
  )
}

function PainPointItem({ point }: { point: PainPoint }) {
  return (
    <li className="space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <CategoryBadge category={point.category} />
        {point.is_primary && (
          <span
            data-testid="pain-point-primary"
            className="inline-flex items-center px-1.5 py-0.5 text-xs rounded bg-teal-faint text-teal font-medium"
          >
            Principal
          </span>
        )}
        <span
          data-testid="pain-point-urgency"
          className={['text-xs font-medium uppercase', URGENCY_STYLES[point.urgency] ?? 'text-ink-3'].join(' ')}
        >
          {point.urgency}
        </span>
      </div>
      <p data-testid="pain-point-description" className="text-sm text-ink">
        {point.description}
      </p>
      {point.evidence && (
        <p
          data-testid="pain-point-evidence"
          className="text-xs text-ink-3 italic border-l-2 border-line-2 pl-2"
        >
          "{point.evidence}"
        </p>
      )}
    </li>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// AnalysisPanel
// ──────────────────────────────────────────────────────────────────────────────

export function AnalysisPanel({ interests, problem }: AnalysisPanelProps) {
  const showInterests = hasInterests(interests)
  const showProblem = hasProblem(problem)

  // Graceful degradation — pre-Phase-5 calls with no analysis data
  if (!showInterests && !showProblem) return null

  // Sort pain points: primary first, then by category
  const sortedPains = problem?.pain_points
    ? [...problem.pain_points].sort((a, b) => {
        if (a.is_primary && !b.is_primary) return -1
        if (!a.is_primary && b.is_primary) return 1
        return 0
      })
    : []

  return (
    <div className="space-y-3 mt-3">
      {/* Detected Interests chips */}
      {showInterests && interests && (
        <div data-testid="analysis-interests" className="space-y-1.5">
          <p className="text-xs text-ink-3 uppercase tracking-wider">
            Detected Interests
          </p>
          <div className="flex flex-wrap gap-1.5">
            {interests.products?.map((product) => (
              <Chip key={`product-${product}`} label={product} />
            ))}
            {interests.specific_needs?.map((need) => (
              <Chip key={`need-${need}`} label={need} />
            ))}
            {interests.buying_signals?.map((signal) => (
              <Chip key={`signal-${signal}`} label={signal} />
            ))}
          </div>
        </div>
      )}

      {/* Identified Problem card */}
      {showProblem && problem && (
        <div data-testid="analysis-problem" className="space-y-1.5">
          <p className="text-xs text-ink-3 uppercase tracking-wider">
            Identified Problem
          </p>
          <div className="bg-paper border border-line rounded-md p-3">
            <ul className="space-y-3">
              {sortedPains.map((point, idx) => (
                <PainPointItem key={`${point.category}-${idx}`} point={point} />
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
