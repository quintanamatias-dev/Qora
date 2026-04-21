/**
 * Input — Sovereign Interface primitive
 *
 * Background: surface-container-highest
 * Focus: violet (#d0bcff) bottom border with 2px glow
 * No bubbly focus rings (outline: none per DESIGN.md)
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
          className="text-xs font-medium uppercase tracking-widest text-on-surface-variant"
        >
          {label}
        </label>
      )}
      <input
        id={inputId}
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
          'placeholder:text-on-surface-variant/50',
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
