/**
 * StatCard — Unit tests
 *
 * Spec: sdd/qora-dashboard-metrics/spec — Requirement: Stat Cards Grid
 * Design: stat-card.tsx in features/dashboard/ (feature-specific, not design primitive)
 *
 * TDD Layer: Integration (RTL render + behavioral assertions)
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatCard } from './stat-card'

describe('StatCard — label and value rendering', () => {
  it('renders the label text', () => {
    render(<StatCard label="Total Calls" value="42" />)
    expect(screen.getByText('Total Calls')).toBeInTheDocument()
  })

  it('renders the value text', () => {
    render(<StatCard label="Total Calls" value="42" />)
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('renders numeric value as string', () => {
    render(<StatCard label="Avg Duration" value="2:05" />)
    expect(screen.getByText('2:05')).toBeInTheDocument()
  })

  it('renders a different label-value pair', () => {
    render(<StatCard label="Billable Minutes" value="35 min" />)
    expect(screen.getByText('Billable Minutes')).toBeInTheDocument()
    expect(screen.getByText('35 min')).toBeInTheDocument()
  })
})

describe('StatCard — accent prop', () => {
  it('exposes data-accent="primary" for emerald/completed card', () => {
    render(<StatCard label="Completed" value="35" accent="primary" data-testid="card" />)
    expect(screen.getByTestId('card')).toHaveAttribute('data-accent', 'primary')
  })

  it('exposes data-accent="error" for red/abandoned card', () => {
    render(<StatCard label="Abandoned" value="7" accent="error" data-testid="card" />)
    expect(screen.getByTestId('card')).toHaveAttribute('data-accent', 'error')
  })

  it('exposes data-accent="secondary" for violet/billable card', () => {
    render(<StatCard label="Billable" value="35 min" accent="secondary" data-testid="card" />)
    expect(screen.getByTestId('card')).toHaveAttribute('data-accent', 'secondary')
  })

  it('does NOT set data-accent when no accent is provided', () => {
    render(<StatCard label="Total Calls" value="42" data-testid="card" />)
    expect(screen.getByTestId('card')).not.toHaveAttribute('data-accent')
  })
})

describe('StatCard — loading skeleton', () => {
  it('renders skeleton placeholder when loading=true', () => {
    render(<StatCard label="Total Calls" value="42" loading data-testid="card" />)
    expect(screen.getByTestId('card')).toBeInTheDocument()
    expect(screen.getByTestId('stat-skeleton')).toBeInTheDocument()
  })

  it('does NOT render the value when loading=true', () => {
    render(<StatCard label="Total Calls" value="42" loading />)
    expect(screen.queryByText('42')).not.toBeInTheDocument()
  })

  it('still renders the label when loading=true', () => {
    render(<StatCard label="Total Calls" value="42" loading />)
    expect(screen.getByText('Total Calls')).toBeInTheDocument()
  })

  it('renders value when loading=false', () => {
    render(<StatCard label="Total Calls" value="42" loading={false} />)
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.queryByTestId('stat-skeleton')).not.toBeInTheDocument()
  })
})

describe('StatCard — className passthrough', () => {
  it('applies additional className to root element', () => {
    render(<StatCard label="Total Calls" value="42" className="custom-class" data-testid="card" />)
    expect(screen.getByTestId('card')).toHaveClass('custom-class')
  })
})
