/**
 * Toast — Sovereign Interface primitive
 *
 * Success/error feedback after CRUD operations.
 * Auto-dismisses after configurable timeout (default 4s).
 * Variant "fixed": positioned fixed bottom-right.
 * Variant "inline": renders in document flow.
 * Uses status colors from design tokens.
 * No borders — background-shift elevation only.
 */

import { useEffect, useState } from 'react'
import type { HTMLAttributes } from 'react'

export type ToastStatus = 'success' | 'error'
export type ToastVariant = 'fixed' | 'inline'

export interface ToastProps extends HTMLAttributes<HTMLDivElement> {
  /** Message content to display */
  message: string
  /** Status drives color: success (#4edea3) or error (#f87171) */
  status: ToastStatus
  /** "fixed" renders bottom-right fixed; "inline" renders in flow */
  variant?: ToastVariant
  /** Auto-dismiss timeout in ms (default: 4000, pass 0 to disable) */
  timeout?: number
  /** Called when toast dismisses (auto or manual) */
  onDismiss?: () => void
}

const statusStyles: Record<ToastStatus, string> = {
  success: 'bg-success/15 text-on-surface',
  error: 'bg-error/15 text-on-surface',
}

const statusIndicator: Record<ToastStatus, string> = {
  success: 'bg-success',
  error: 'bg-error',
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
        'rounded',
        'shadow-lg',
        statusStyles[status],
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
      <span className="flex-1 text-sm">{message}</span>
      <button
        aria-label="Dismiss"
        onClick={handleDismiss}
        className="shrink-0 text-on-surface-variant hover:text-on-surface transition-colors duration-150 focus:outline-none text-lg leading-none"
      >
        ×
      </button>
    </div>
  )
}
