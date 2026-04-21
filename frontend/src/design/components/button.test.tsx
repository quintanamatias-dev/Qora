/**
 * CAP-3: Button Component Tests
 * TDD Layer: Integration — render + behavioral assertions
 *
 * REQ-3.1: Button supports primary, secondary, tertiary variants
 * - All variants render as <button> elements (not <a> tags or divs)
 * - Primary: renders text color indicator, is not disabled by default
 * - Secondary: renders with border/ghost styling, not disabled by default
 * - Tertiary: no background color indicator, not disabled by default
 * - Disabled state: button becomes non-interactive
 */

import { render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Button } from './button'

describe('Button — primary variant', () => {
  it('renders children text', () => {
    render(<Button variant="primary">Save</Button>)
    expect(screen.getByRole('button')).toHaveTextContent('Save')
  })

  it('has data-variant="primary" attribute', () => {
    render(<Button variant="primary">Save</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('data-variant', 'primary')
  })

  it('is a button element', () => {
    render(<Button variant="primary">Save</Button>)
    expect(screen.getByRole('button').tagName).toBe('BUTTON')
  })
})

describe('Button — secondary variant', () => {
  it('renders children text', () => {
    render(<Button variant="secondary">Cancel</Button>)
    expect(screen.getByRole('button')).toHaveTextContent('Cancel')
  })

  it('has data-variant="secondary" attribute', () => {
    render(<Button variant="secondary">Cancel</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('data-variant', 'secondary')
  })
})

describe('Button — tertiary variant', () => {
  it('renders children text', () => {
    render(<Button variant="tertiary">Learn more</Button>)
    expect(screen.getByRole('button')).toHaveTextContent('Learn more')
  })

  it('has data-variant="tertiary" attribute', () => {
    render(<Button variant="tertiary">Learn more</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('data-variant', 'tertiary')
  })
})

describe('Button — disabled state', () => {
  it('is disabled when disabled prop is true', () => {
    render(<Button variant="primary" disabled>Save</Button>)
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('does not fire onClick when disabled', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<Button variant="primary" disabled onClick={onClick}>Save</Button>)
    await user.click(screen.getByRole('button'))
    expect(onClick).not.toHaveBeenCalled()
  })
})

describe('Button — onClick handler', () => {
  it('calls onClick when clicked', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<Button variant="primary" onClick={onClick}>Save</Button>)
    await user.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})

describe('Button — size prop', () => {
  it('accepts size="sm" without crashing', () => {
    render(<Button variant="primary" size="sm">Small</Button>)
    expect(screen.getByRole('button')).toHaveTextContent('Small')
  })

  it('accepts size="lg" without crashing', () => {
    render(<Button variant="primary" size="lg">Large</Button>)
    expect(screen.getByRole('button')).toHaveTextContent('Large')
  })

  it('has data-size attribute when size is provided', () => {
    render(<Button variant="primary" size="sm">Small</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('data-size', 'sm')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// REQ-3.1: Behavioral variant rendering (spec compliance)
// ──────────────────────────────────────────────────────────────────────────────
describe('Button — all 3 variants are button elements (REQ-3.1)', () => {
  it('primary variant renders as a <button> element with role=button', () => {
    render(<Button variant="primary">Submit</Button>)
    const btn = screen.getByRole('button', { name: 'Submit' })
    expect(btn.tagName).toBe('BUTTON')
    // Verify it is NOT disabled by default (interactive)
    expect(btn).not.toBeDisabled()
  })

  it('secondary variant renders as a <button> element and is interactive by default', () => {
    render(<Button variant="secondary">Cancel</Button>)
    const btn = screen.getByRole('button', { name: 'Cancel' })
    expect(btn.tagName).toBe('BUTTON')
    expect(btn).not.toBeDisabled()
  })

  it('tertiary variant renders as a <button> element and is interactive by default', () => {
    render(<Button variant="tertiary">Learn more</Button>)
    const btn = screen.getByRole('button', { name: 'Learn more' })
    expect(btn.tagName).toBe('BUTTON')
    expect(btn).not.toBeDisabled()
  })

  it('all 3 variants call their onClick when clicked', async () => {
    const user = userEvent.setup()
    const variants = ['primary', 'secondary', 'tertiary'] as const
    for (const variant of variants) {
      const onClick = vi.fn()
      const { unmount } = render(
        <Button variant={variant} onClick={onClick}>{variant}</Button>
      )
      await user.click(screen.getByRole('button', { name: variant }))
      expect(onClick).toHaveBeenCalledTimes(1)
      unmount()
    }
  })
})
