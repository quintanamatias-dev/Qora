/**
 * PeriodSelector — Analytics period Seg control
 *
 * Design: qora-presentacion/project/dashboard/ui.jsx Seg — plain buttons,
 * "on" class marks the active option. Options: Día | Semana | Mes | Personalizado.
 */

import type { AnalyticsPeriod } from '@/api/types'

interface PeriodSelectorProps {
  value: AnalyticsPeriod
  onChange: (period: AnalyticsPeriod) => void
}

const PERIODS: [AnalyticsPeriod, string][] = [
  ['day', 'Día'],
  ['week', 'Semana'],
  ['month', 'Mes'],
  ['custom', 'Personalizado'],
]

export function PeriodSelector({ value, onChange }: PeriodSelectorProps) {
  return (
    <div className="seg">
      {PERIODS.map(([k, l]) => (
        <button key={k} type="button" className={value === k ? 'on' : ''} onClick={() => onChange(k)}>
          {l}
        </button>
      ))}
    </div>
  )
}
