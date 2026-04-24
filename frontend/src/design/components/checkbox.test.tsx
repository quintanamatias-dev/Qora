/**
 * Checkbox Component Tests
 * TDD Layer: Integration — render + behavioral assertions
 */

import { render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Checkbox } from './checkbox'

describe('Checkbox — rendering', () => {
  it('renders a checkbox input', () => {
    render(<Checkbox />)
    expect(screen.getByRole('checkbox')).toBeInTheDocument()
  })

  it('renders with a label when label prop is provided', () => {
    render(<Checkbox label="Enable feature" />)
    expect(screen.getByLabelText('Enable feature')).toBeInTheDocument()
  })

  it('label is inline next to the checkbox', () => {
    render(<Checkbox label="Web search" />)
    expect(screen.getByText('Web search')).toBeInTheDocument()
    expect(screen.getByRole('checkbox')).toBeInTheDocument()
  })
})

describe('Checkbox — checked state', () => {
  it('has data-checked="true" when checked', () => {
    render(<Checkbox checked onChange={vi.fn()} />)
    expect(screen.getByRole('checkbox')).toHaveAttribute('data-checked', 'true')
  })

  it('has data-checked="false" when unchecked', () => {
    render(<Checkbox checked={false} onChange={vi.fn()} />)
    expect(screen.getByRole('checkbox')).toHaveAttribute('data-checked', 'false')
  })

  it('is checked when checked prop is true', () => {
    render(<Checkbox checked onChange={vi.fn()} />)
    expect(screen.getByRole('checkbox')).toBeChecked()
  })

  it('is unchecked when checked prop is false', () => {
    render(<Checkbox checked={false} onChange={vi.fn()} />)
    expect(screen.getByRole('checkbox')).not.toBeChecked()
  })
})

describe('Checkbox — onChange handler', () => {
  it('calls onChange when clicked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Checkbox onChange={onChange} />)
    await user.click(screen.getByRole('checkbox'))
    expect(onChange).toHaveBeenCalled()
  })
})

describe('Checkbox — disabled state', () => {
  it('is disabled when disabled prop is passed', () => {
    render(<Checkbox disabled />)
    expect(screen.getByRole('checkbox')).toBeDisabled()
  })

  it('does not fire onChange when disabled', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Checkbox disabled onChange={onChange} />)
    await user.click(screen.getByRole('checkbox'))
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('Checkbox — className passthrough', () => {
  it('applies additional className to the input', () => {
    render(<Checkbox className="custom-checkbox" />)
    expect(screen.getByRole('checkbox')).toHaveClass('custom-checkbox')
  })
})

describe('Checkbox — id and label association', () => {
  it('generates id from label when no id is provided', () => {
    render(<Checkbox label="Web search" />)
    const checkbox = screen.getByRole('checkbox')
    expect(checkbox).toHaveAttribute('id', 'checkbox-web-search')
  })

  it('uses provided id', () => {
    render(<Checkbox id="custom-id" label="Tool" />)
    expect(screen.getByRole('checkbox')).toHaveAttribute('id', 'custom-id')
  })
})
