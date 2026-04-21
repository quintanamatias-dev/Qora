/**
 * CAP-3: Input Component Tests
 * TDD Layer: Integration — render + behavioral assertions
 */

import { render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Input } from './input'

describe('Input — rendering', () => {
  it('renders an input element', () => {
    render(<Input />)
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('renders with placeholder text', () => {
    render(<Input placeholder="Search leads..." />)
    expect(screen.getByPlaceholderText('Search leads...')).toBeInTheDocument()
  })

  it('renders with a label when label prop is provided', () => {
    render(<Input label="Email" id="email" />)
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
  })
})

describe('Input — value and change', () => {
  it('accepts and displays a value', () => {
    render(<Input value="test value" onChange={vi.fn()} />)
    expect(screen.getByRole('textbox')).toHaveValue('test value')
  })

  it('calls onChange when user types', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Input onChange={onChange} />)
    await user.type(screen.getByRole('textbox'), 'hello')
    expect(onChange).toHaveBeenCalled()
  })
})

describe('Input — focus state', () => {
  it('receives focus when clicked', async () => {
    const user = userEvent.setup()
    render(<Input data-testid="input-wrapper" />)
    const input = screen.getByRole('textbox')
    await user.click(input)
    expect(input).toHaveFocus()
  })
})

describe('Input — disabled state', () => {
  it('is disabled when disabled prop is passed', () => {
    render(<Input disabled />)
    expect(screen.getByRole('textbox')).toBeDisabled()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// REQ-3.3: Input behavioral specification
// - Focus: input accepts focus (already tested)
// - No ring: the input does NOT have type="button" (isn't a button that auto-rings)
// - Accepts controlled value round-trip
// ──────────────────────────────────────────────────────────────────────────────
describe('REQ-3.3 Input behavioral rendering', () => {
  it('input is a text field (not a button or checkbox) — correct role', () => {
    render(<Input />)
    // getByRole('textbox') succeeds only when type=text|email|search|etc
    const input = screen.getByRole('textbox')
    expect(input.tagName).toBe('INPUT')
  })

  it('controlled input round-trips its value', async () => {
    const { rerender } = render(<Input value="initial" onChange={() => {}} />)
    expect(screen.getByRole('textbox')).toHaveValue('initial')

    rerender(<Input value="updated" onChange={() => {}} />)
    expect(screen.getByRole('textbox')).toHaveValue('updated')
  })

  it('input with label creates an accessible label-input pair', () => {
    render(<Input label="Phone number" id="phone" />)
    const input = screen.getByLabelText('Phone number')
    expect(input).toBeInTheDocument()
    expect(input.tagName).toBe('INPUT')
  })
})
