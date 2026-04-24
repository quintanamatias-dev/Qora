/**
 * Select Component Tests
 * TDD Layer: Integration — render + behavioral assertions
 */

import { render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Select } from './select'

describe('Select — rendering', () => {
  it('renders a select element', () => {
    render(
      <Select>
        <option value="a">Option A</option>
      </Select>
    )
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('renders with options', () => {
    render(
      <Select>
        <option value="a">Option A</option>
        <option value="b">Option B</option>
      </Select>
    )
    expect(screen.getByText('Option A')).toBeInTheDocument()
    expect(screen.getByText('Option B')).toBeInTheDocument()
  })

  it('renders with a label when label prop is provided', () => {
    render(
      <Select label="Client">
        <option value="c1">Client 1</option>
      </Select>
    )
    expect(screen.getByLabelText('Client')).toBeInTheDocument()
  })

  it('label has htmlFor matching the select id', () => {
    render(
      <Select label="Client" id="client-select">
        <option value="c1">Client 1</option>
      </Select>
    )
    const select = screen.getByRole('combobox')
    expect(select).toHaveAttribute('id', 'client-select')
    expect(screen.getByLabelText('Client')).toBe(select)
  })
})

describe('Select — value and change', () => {
  it('accepts a controlled value', () => {
    render(
      <Select value="b" onChange={vi.fn()}>
        <option value="a">Option A</option>
        <option value="b">Option B</option>
      </Select>
    )
    expect(screen.getByRole('combobox')).toHaveValue('b')
  })

  it('calls onChange when user selects an option', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <Select onChange={onChange}>
        <option value="a">Option A</option>
        <option value="b">Option B</option>
      </Select>
    )
    await user.selectOptions(screen.getByRole('combobox'), 'b')
    expect(onChange).toHaveBeenCalled()
  })
})

describe('Select — disabled state', () => {
  it('is disabled when disabled prop is passed', () => {
    render(
      <Select disabled>
        <option value="a">Option A</option>
      </Select>
    )
    expect(screen.getByRole('combobox')).toBeDisabled()
  })
})

describe('Select — className passthrough', () => {
  it('applies additional className', () => {
    render(
      <Select className="custom-select">
        <option value="a">A</option>
      </Select>
    )
    expect(screen.getByRole('combobox')).toHaveClass('custom-select')
  })
})

describe('Select — data-testid support', () => {
  it('forwards data-testid attribute', () => {
    render(
      <Select data-testid="client-selector">
        <option value="a">A</option>
      </Select>
    )
    expect(screen.getByTestId('client-selector')).toBeInTheDocument()
  })
})
