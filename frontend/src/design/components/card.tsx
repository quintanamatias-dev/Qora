/**
 * Card — Qora Design System primitive
 *
 * bg-paper + border border-line + rounded-lg (20px) + shadow-md + p-7.
 * Left-border accent stripes PROHIBITED (anti-pattern #21 per design system).
 */

import type { HTMLAttributes, ReactNode } from 'react'

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
}

export function Card({
  className = '',
  children,
  ...rest
}: CardProps) {
  return (
    <div
      data-variant="default"
      className={[
        'bg-paper',
        'border border-line',
        'rounded-lg',
        'shadow-md',
        'p-7',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      {children}
    </div>
  )
}
