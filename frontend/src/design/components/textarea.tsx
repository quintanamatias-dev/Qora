/**
 * Textarea — Sovereign Interface primitive
 *
 * Same visual style as Input: bg-surface-container-highest, violet focus glow.
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
          className="text-xs font-medium uppercase tracking-widest text-on-surface-variant"
        >
          {label}
        </label>
      )}
      <textarea
        id={textareaId}
        rows={minRows}
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
