/**
 * TopBar — Sovereign Interface layout primitive
 *
 * Sticky top bar with surface-container background.
 * Displays brand name + client context slot.
 * Uses font-display (Manrope) for title.
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
        'bg-surface-container',
        'flex items-center gap-4',
        'px-6',
        'z-50',
        // Ghost border bottom — outline-variant at 15% opacity per DESIGN.md
        'border-b border-b-outline-variant/15',
      ].join(' ')}
    >
      {/* Brand */}
      <span className="font-display font-bold text-lg text-primary tracking-tight">
        Qora
      </span>

      {/* Separator */}
      <span className="text-outline/40 select-none">·</span>

      {/* Client context */}
      <span className="text-sm text-on-surface-variant font-medium truncate">
        {clientId}
      </span>
    </header>
  )
}
