/**
 * Checkbox — Sovereign Interface primitive
 *
 * Custom styled checkbox with accent-primary for checked state.
 * Label rendered inline to the right.
 * Uses data-checked attribute for test targeting.
 * Extends native <input type="checkbox"> attributes.
 */

import type { InputHTMLAttributes } from 'react'

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  /** Label rendered inline to the right of the checkbox */
  label?: string
}

export function Checkbox({
  label,
  id,
  checked,
  className = '',
  ...rest
}: CheckboxProps) {
  const checkboxId =
    id ?? (label ? `checkbox-${label.toLowerCase().replace(/\s+/g, '-')}` : undefined)

  return (
    <div className="inline-flex items-center gap-2">
      <input
        type="checkbox"
        id={checkboxId}
        checked={checked}
        data-checked={checked ? 'true' : 'false'}
        className={[
          'w-4 h-4',
          'rounded-sm',
          'accent-primary',
          'cursor-pointer',
          'disabled:opacity-40 disabled:cursor-not-allowed',
          className,
        ]
          .filter(Boolean)
          .join(' ')}
        {...rest}
      />
      {label && (
        <label
          htmlFor={checkboxId}
          className="text-sm text-on-surface cursor-pointer select-none"
        >
          {label}
        </label>
      )}
    </div>
  )
}
