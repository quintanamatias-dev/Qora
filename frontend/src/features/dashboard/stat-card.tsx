/**
 * StatCard — Dashboard-specific KPI card
 *
 * Design: features/dashboard (not promoted to design system — YAGNI)
 * Qora Design System: bg-paper + rounded-lg + border border-line + shadow-md.
 * Display value: Fredoka (font-display), large headline numbers.
 * Accent: text-teal for primary, text-coral for error.
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
      className={[
        'bg-paper rounded-lg border border-line shadow-md p-6',
        className,
      ].filter(Boolean).join(' ')}
      data-testid={testId}
      {...accentAttr}
    >
      <p className="font-mono text-xs font-medium uppercase tracking-[0.20em] text-ink-3 mb-3">
        {label}
      </p>

      {loading ? (
        <div
          data-testid="stat-skeleton"
          className="animate-pulse bg-mist rounded h-12 w-28"
        />
      ) : (
        <p
          className={[
            'font-display text-[2.5rem] leading-none font-medium tracking-[-0.025em]',
            accent === 'primary' ? 'text-teal' :
            accent === 'error' ? 'text-coral' :
            accent === 'secondary' ? 'text-ink-2' :
            accent === 'warning' ? 'text-warning' :
            'text-ink',
          ].join(' ')}
        >
          {value}
        </p>
      )}
    </div>
  )
}
