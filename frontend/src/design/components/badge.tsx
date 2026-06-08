/**
 * Badge — Qora Design System primitive
 *
 * Pill shape (r-full), JetBrains Mono, 11px uppercase, tracking +0.20em.
 * Status variants map to Qora token colors.
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
  // Semantic states
  success:  'bg-teal-faint text-teal border border-teal-line',
  active:   'bg-teal-faint text-teal border border-teal-line',
  neutral:  'bg-mist text-ink-3 border border-line',
  error:    'bg-coral-faint text-coral border border-coral-line',
  warning:  'bg-warning/10 text-warning border border-warning/20',

  // Lead status states (matching LeadStatus from API)
  new:          'bg-teal-faint text-teal border border-teal-line',
  called:       'bg-mist text-ink-2 border border-line',
  interested:   'bg-teal-faint text-teal border border-teal-line',
  not_interested: 'bg-mist text-ink-3 border border-line',
  follow_up:    'bg-warning/10 text-warning border border-warning/20',
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
        'px-2.5 py-1',
        'font-mono text-[11px] font-medium uppercase tracking-[0.20em]',
        'rounded-full',
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
