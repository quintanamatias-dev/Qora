/**
 * PeriodSelector — Radix ToggleGroup wrapper for period filtering
 *
 * Design: single-select, always has one active value (no deselect)
 * Sovereign Interface: no borders, obsidian-surface active state
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
      className="flex gap-1"
      aria-label="Select time period"
    >
      {PERIODS.map(period => (
        <ToggleGroup.Item
          key={period.value}
          value={period.value}
          className="px-3 py-1 text-sm font-medium text-on-surface-variant data-[state=on]:bg-surface-bright data-[state=on]:text-on-surface focus:outline-none"
        >
          {period.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  )
}
