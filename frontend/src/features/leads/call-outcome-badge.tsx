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
  no_answer: 'bg-surface-bright/60 text-on-surface-variant',
  busy: 'bg-warning/20 text-warning',
  callback_requested: 'bg-secondary/20 text-secondary',
  completed_positive: 'bg-primary/20 text-primary',
  completed_neutral: 'bg-surface-bright/60 text-on-surface-variant',
  completed_negative: 'bg-error/10 text-error',
  do_not_contact: 'bg-error/20 text-error',
  wrong_number: 'bg-surface-bright/60 text-on-surface-variant',
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
  const style = OUTCOME_STYLES[outcome.classification] ?? 'bg-surface-bright/60 text-on-surface-variant'

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
