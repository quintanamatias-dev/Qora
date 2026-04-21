/**
 * Badge — Sovereign Interface primitive
 *
 * Status indicator using design palette colors.
 * Small, compact, with label-sm uppercase style.
 */

import type { HTMLAttributes, ReactNode } from 'react'

export type BadgeStatus =
  | 'success'
  | 'active'
  | 'neutral'
  | 'error'
  | 'warning'
  | 'new'
  | 'called'
  | 'interested'
  | 'not_interested'
  | 'follow_up'

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  status: BadgeStatus
  children: ReactNode
}

const statusStyles: Record<BadgeStatus, string> = {
  // Design system states
  success: 'bg-primary/20 text-primary',
  active: 'bg-secondary/20 text-secondary',
  neutral: 'bg-surface-bright/60 text-on-surface-variant',
  error: 'bg-error/20 text-error',
  warning: 'bg-warning/20 text-warning',

  // Lead status states (matching LeadStatus from API)
  new: 'bg-primary/20 text-primary',
  called: 'bg-secondary/20 text-secondary',
  interested: 'bg-primary/30 text-primary',
  not_interested: 'bg-surface-bright/60 text-on-surface-variant',
  follow_up: 'bg-warning/20 text-warning',
}

export function Badge({
  status,
  className = '',
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      data-status={status}
      className={[
        'inline-flex items-center',
        'px-2 py-0.5',
        'text-xs font-medium uppercase tracking-wider',
        'rounded-sm',
        statusStyles[status],
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      {children}
    </span>
  )
}
