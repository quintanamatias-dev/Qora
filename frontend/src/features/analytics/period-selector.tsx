/**
 * PeriodSelector — Analytics period tab selector
 *
 * Allows selecting: day | week | month | custom
 * Design: simple button group, matches spec requirement.
 */

import type { AnalyticsPeriod } from '@/api/types'

interface PeriodSelectorProps {
  value: AnalyticsPeriod
  onChange: (period: AnalyticsPeriod) => void
}

const PERIODS: { value: AnalyticsPeriod; label: string }[] = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: 'custom', label: 'Custom' },
]

export function PeriodSelector({ value, onChange }: PeriodSelectorProps) {
  return (
    <div className="flex gap-1 rounded-md border border-border p-1 bg-surface-container-low">
      {PERIODS.map((p) => (
        <button
          key={p.value}
          type="button"
          onClick={() => onChange(p.value)}
          className={[
            'px-3 py-1 text-sm font-medium rounded transition-colors',
            value === p.value
              ? 'bg-primary text-on-primary'
              : 'text-on-surface-variant hover:text-on-surface',
          ].join(' ')}
        >
          {p.label}
        </button>
      ))}
    </div>
  )
}
