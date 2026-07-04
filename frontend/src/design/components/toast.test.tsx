/**
 * Toast Component Tests
 * TDD Layer: Integration — render + behavioral assertions
 */

import { render, screen, act } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { Toast } from './toast'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  // Flush any pending timers inside act so React can process resulting state
  // updates (e.g. setVisible(false) from a timeout) before the test tears down.
  // Required with React 19 + vi.useFakeTimers() to avoid act(...) warnings.
  act(() => {
    vi.runOnlyPendingTimers()
  })
  vi.useRealTimers()
})

describe('Toast — rendering', () => {
  it('renders the message text', () => {
    render(<Toast message="Operation successful" status="success" timeout={0} />)
    expect(screen.getByText('Operation successful')).toBeInTheDocument()
  })

  it('renders a success toast with data-status="success"', () => {
    render(<Toast message="Saved!" status="success" timeout={0} />)
    expect(screen.getByRole('alert')).toHaveAttribute('data-status', 'success')
  })

  it('renders an error toast with data-status="error"', () => {
    render(<Toast message="Something went wrong" status="error" timeout={0} />)
    expect(screen.getByRole('alert')).toHaveAttribute('data-status', 'error')
  })

  it('has role="alert" for accessibility', () => {
    render(<Toast message="Hello" status="success" timeout={0} />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})

describe('Toast — variant', () => {
  it('has data-variant="fixed" by default', () => {
    render(<Toast message="Hi" status="success" timeout={0} />)
    expect(screen.getByRole('alert')).toHaveAttribute('data-variant', 'fixed')
  })

  it('has data-variant="inline" when variant="inline"', () => {
    render(<Toast message="Hi" status="success" variant="inline" timeout={0} />)
    expect(screen.getByRole('alert')).toHaveAttribute('data-variant', 'inline')
  })
})

describe('Toast — dismiss button', () => {
  it('renders a dismiss button', () => {
    render(<Toast message="Hi" status="success" timeout={0} />)
    expect(screen.getByRole('button', { name: 'Dismiss' })).toBeInTheDocument()
  })

  it('hides the toast when dismiss button is clicked', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(<Toast message="Hi" status="success" timeout={0} />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    vi.useFakeTimers()
  })

  it('calls onDismiss when dismiss button is clicked', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    const onDismiss = vi.fn()
    render(<Toast message="Hi" status="success" timeout={0} onDismiss={onDismiss} />)
    await user.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(onDismiss).toHaveBeenCalled()
    vi.useFakeTimers()
  })
})

describe('Toast — auto-dismiss', () => {
  it('is visible before timeout expires', () => {
    render(<Toast message="Hi" status="success" timeout={4000} />)
    // Advance slightly but not enough to dismiss
    act(() => {
      vi.advanceTimersByTime(100)
    })
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('auto-dismisses after timeout', () => {
    render(<Toast message="Hi" status="success" timeout={4000} />)
    act(() => {
      vi.advanceTimersByTime(4001)
    })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('calls onDismiss after timeout', () => {
    const onDismiss = vi.fn()
    render(<Toast message="Hi" status="success" timeout={2000} onDismiss={onDismiss} />)
    act(() => {
      vi.advanceTimersByTime(2001)
    })
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('does not auto-dismiss when timeout=0', () => {
    render(<Toast message="Hi" status="success" timeout={0} />)
    act(() => {
      vi.advanceTimersByTime(10000)
    })
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})

describe('Toast — className passthrough', () => {
  it('applies additional className', () => {
    render(<Toast message="Hi" status="success" className="custom-toast" timeout={0} />)
    expect(screen.getByRole('alert')).toHaveClass('custom-toast')
  })
})
