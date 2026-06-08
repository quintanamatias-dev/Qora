/**
 * Toast — Qora Design System primitive
 *
 * Success/error feedback after CRUD operations.
 * Auto-dismisses after configurable timeout (default 4s).
 * Variant "fixed": positioned fixed bottom-right.
 * Variant "inline": renders in document flow.
 * bg-paper + border border-line + rounded-lg + shadow-lg.
 * Success indicator: teal dot. Error indicator: coral dot.
 */

import { useEffect, useState } from 'react'
import type { HTMLAttributes } from 'react'

export type ToastStatus = 'success' | 'error'
export type ToastVariant = 'fixed' | 'inline'

export interface ToastProps extends HTMLAttributes<HTMLDivElement> {
  /** Message content to display */
  message: string
  /** Status drives color indicator: success (teal) or error (coral) */
  status: ToastStatus
  /** "fixed" renders bottom-right fixed; "inline" renders in flow */
  variant?: ToastVariant
  /** Auto-dismiss timeout in ms (default: 4000, pass 0 to disable) */
  timeout?: number
  /** Called when toast dismisses (auto or manual) */
  onDismiss?: () => void
}

const statusIndicator: Record<ToastStatus, string> = {
  success: 'bg-teal',
  error:   'bg-coral',
}

export function Toast({
  message,
  status,
  variant = 'fixed',
  timeout = 4000,
  onDismiss,
  className = '',
  ...rest
}: ToastProps) {
  const [visible, setVisible] = useState(true)

  useEffect(() => {
    if (timeout === 0) return
    const timer = setTimeout(() => {
      setVisible(false)
      onDismiss?.()
    }, timeout)
    return () => clearTimeout(timer)
  }, [timeout, onDismiss])

  if (!visible) return null

  const handleDismiss = () => {
    setVisible(false)
    onDismiss?.()
  }

  return (
    <div
      role="alert"
      aria-live="polite"
      data-status={status}
      data-variant={variant}
      className={[
        'flex items-center gap-3',
        'px-4 py-3',
        'bg-paper',
        'border border-line',
        'rounded-lg',
        'shadow-lg',
        'text-ink',
        variant === 'fixed'
          ? 'fixed bottom-4 right-4 z-50 min-w-[18rem] max-w-sm'
          : 'w-full',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      {/* Status color indicator dot */}
      <span
        aria-hidden="true"
        className={[
          'w-2 h-2 rounded-full shrink-0',
          statusIndicator[status],
        ].join(' ')}
      />
      <span className="flex-1 text-sm text-ink">{message}</span>
      <button
        aria-label="Dismiss"
        onClick={handleDismiss}
        className="shrink-0 text-ink-3 hover:text-ink transition-colors duration-150 focus:outline-none text-lg leading-none"
      >
        ×
      </button>
    </div>
  )
}
