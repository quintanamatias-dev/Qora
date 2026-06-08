/**
 * PageContainer — Qora Design System layout primitive
 *
 * Wraps page content. Sits inside the outlet area (right of Sidebar, below TopBar).
 * bg-pearl base. Provides correct padding and overflow behavior.
 *
 * sidebarCollapsed: when true, uses ml-16 (64px); when false, uses ml-56 (224px).
 * Transition mirrors the sidebar collapse animation.
 */

import type { ReactNode } from 'react'

interface PageContainerProps {
  children: ReactNode
  className?: string
  sidebarCollapsed?: boolean
}

export function PageContainer({ children, className = '', sidebarCollapsed = false }: PageContainerProps) {
  return (
    <main
      className={[
        sidebarCollapsed ? 'ml-16' : 'ml-56',
        'pt-14', // TopBar height
        'min-h-full',
        'bg-pearl',
        'p-6',
        'transition-[margin-left] duration-200 ease-[cubic-bezier(.4,0,.2,1)]',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {children}
    </main>
  )
}
