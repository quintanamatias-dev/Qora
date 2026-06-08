/**
 * StatusBreakdown — CSS-only horizontal stacked bar
 *
 * Spec: completed (teal) + abandoned (coral) flex segments with % labels
 * Design: no SVG, no chart library — pure flex + inline width percentages
 * Background: bg-mist (Qora light surface)
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
      <div className="flex h-3 w-full overflow-hidden bg-mist rounded-full">
        <div
          data-testid="segment-completed"
          className="bg-teal h-full flex-shrink-0"
          style={{ width: `${completedPct}%` }}
        />
        {abandonedPct > 0 && (
          <div
            data-testid="segment-abandoned"
            className="bg-coral h-full flex-shrink-0"
            style={{ width: `${abandonedPct}%` }}
          />
        )}
      </div>

      {/* Percentage labels */}
      <div className="flex gap-4 text-xs text-ink-3 font-mono">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-teal" />
          {completedPct}%
        </span>
        {abandonedPct > 0 && (
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm bg-coral" />
            {abandonedPct}%
          </span>
        )}
      </div>
    </div>
  )
}
