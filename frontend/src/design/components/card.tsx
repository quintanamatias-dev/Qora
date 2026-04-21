/**
 * Card — Sovereign Interface primitive
 *
 * Background-shift elevation — NO visible borders (1px borders PROHIBITED per DESIGN.md).
 * Uses surface-container-low or surface-container background.
 * Optional `stripe` prop adds 2px emerald (#4edea3) left stripe for active state.
 */

import type { HTMLAttributes, ReactNode } from 'react'

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Add 2px emerald left stripe to indicate active state */
  stripe?: boolean
  children: ReactNode
}

export function Card({
  stripe = false,
  className = '',
  children,
  ...rest
}: CardProps) {
  return (
    <div
      data-variant="default"
      {...(stripe ? { 'data-stripe': 'true' } : {})}
      className={[
        'bg-surface-container-low',
        'rounded',
        'p-4',
        stripe
          ? 'border-l-2 border-l-primary pl-[calc(1rem-2px)]'
          : '',
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
