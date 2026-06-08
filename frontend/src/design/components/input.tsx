/**
 * Input — Qora Design System primitive
 *
 * bg-paper + border border-line-2 + rounded-md (12px).
 * Focus: border-teal + shadow-[0_0_0_3px_var(--color-teal-faint)].
 * No violet focus glow.
 */

import type { InputHTMLAttributes } from 'react'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Optional visible label */
  label?: string
}

export function Input({ label, id, className = '', ...rest }: InputProps) {
  const inputId = id ?? (label ? `input-${label.toLowerCase().replace(/\s+/g, '-')}` : undefined)

  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label
          htmlFor={inputId}
          className="text-xs font-medium uppercase tracking-widest text-ink-3"
        >
          {label}
        </label>
      )}
      <input
        id={inputId}
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
          'placeholder:text-ink-4',
          'disabled:opacity-40 disabled:cursor-not-allowed',
          className,
        ]
          .filter(Boolean)
          .join(' ')}
        {...rest}
      />
    </div>
  )
}
