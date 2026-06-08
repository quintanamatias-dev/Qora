/**
 * Select — Qora Design System primitive
 *
 * Same visual style as Input: bg-paper + border-line-2 + rounded-md.
 * Focus: border-teal + teal shadow ring.
 * Label support via optional `label` prop (matches Input pattern).
 * Extends native <select> attributes.
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
          className="text-xs font-medium uppercase tracking-widest text-ink-3"
        >
          {label}
        </label>
      )}
      <select
        id={selectId}
        className={[
          'w-full',
          'bg-paper',
          'text-ink',
          'text-sm',
          'px-3 py-2',
          'rounded-md',
          'border border-line-2',
          'focus:border-teal',
          'focus:shadow-[0_0_0_3px_var(--color-teal-faint)]',
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
