/**
 * PeriodSelector — Radix ToggleGroup wrapper for period filtering
 *
 * Design: single-select, always has one active value (no deselect)
 * Qora Design System: active state bg-teal-faint text-teal, inactive text-ink-3
 *
 * Spec: Today | 7d | 30d | All — default is "today"
 */

import * as ToggleGroup from '@radix-ui/react-toggle-group'

export type Period = 'today' | '7d' | '30d' | 'all'

interface PeriodSelectorProps {
  value: Period
  onChange: (period: Period) => void
}

const PERIODS: { value: Period; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: 'all', label: 'All' },
]

export function PeriodSelector({ value, onChange }: PeriodSelectorProps) {
  function handleValueChange(next: string) {
    // ToggleGroup fires with empty string if user clicks active item
    // We enforce always-one-selected: ignore empty values
    if (next && next !== value) {
      onChange(next as Period)
    }
  }

  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      onValueChange={handleValueChange}
      className="flex gap-1 bg-mist rounded-md p-1"
      aria-label="Select time period"
    >
      {PERIODS.map(period => (
        <ToggleGroup.Item
          key={period.value}
          value={period.value}
          className="px-3 py-1 text-sm font-medium rounded-md text-ink-3 data-[state=on]:bg-teal-faint data-[state=on]:text-teal focus:outline-none transition-colors duration-150"
        >
          {period.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  )
}
