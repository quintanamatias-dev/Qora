/**
 * CallOutcomeBadge — Presentational component for call outcome display
 *
 * Spec: sdd/qora-outcome/spec — Requirement: CallOutcomeBadge Component
 * Issue #50: 11 classifications, no engagement_quality indicator.
 *
 * Design: Pure presentational — receives CallOutcome | null | undefined
 *   - Renders nothing when outcome is null/undefined (graceful degradation)
 *   - Shows classification label as colored badge
 *   - NO engagement quality indicator (engagement_quality removed)
 */

import type { CallOutcome, OutcomeClassification } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Label + color mappings (11 classifications)
// ──────────────────────────────────────────────────────────────────────────────

export const OUTCOME_LABELS: Record<OutcomeClassification, string> = {
  no_answer: 'No Answer',
  busy: 'Busy',
  callback_requested: 'Callback Requested',
  completed_positive: 'Completed Positive',
  completed_neutral: 'Completed Neutral',
  completed_negative: 'Completed Negative',
  do_not_contact: 'Do Not Contact',
  wrong_number: 'Wrong Number',
  hostile: 'Hostile',
  confused: 'Confused',
  technical_issue: 'Technical Issue',
}

export const OUTCOME_STYLES: Record<OutcomeClassification, string> = {
  no_answer: 'bg-mist text-ink-3',
  busy: 'bg-warning/20 text-warning',
  callback_requested: 'bg-mist text-ink-2',
  completed_positive: 'bg-teal-faint text-teal',
  completed_neutral: 'bg-mist text-ink-3',
  completed_negative: 'bg-error/10 text-error',
  do_not_contact: 'bg-error/20 text-error',
  wrong_number: 'bg-mist text-ink-3',
  hostile: 'bg-error/20 text-error',
  confused: 'bg-warning/20 text-warning',
  technical_issue: 'bg-warning/10 text-warning',
}

// ──────────────────────────────────────────────────────────────────────────────
// Props
// ──────────────────────────────────────────────────────────────────────────────

interface CallOutcomeBadgeProps {
  outcome: CallOutcome | null | undefined
}

// ──────────────────────────────────────────────────────────────────────────────
// CallOutcomeBadge
// ──────────────────────────────────────────────────────────────────────────────

export function CallOutcomeBadge({ outcome }: CallOutcomeBadgeProps) {
  // Graceful degradation — legacy calls without analysis data
  if (!outcome) return null

  const label = OUTCOME_LABELS[outcome.classification] ?? outcome.classification
  const style = OUTCOME_STYLES[outcome.classification] ?? 'bg-mist text-ink-3'

  return (
    <span
      className={[
        'inline-flex items-center',
        'px-2 py-0.5',
        'text-xs font-medium uppercase tracking-wider',
        'rounded-sm',
        style,
      ].join(' ')}
    >
      {label}
    </span>
  )
}
