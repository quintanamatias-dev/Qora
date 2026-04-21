/**
 * MetricsGrid — Composes 6 StatCards + StatusBreakdown from CallMetricsResponse
 *
 * Spec: 4-column primary grid (Total/Completed/Abandoned/Avg Duration)
 *       2-column secondary grid (Total Duration / Billable Minutes)
 *       StatusBreakdown bar below
 * Design: 16px gap, no borders, responsive columns
 */

import type { CallMetricsResponse } from '@/api/types'
import { StatCard } from './stat-card'
import { StatusBreakdown } from './status-breakdown'
import { formatDuration } from '@/lib/format-duration'

interface MetricsGridProps {
  data: CallMetricsResponse
  loading?: boolean
}

export function MetricsGrid({ data, loading = false }: MetricsGridProps) {
  return (
    <div className="space-y-4">
      {/* Primary 4-column grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Calls"
          value={String(data.total_calls)}
          loading={loading}
        />
        <StatCard
          label="Completed"
          value={String(data.completed_calls)}
          accent="primary"
          loading={loading}
        />
        <StatCard
          label="Abandoned"
          value={String(data.abandoned_calls)}
          accent="error"
          loading={loading}
        />
        <StatCard
          label="Avg Duration"
          value={formatDuration(data.average_duration_seconds)}
          loading={loading}
        />
      </div>

      {/* Secondary 2-column grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <StatCard
          label="Total Duration"
          value={formatDuration(data.total_duration_seconds)}
          loading={loading}
        />
        <StatCard
          label="Billable Minutes"
          value={`${data.total_billable_minutes} min`}
          accent="secondary"
          loading={loading}
        />
      </div>

      {/* Status breakdown bar */}
      <StatusBreakdown
        completed={data.completed_calls}
        abandoned={data.abandoned_calls}
        total={data.total_calls}
      />
    </div>
  )
}
