/**
 * PageContainer — Sovereign Interface layout primitive
 *
 * Wraps page content. Sits inside the outlet area (right of Sidebar, below TopBar).
 * Provides correct padding and overflow behavior.
 */

import type { ReactNode } from 'react'

interface PageContainerProps {
  children: ReactNode
  className?: string
}

export function PageContainer({ children, className = '' }: PageContainerProps) {
  return (
    <main
      className={[
        'ml-56', // Sidebar width
        'pt-14', // TopBar height
        'min-h-full',
        'bg-background',
        'p-6',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {children}
    </main>
  )
}
