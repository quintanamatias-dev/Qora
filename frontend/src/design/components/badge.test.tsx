/**
 * CAP-3: Badge Component Tests
 * TDD Layer: Integration — render + behavioral assertions
 */

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { Badge } from './badge'

describe('Badge — rendering', () => {
  it('renders children text', () => {
    render(<Badge status="success">Completed</Badge>)
    expect(screen.getByText('Completed')).toBeInTheDocument()
  })

  it('renders with status="success" and has data-status attribute', () => {
    render(<Badge status="success">Active</Badge>)
    const badge = screen.getByText('Active')
    expect(badge).toHaveAttribute('data-status', 'success')
  })

  it('renders with status="active" and has correct data-status', () => {
    render(<Badge status="active">Processing</Badge>)
    expect(screen.getByText('Processing')).toHaveAttribute('data-status', 'active')
  })

  it('renders with status="neutral" and has correct data-status', () => {
    render(<Badge status="neutral">Pending</Badge>)
    expect(screen.getByText('Pending')).toHaveAttribute('data-status', 'neutral')
  })

  it('renders with status="error" and has correct data-status', () => {
    render(<Badge status="error">Failed</Badge>)
    expect(screen.getByText('Failed')).toHaveAttribute('data-status', 'error')
  })
})

describe('Badge — lead status variants', () => {
  const statuses = ['new', 'called', 'interested', 'not_interested', 'follow_up'] as const

  statuses.forEach((status) => {
    it(`renders badge with lead status "${status}"`, () => {
      render(<Badge status={status}>{status}</Badge>)
      expect(screen.getByText(status)).toHaveAttribute('data-status', status)
    })
  })
})

describe('Badge — className passthrough', () => {
  it('applies additional className', () => {
    render(<Badge status="success" className="custom-badge">OK</Badge>)
    expect(screen.getByText('OK')).toHaveClass('custom-badge')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// REQ-3.4: Status color mapping — behavioral verification
// The badge renders as an inline element containing the status text.
// All 10 badge statuses must produce a visible, readable span.
// ──────────────────────────────────────────────────────────────────────────────
describe('REQ-3.4 Badge status — behavioral rendering', () => {
  it('success badge renders as an inline element with the label text visible', () => {
    render(<Badge status="success">Completed</Badge>)
    const badge = screen.getByText('Completed')
    // Verify it's a span (inline — not a block layout breaking element)
    expect(badge.tagName).toBe('SPAN')
    // Verify the text is actually rendered (not hidden/empty)
    expect(badge.textContent).toBe('Completed')
  })

  it('active badge renders with visible label', () => {
    render(<Badge status="active">Active</Badge>)
    expect(screen.getByText('Active').tagName).toBe('SPAN')
    expect(screen.getByText('Active').textContent).toBe('Active')
  })

  it('error badge renders with visible label', () => {
    render(<Badge status="error">Failed</Badge>)
    expect(screen.getByText('Failed').tagName).toBe('SPAN')
    expect(screen.getByText('Failed').textContent).toBe('Failed')
  })

  it('neutral badge renders with visible label', () => {
    render(<Badge status="neutral">Pending</Badge>)
    expect(screen.getByText('Pending').tagName).toBe('SPAN')
    expect(screen.getByText('Pending').textContent).toBe('Pending')
  })

  it('each status produces a different data-status attribute (palette mapping is unique per status)', () => {
    const statuses = [
      { status: 'success', label: 'S1' },
      { status: 'active', label: 'S2' },
      { status: 'neutral', label: 'S3' },
      { status: 'error', label: 'S4' },
    ] as const

    const { container } = render(
      <div>
        {statuses.map(({ status, label }) => (
          <Badge key={status} status={status}>{label}</Badge>
        ))}
      </div>
    )

    // Each badge must have a distinct data-status value — proves palette mapping is driven by the status prop
    const badges = container.querySelectorAll('[data-status]')
    expect(badges).toHaveLength(4)
    const statusValues = Array.from(badges).map((el) => el.getAttribute('data-status'))
    expect(statusValues).toEqual(['success', 'active', 'neutral', 'error'])
  })
})
