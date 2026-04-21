/**
 * PeriodSelector — Unit tests
 *
 * Spec: sdd/qora-dashboard-metrics/spec — Requirement: Period Selection
 * Design: Radix ToggleGroup (single mode), Today/7d/30d/All options
 *
 * TDD Layer: Integration (RTL render + userEvent)
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PeriodSelector } from './period-selector'

describe('PeriodSelector — renders all options', () => {
  it('renders "Today" option', () => {
    render(<PeriodSelector value="today" onChange={vi.fn()} />)
    expect(screen.getByText('Today')).toBeInTheDocument()
  })

  it('renders "7d" option', () => {
    render(<PeriodSelector value="today" onChange={vi.fn()} />)
    expect(screen.getByText('7d')).toBeInTheDocument()
  })

  it('renders "30d" option', () => {
    render(<PeriodSelector value="today" onChange={vi.fn()} />)
    expect(screen.getByText('30d')).toBeInTheDocument()
  })

  it('renders "All" option', () => {
    render(<PeriodSelector value="today" onChange={vi.fn()} />)
    expect(screen.getByText('All')).toBeInTheDocument()
  })

  it('renders exactly 4 toggle options', () => {
    render(<PeriodSelector value="today" onChange={vi.fn()} />)
    const buttons = screen.getAllByRole('radio')
    expect(buttons).toHaveLength(4)
  })
})

describe('PeriodSelector — active state', () => {
  it('marks "Today" as active when value is "today"', () => {
    render(<PeriodSelector value="today" onChange={vi.fn()} />)
    expect(screen.getByRole('radio', { name: 'Today' })).toHaveAttribute('data-state', 'on')
  })

  it('marks "7d" as active when value is "7d"', () => {
    render(<PeriodSelector value="7d" onChange={vi.fn()} />)
    expect(screen.getByRole('radio', { name: '7d' })).toHaveAttribute('data-state', 'on')
  })

  it('marks "30d" as active when value is "30d"', () => {
    render(<PeriodSelector value="30d" onChange={vi.fn()} />)
    expect(screen.getByRole('radio', { name: '30d' })).toHaveAttribute('data-state', 'on')
  })

  it('marks "All" as active when value is "all"', () => {
    render(<PeriodSelector value="all" onChange={vi.fn()} />)
    expect(screen.getByRole('radio', { name: 'All' })).toHaveAttribute('data-state', 'on')
  })

  it('marks only one option as active at a time', () => {
    render(<PeriodSelector value="7d" onChange={vi.fn()} />)
    const activeButtons = screen.getAllByRole('radio').filter(
      btn => btn.getAttribute('data-state') === 'on'
    )
    expect(activeButtons).toHaveLength(1)
  })
})

describe('PeriodSelector — onChange callback', () => {
  it('calls onChange with "7d" when 7d is clicked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<PeriodSelector value="today" onChange={onChange} />)
    await user.click(screen.getByRole('radio', { name: '7d' }))
    expect(onChange).toHaveBeenCalledWith('7d')
  })

  it('calls onChange with "30d" when 30d is clicked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<PeriodSelector value="today" onChange={onChange} />)
    await user.click(screen.getByRole('radio', { name: '30d' }))
    expect(onChange).toHaveBeenCalledWith('30d')
  })

  it('calls onChange with "all" when All is clicked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<PeriodSelector value="today" onChange={onChange} />)
    await user.click(screen.getByRole('radio', { name: 'All' }))
    expect(onChange).toHaveBeenCalledWith('all')
  })

  it('does NOT call onChange when clicking the already-active option', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<PeriodSelector value="today" onChange={onChange} />)
    await user.click(screen.getByRole('radio', { name: 'Today' }))
    // Radix ToggleGroup type="single" does not deselect when clicking current value
    // onChange only fires when value CHANGES
    expect(onChange).not.toHaveBeenCalled()
  })
})
