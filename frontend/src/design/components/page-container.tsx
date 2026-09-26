/**
 * PageContainer — wraps route content inside the `.main` shell panel.
 *
 * Renders the single <main role="main"> landmark for the app (the `.main`
 * CSS class from dashboard.css lives on the plain wrapper div in app-layout.tsx,
 * which holds TopBar + PageContainer — see app-layout.tsx for the split).
 */

import type { ReactNode } from 'react'

interface PageContainerProps {
  children: ReactNode
  className?: string
}

export function PageContainer({ children, className = '' }: PageContainerProps) {
  return (
    // Each screen renders its own `.page` wrapper (the live panel sits outside it,
    // full-bleed), so this landmark only fills the remaining height of `.main`.
    <main role="main" className={['main-body', className].filter(Boolean).join(' ')}>
      {children}
    </main>
  )
}
