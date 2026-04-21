/**
 * Button — Sovereign Interface primitive
 *
 * Variants:
 *  - primary:   135° gradient from #4edea3 → #10b981, text #003824, sharp 4px corners
 *  - secondary: ghost — outline at 20% opacity, secondary (#d0bcff) text
 *  - tertiary:  no background, on-surface text, underline on hover
 *
 * Pill shapes PROHIBITED per DESIGN.md.
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
    'bg-gradient-to-br from-primary to-primary-container',
    'text-on-primary',
    'font-semibold',
    'border-none',
    'shadow-sm',
    'hover:brightness-110',
    'active:brightness-95',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ].join(' '),

  secondary: [
    'bg-transparent',
    'border border-outline/20',
    'text-secondary',
    'hover:border-outline/40',
    'hover:bg-surface-container-highest/30',
    'active:bg-surface-container-highest/50',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ].join(' '),

  tertiary: [
    'bg-transparent',
    'border-none',
    'text-on-surface',
    'hover:underline',
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
        'rounded', // DEFAULT = 0.25rem = 4px
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
