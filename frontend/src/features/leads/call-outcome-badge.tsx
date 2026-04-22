/**
 * CallOutcomeBadge — Presentational component for call outcome display
 *
 * Spec: sdd/qora-post-call-analysis/spec — Requirements:
 *   - Per-Call Outcome Badge
 *   - Engagement Quality Indicator
 *
 * Design: Pure presentational — receives CallOutcome | null | undefined
 *   - Renders nothing when outcome is null/undefined (graceful degradation)
 *   - Shows classification label as colored badge
 *   - Shows engagement quality as visual indicator (role="img" for a11y)
 */

import type { CallOutcome, OutcomeClassification, EngagementQuality } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Label + color mappings (centralized per design pattern)
// ──────────────────────────────────────────────────────────────────────────────

export const OUTCOME_LABELS: Record<OutcomeClassification, string> = {
  interested: 'Interested',
  not_interested: 'Not Interested',
  busy: 'Busy',
  follow_up: 'Follow Up',
  no_answer: 'No Answer',
  hostile: 'Hostile',
  confused: 'Confused',
}

export const OUTCOME_STYLES: Record<OutcomeClassification, string> = {
  interested: 'bg-primary/20 text-primary',
  not_interested: 'bg-surface-bright/60 text-on-surface-variant',
  busy: 'bg-warning/20 text-warning',
  follow_up: 'bg-secondary/20 text-secondary',
  no_answer: 'bg-surface-bright/60 text-on-surface-variant',
  hostile: 'bg-error/20 text-error',
  confused: 'bg-warning/20 text-warning',
}

export const ENGAGEMENT_ICONS: Record<EngagementQuality, { symbol: string; label: string }> = {
  high: { symbol: '●●●', label: 'high' },
  medium: { symbol: '●●○', label: 'medium' },
  low: { symbol: '●○○', label: 'low' },
  none: { symbol: '○○○', label: 'none' },
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
  const engagementInfo = ENGAGEMENT_ICONS[outcome.engagement_quality] ?? ENGAGEMENT_ICONS.none

  return (
    <span className="inline-flex items-center gap-1.5">
      {/* Classification badge */}
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

      {/* Engagement quality indicator */}
      <span
        role="img"
        aria-label={`${engagementInfo.label} engagement`}
        className="text-xs text-on-surface-variant font-mono"
        title={`Engagement: ${engagementInfo.label}`}
      >
        {engagementInfo.symbol}
      </span>
    </span>
  )
}
