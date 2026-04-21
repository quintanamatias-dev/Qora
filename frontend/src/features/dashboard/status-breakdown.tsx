/**
 * StatusBreakdown — CSS-only horizontal stacked bar
 *
 * Spec: completed (emerald) + abandoned (red) flex segments with % labels
 * Design: no SVG, no chart library — pure flex + inline width percentages
 * Background: surface-container-lowest per DESIGN.md inset rule
 */

interface StatusBreakdownProps {
  completed: number
  abandoned: number
  total: number
}

export function StatusBreakdown({ completed, abandoned, total }: StatusBreakdownProps) {
  const completedPct = total > 0 ? Math.round((completed / total) * 100) : 0
  const abandonedPct = total > 0 ? Math.round((abandoned / total) * 100) : 0

  return (
    <div data-testid="status-breakdown" className="space-y-2">
      {/* Stacked bar */}
      <div className="flex h-3 w-full overflow-hidden bg-surface-container-lowest rounded-sm">
        <div
          data-testid="segment-completed"
          className="bg-primary h-full flex-shrink-0"
          style={{ width: `${completedPct}%` }}
        />
        {abandonedPct > 0 && (
          <div
            data-testid="segment-abandoned"
            className="bg-error h-full flex-shrink-0"
            style={{ width: `${abandonedPct}%` }}
          />
        )}
      </div>

      {/* Percentage labels */}
      <div className="flex gap-4 text-xs text-on-surface-variant">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-primary" />
          {completedPct}%
        </span>
        {abandonedPct > 0 && (
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm bg-error" />
            {abandonedPct}%
          </span>
        )}
      </div>
    </div>
  )
}
