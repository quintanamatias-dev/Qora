/**
 * Textarea Component Tests
 * TDD Layer: Integration — render + behavioral assertions
 */

import { render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Textarea } from './textarea'

describe('Textarea — rendering', () => {
  it('renders a textarea element', () => {
    render(<Textarea />)
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('renders with placeholder text', () => {
    render(<Textarea placeholder="Enter system prompt..." />)
    expect(screen.getByPlaceholderText('Enter system prompt...')).toBeInTheDocument()
  })

  it('renders with a label when label prop is provided', () => {
    render(<Textarea label="System Prompt" id="system-prompt" />)
    expect(screen.getByLabelText('System Prompt')).toBeInTheDocument()
  })

  it('label has htmlFor matching the textarea id', () => {
    render(<Textarea label="System Prompt" id="system-prompt" />)
    const textarea = screen.getByRole('textbox')
    expect(textarea).toHaveAttribute('id', 'system-prompt')
    expect(screen.getByLabelText('System Prompt')).toBe(textarea)
  })
})

describe('Textarea — rows', () => {
  it('renders with default minRows=3', () => {
    render(<Textarea />)
    expect(screen.getByRole('textbox')).toHaveAttribute('rows', '3')
  })

  it('renders with custom minRows', () => {
    render(<Textarea minRows={6} />)
    expect(screen.getByRole('textbox')).toHaveAttribute('rows', '6')
  })
})

describe('Textarea — value and change', () => {
  it('accepts and displays a value', () => {
    render(<Textarea value="Hello system" onChange={vi.fn()} />)
    expect(screen.getByRole('textbox')).toHaveValue('Hello system')
  })

  it('calls onChange when user types', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Textarea onChange={onChange} />)
    await user.type(screen.getByRole('textbox'), 'test')
    expect(onChange).toHaveBeenCalled()
  })
})

describe('Textarea — disabled state', () => {
  it('is disabled when disabled prop is passed', () => {
    render(<Textarea disabled />)
    expect(screen.getByRole('textbox')).toBeDisabled()
  })
})

describe('Textarea — className passthrough', () => {
  it('applies additional className', () => {
    render(<Textarea className="custom-textarea" />)
    expect(screen.getByRole('textbox')).toHaveClass('custom-textarea')
  })
})

describe('Textarea — focus state', () => {
  it('receives focus when clicked', async () => {
    const user = userEvent.setup()
    render(<Textarea />)
    const textarea = screen.getByRole('textbox')
    await user.click(textarea)
    expect(textarea).toHaveFocus()
  })
})
