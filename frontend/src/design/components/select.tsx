/**
 * Select — Sovereign Interface primitive
 *
 * Same visual style as Input: bg-surface-container-highest, violet focus glow.
 * Label support via optional `label` prop (matches Input pattern).
 * Extends native <select> attributes.
 * No borders except bottom border focus indicator.
 */

import type { SelectHTMLAttributes } from 'react'

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  /** Optional visible label */
  label?: string
}

export function Select({ label, id, className = '', children, ...rest }: SelectProps) {
  const selectId =
    id ?? (label ? `select-${label.toLowerCase().replace(/\s+/g, '-')}` : undefined)

  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label
          htmlFor={selectId}
          className="text-xs font-medium uppercase tracking-widest text-on-surface-variant"
        >
          {label}
        </label>
      )}
      <select
        id={selectId}
        className={[
          'w-full',
          'bg-surface-container-highest',
          'text-on-surface',
          'text-sm',
          'px-3 py-2',
          'rounded-sm',
          // Bottom border focus: violet with glow
          'border-b border-b-outline/30',
          'focus:border-b-secondary',
          'focus:shadow-[0_2px_0_0_#d0bcff]',
          // No bubbly focus ring
          'outline-none',
          'transition-all duration-150',
          'disabled:opacity-40 disabled:cursor-not-allowed',
          'cursor-pointer',
          className,
        ]
          .filter(Boolean)
          .join(' ')}
        {...rest}
      >
        {children}
      </select>
    </div>
  )
}
