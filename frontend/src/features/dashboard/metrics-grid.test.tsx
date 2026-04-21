/**
 * MetricsGrid — Unit tests
 *
 * Spec: sdd/qora-dashboard-metrics/spec — Requirement: Stat Cards Grid
 * Design: 4-card primary grid + 2-card secondary grid + StatusBreakdown
 *
 * TDD Layer: Integration (RTL render + text assertions on formatted values)
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MetricsGrid } from './metrics-grid'
import type { CallMetricsResponse } from '@/api/types'

const mockData: CallMetricsResponse = {
  total_calls: 124,
  completed_calls: 98,
  abandoned_calls: 26,
  total_duration_seconds: 7200,
  average_duration_seconds: 125,
  total_billable_minutes: 120,
  period: { date_from: '2026-01-01', date_to: '2026-01-07' },
}

describe('MetricsGrid — renders all 6 KPI cards', () => {
  it('renders "Total Calls" label', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('Total Calls')).toBeInTheDocument()
  })

  it('renders "Completed" label', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('Completed')).toBeInTheDocument()
  })

  it('renders "Abandoned" label', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('Abandoned')).toBeInTheDocument()
  })

  it('renders "Avg Duration" label', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('Avg Duration')).toBeInTheDocument()
  })

  it('renders "Total Duration" label', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('Total Duration')).toBeInTheDocument()
  })

  it('renders "Billable Minutes" label', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('Billable Minutes')).toBeInTheDocument()
  })
})

describe('MetricsGrid — formatted values', () => {
  it('renders total_calls as integer string "124"', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('124')).toBeInTheDocument()
  })

  it('renders completed_calls as integer string "98"', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('98')).toBeInTheDocument()
  })

  it('renders abandoned_calls as integer string "26"', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('26')).toBeInTheDocument()
  })

  it('renders average_duration_seconds (125s) formatted as "2:05"', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('2:05')).toBeInTheDocument()
  })

  it('renders total_duration_seconds (7200s) formatted as "2h 0m"', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('2h 0m')).toBeInTheDocument()
  })

  it('renders total_billable_minutes as "120 min"', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('120 min')).toBeInTheDocument()
  })
})

describe('MetricsGrid — loading pass-through', () => {
  it('renders skeleton cards when loading=true', () => {
    render(<MetricsGrid data={mockData} loading />)
    const skeletons = screen.getAllByTestId('stat-skeleton')
    expect(skeletons).toHaveLength(6)
  })

  it('renders values when loading=false', () => {
    render(<MetricsGrid data={mockData} loading={false} />)
    expect(screen.getByText('124')).toBeInTheDocument()
    expect(screen.queryByTestId('stat-skeleton')).not.toBeInTheDocument()
  })
})

describe('MetricsGrid — status breakdown composition', () => {
  it('renders the status breakdown bar', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByTestId('status-breakdown')).toBeInTheDocument()
  })

  it('passes correct percentages to StatusBreakdown (98/124 → 79%)', () => {
    render(<MetricsGrid data={mockData} />)
    expect(screen.getByText('79%')).toBeInTheDocument()
  })
})
