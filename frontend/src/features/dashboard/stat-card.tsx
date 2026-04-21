/**
 * StatCard — Dashboard-specific KPI card
 *
 * Design: features/dashboard (not promoted to design system — YAGNI)
 * Sovereign Interface: no borders, background-shift for depth, Manrope display value
 *
 * Accent → data-accent attribute for CSS targeting + semantic styling
 */

type StatAccent = 'primary' | 'error' | 'secondary' | 'warning'

interface StatCardProps {
  label: string
  value: string | number
  accent?: StatAccent
  loading?: boolean
  className?: string
  'data-testid'?: string
}

export function StatCard({ label, value, accent, loading = false, className, 'data-testid': testId }: StatCardProps) {
  const accentAttr = accent ? { 'data-accent': accent } : {}

  return (
    <div
      className={['bg-surface-container-low p-4', className].filter(Boolean).join(' ')}
      data-testid={testId}
      {...accentAttr}
    >
      <p className="font-body text-xs font-medium uppercase tracking-wider text-on-surface-variant">
        {label}
      </p>

      {loading ? (
        <div
          data-testid="stat-skeleton"
          className="mt-2 animate-pulse bg-surface-container rounded h-8 w-24"
        />
      ) : (
        <p
          className={[
            'mt-2 font-display text-3xl font-bold',
            accent === 'primary' ? 'text-primary' :
            accent === 'error' ? 'text-error' :
            accent === 'secondary' ? 'text-secondary' :
            accent === 'warning' ? 'text-warning' :
            'text-on-surface',
          ].join(' ')}
        >
          {value}
        </p>
      )}
    </div>
  )
}
