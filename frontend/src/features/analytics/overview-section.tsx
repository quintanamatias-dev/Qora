/**
 * OverviewSection — Presentational component for analytics overview metrics
 *
 * Shows: total_calls, conversion_rate, outcome distribution breakdown
 * Design: container-presentational pattern, receives data as props.
 * Issue #50: removed engagement_distribution (field dropped from schema).
 */

import type { AnalyticsOverviewResponse } from '@/api/types'

interface OverviewSectionProps {
  data: AnalyticsOverviewResponse
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-surface-container rounded-lg p-4 space-y-1">
      <p className="text-sm text-on-surface-variant">{label}</p>
      <p className="text-2xl font-bold text-on-surface">{value}</p>
    </div>
  )
}

export function OverviewSection({ data }: OverviewSectionProps) {
  const convRate =
    data.conversion_rate !== null
      ? `${(data.conversion_rate * 100).toFixed(1)}%`
      : 'N/A'

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-on-surface">Overview</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Calls" value={data.total_calls} />
        <StatCard label="Conversion Rate" value={convRate} />
        {Object.entries(data.outcome_distribution).map(([key, count]) => (
          <StatCard key={key} label={`Outcome: ${key}`} value={count} />
        ))}
      </div>
    </div>
  )
}
