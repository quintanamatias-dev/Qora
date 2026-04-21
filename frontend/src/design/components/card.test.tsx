/**
 * CAP-3: Card Component Tests
 * TDD Layer: Integration — render + behavioral assertions
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

describe('Card — stripe prop', () => {
  it('has data-stripe="true" when stripe prop is set', () => {
    render(<Card data-testid="card" stripe>Striped card</Card>)
    expect(screen.getByTestId('card')).toHaveAttribute('data-stripe', 'true')
  })

  it('does NOT have data-stripe attribute by default', () => {
    render(<Card data-testid="card">No stripe</Card>)
    expect(screen.getByTestId('card')).not.toHaveAttribute('data-stripe')
  })

  it('still renders children when stripe is active', () => {
    render(<Card stripe>Striped content</Card>)
    expect(screen.getByText('Striped content')).toBeInTheDocument()
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
// - Stripe card: renders children AND exposes stripe state via data-stripe
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

  it('striped card renders children AND exposes data-stripe=true for styling hook', () => {
    render(<Card data-testid="card" stripe>Active lead</Card>)
    const card = screen.getByTestId('card')
    // Children visible
    expect(card).toHaveTextContent('Active lead')
    // Stripe state exposed — this is the production code's contract for the visual stripe
    expect(card).toHaveAttribute('data-stripe', 'true')
  })

  it('default card does NOT expose data-stripe (no stripe when not requested)', () => {
    render(<Card data-testid="card">No stripe here</Card>)
    expect(screen.getByTestId('card')).not.toHaveAttribute('data-stripe')
  })
})
