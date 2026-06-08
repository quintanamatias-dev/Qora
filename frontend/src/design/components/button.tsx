/**
 * Button — Qora Design System primitive
 *
 * Variants:
 *  - primary:   solid teal bg, white text, pill (r-full). Hover: teal-deep.
 *  - secondary: ghost — border-line-2, text-ink-2, pill. Hover: border-line-3 text-ink.
 *  - tertiary:  no background, text-ink-2. Hover: text-ink.
 *
 * Gradients PROHIBITED. Pills are canonical (r-full = 999px).
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'tertiary'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  children: ReactNode
}

const variantStyles: Record<ButtonVariant, string> = {
  primary: [
    'bg-teal',
    'text-white',
    'font-medium',
    'border-none',
    'shadow-sm',
    'hover:bg-teal-deep',
    'hover:-translate-y-px',
    'active:translate-y-0',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ].join(' '),

  secondary: [
    'bg-transparent',
    'border border-line-2',
    'text-ink-2',
    'hover:border-line-3',
    'hover:text-ink',
    'active:opacity-70',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ].join(' '),

  tertiary: [
    'bg-transparent',
    'border-none',
    'text-ink-2',
    'hover:text-ink',
    'active:opacity-70',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ].join(' '),
}

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-sm',
  md: 'px-4 py-2 text-sm',
  lg: 'px-6 py-3 text-base',
}

export function Button({
  variant = 'primary',
  size = 'md',
  className = '',
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      data-variant={variant}
      data-size={size}
      className={[
        'inline-flex items-center justify-center gap-2',
        'rounded-full', // r-full = 999px pill — canonical
        'transition-all duration-150',
        'focus:outline-none',
        variantStyles[variant],
        sizeStyles[size],
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      {children}
    </button>
  )
}
