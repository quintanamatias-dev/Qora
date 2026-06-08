/**
 * TopBar — Qora Design System layout primitive
 *
 * bg-paper + border-b border-line.
 * Shows current client context (no Qora wordmark — it lives in the sidebar only).
 * Clean and minimal: just context info.
 */

interface TopBarProps {
  clientId: string
}

export function TopBar({ clientId }: TopBarProps) {
  return (
    <header
      role="banner"
      className={[
        'fixed top-0 left-0 right-0',
        'h-14',
        'bg-paper',
        'flex items-center gap-3',
        'px-6',
        'z-50',
        'border-b border-line',
      ].join(' ')}
    >
      {/* Client context */}
      <span
        className="text-sm text-ink-3 font-mono uppercase tracking-[0.10em]"
        aria-label={`Current client: ${clientId}`}
      >
        {clientId}
      </span>
    </header>
  )
}
