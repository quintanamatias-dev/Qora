/**
 * Textarea — Qora Design System primitive
 *
 * Same visual style as Input: bg-paper + border-line-2 + rounded-md.
 * Focus: border-teal + teal shadow ring.
 * Label support via optional `label` prop (matches Input pattern).
 * min-height via minRows prop (default: 3 rows), resize: vertical.
 * Extends native <textarea> attributes.
 */

import type { TextareaHTMLAttributes } from 'react'

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Optional visible label */
  label?: string
  /** Minimum visible rows (default: 3) */
  minRows?: number
}

export function Textarea({ label, id, minRows = 3, className = '', style, ...rest }: TextareaProps) {
  const textareaId =
    id ?? (label ? `textarea-${label.toLowerCase().replace(/\s+/g, '-')}` : undefined)

  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label
          htmlFor={textareaId}
          className="text-xs font-medium uppercase tracking-widest text-ink-3"
        >
          {label}
        </label>
      )}
      <textarea
        id={textareaId}
        rows={minRows}
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
          'resize-y',
          className,
        ]
          .filter(Boolean)
          .join(' ')}
        style={{
          minHeight: `${minRows * 1.5}rem`,
          ...style,
        }}
        {...rest}
      />
    </div>
  )
}
