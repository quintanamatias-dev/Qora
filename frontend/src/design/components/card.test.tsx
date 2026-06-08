/**
 * CAP-3: Card Component Tests
 * TDD Layer: Integration — render + behavioral assertions
 *
 * stripe prop removed (anti-pattern #21 per Qora Design System).
 */

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { Card } from './card'

describe('Card — default rendering', () => {
  it('renders children content', () => {
    render(<Card>Card content</Card>)
    expect(screen.getByText('Card content')).toBeInTheDocument()
  })

  it('has data-variant="default" attribute by default', () => {
    render(<Card data-testid="card">Card content</Card>)
    expect(screen.getByTestId('card')).toHaveAttribute('data-variant', 'default')
  })

  it('renders as a div element', () => {
    render(<Card data-testid="card">Content</Card>)
    expect(screen.getByTestId('card').tagName).toBe('DIV')
  })
})

describe('Card — className passthrough', () => {
  it('applies additional className prop', () => {
    render(<Card data-testid="card" className="custom-class">Content</Card>)
    expect(screen.getByTestId('card')).toHaveClass('custom-class')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// REQ-3.2: Card behavioral specification
// - Default card: renders as a div containing the children
// - No stripe prop (removed — anti-pattern #21 per design system)
// ──────────────────────────────────────────────────────────────────────────────
describe('REQ-3.2 Card behavioral rendering', () => {
  it('default card renders as a div with children accessible as text', () => {
    render(<Card data-testid="card">Invoice #1234</Card>)
    const card = screen.getByTestId('card')
    // It's a structural div container (not a button or link)
    expect(card.tagName).toBe('DIV')
    // Content is accessible to the user
    expect(card).toHaveTextContent('Invoice #1234')
  })

  it('card does NOT have data-stripe attribute (stripe prop removed)', () => {
    render(<Card data-testid="card">Content</Card>)
    expect(screen.getByTestId('card')).not.toHaveAttribute('data-stripe')
  })
})
