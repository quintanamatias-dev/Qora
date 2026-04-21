/**
 * StatusBreakdown — Unit tests
 *
 * Spec: sdd/qora-dashboard-metrics/spec — Requirement: Status Breakdown Bar
 * Design: CSS-only flex stacked bar, no SVG/chart library
 *
 * TDD Layer: Integration (RTL render + behavioral assertions on text/style)
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusBreakdown } from './status-breakdown'

describe('StatusBreakdown — normal split', () => {
  it('renders completed percentage label (≈79% for 98/124)', () => {
    render(<StatusBreakdown completed={98} abandoned={26} total={124} />)
    // 98/124 = 79.03... → displayed as "79%"
    expect(screen.getByText('79%')).toBeInTheDocument()
  })

  it('renders abandoned percentage label (≈21% for 26/124)', () => {
    render(<StatusBreakdown completed={98} abandoned={26} total={124} />)
    // 26/124 = 20.96... → displayed as "21%"
    expect(screen.getByText('21%')).toBeInTheDocument()
  })

  it('renders completed segment with correct inline width style', () => {
    render(<StatusBreakdown completed={98} abandoned={26} total={124} />)
    const completedSegment = screen.getByTestId('segment-completed')
    expect(completedSegment).toHaveStyle({ width: '79%' })
  })

  it('renders abandoned segment with correct inline width style', () => {
    render(<StatusBreakdown completed={98} abandoned={26} total={124} />)
    const abandonedSegment = screen.getByTestId('segment-abandoned')
    expect(abandonedSegment).toHaveStyle({ width: '21%' })
  })
})

describe('StatusBreakdown — all completed (no abandoned)', () => {
  it('renders "100%" completed label', () => {
    render(<StatusBreakdown completed={50} abandoned={0} total={50} />)
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('does NOT render the abandoned segment when abandoned = 0', () => {
    render(<StatusBreakdown completed={50} abandoned={0} total={50} />)
    expect(screen.queryByTestId('segment-abandoned')).not.toBeInTheDocument()
  })

  it('completed segment occupies 100% width', () => {
    render(<StatusBreakdown completed={50} abandoned={0} total={50} />)
    expect(screen.getByTestId('segment-completed')).toHaveStyle({ width: '100%' })
  })
})

describe('StatusBreakdown — zero total fallback', () => {
  it('does not crash when total = 0', () => {
    render(<StatusBreakdown completed={0} abandoned={0} total={0} />)
    // Should render without error — show empty bar or "0%" state
    expect(screen.getByTestId('status-breakdown')).toBeInTheDocument()
  })

  it('shows "0%" label when total = 0', () => {
    render(<StatusBreakdown completed={0} abandoned={0} total={0} />)
    expect(screen.getByText('0%')).toBeInTheDocument()
  })
})

describe('StatusBreakdown — percentage labels visible', () => {
  it('renders both percentage labels for a normal split', () => {
    render(<StatusBreakdown completed={75} abandoned={25} total={100} />)
    expect(screen.getByText('75%')).toBeInTheDocument()
    expect(screen.getByText('25%')).toBeInTheDocument()
  })

  it('renders "0%" for abandoned when abandoned = 0 is NOT shown as segment', () => {
    // When abandoned = 0, segment not rendered, no "0%" label needed for abandoned
    render(<StatusBreakdown completed={100} abandoned={0} total={100} />)
    // 100% shows for completed
    expect(screen.getByText('100%')).toBeInTheDocument()
    // No abandoned segment = no "0%" label needed for it
    expect(screen.queryByTestId('segment-abandoned')).not.toBeInTheDocument()
  })
})
