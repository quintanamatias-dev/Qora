/**
 * DashboardPage — Container component for client call metrics
 *
 * Spec: sdd/qora-dashboard-metrics/spec
 * Design: container-presentational pattern
 *   - Reads clientId from URL params
 *   - Manages period state (default: "today" per spec)
 *   - Computes UTC date range from period
 *   - Calls useMetrics and routes to loading/error/empty/data UI branches
 */

import { useState, useMemo } from 'react'
import { useParams } from 'react-router'
import { useMetrics } from '@/api/hooks'
import { PeriodSelector, type Period } from './period-selector'
import { MetricsGrid } from './metrics-grid'

// ──────────────────────────────────────────────────────────────────────────────
// Pure helper — period → UTC date range
// ──────────────────────────────────────────────────────────────────────────────

interface DateRange {
  date_from?: string
  date_to?: string
}

export function periodToDateRange(period: Period): DateRange {
  const now = new Date()

  if (period === 'today') {
    const startOfToday = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()))
    const endOfToday = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 23, 59, 59, 999))
    return {
      date_from: startOfToday.toISOString(),
      date_to: endOfToday.toISOString(),
    }
  }

  if (period === '7d') {
    const from = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
    return { date_from: from.toISOString(), date_to: now.toISOString() }
  }

  if (period === '30d') {
    const from = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
    return { date_from: from.toISOString(), date_to: now.toISOString() }
  }

  // 'all' — omit date params
  return {}
}

// ──────────────────────────────────────────────────────────────────────────────
// DashboardPage
// ──────────────────────────────────────────────────────────────────────────────

export function DashboardPage() {
  const { clientId } = useParams<{ clientId: string }>()
  const [period, setPeriod] = useState<Period>('today')

  // useMemo prevents new Date() from generating a different queryKey on every render,
  // which would cause an infinite refetch loop in TanStack Query.
  // Re-computes only when `period` changes (user clicks a different tab).
  const dateRange = useMemo(() => periodToDateRange(period), [period])
  const { data, isLoading, isError, refetch } = useMetrics(clientId ?? '', dateRange)

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold text-on-surface">
            Dashboard
          </h1>
          {clientId && (
            <p className="text-sm text-on-surface-variant mt-1">
              Client: <span className="text-primary font-medium">{clientId}</span>
            </p>
          )}
        </div>

        {/* Period selector — always interactive (spec: remains interactive during loading) */}
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      {/* Metrics area — routes to loading / error / empty / data */}
      <MetricsArea
        loading={isLoading}
        error={isError}
        data={data ?? null}
        onRetry={refetch}
      />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// MetricsArea — UI branch routing
// ──────────────────────────────────────────────────────────────────────────────

import type { CallMetricsResponse } from '@/api/types'

interface MetricsAreaProps {
  loading: boolean
  error: boolean
  data: CallMetricsResponse | null
  onRetry?: () => void
}

function MetricsArea({ loading, error, data, onRetry }: MetricsAreaProps) {
  // Loading — show skeleton grid (PeriodSelector remains interactive above)
  if (loading) {
    const emptyData: CallMetricsResponse = {
      total_calls: 0, completed_calls: 0, abandoned_calls: 0,
      total_duration_seconds: 0, average_duration_seconds: 0,
      total_billable_minutes: 0, period: { date_from: null, date_to: null },
    }
    return <MetricsGrid data={emptyData} loading />
  }

  // Error — human-readable, no raw API leakage, retry affordance
  if (error) {
    return (
      <div
        role="alert"
        className="bg-surface-container-low p-8 text-center space-y-4"
      >
        <p className="text-on-surface font-medium">
          Unable to load metrics. Please try again.
        </p>
        <p className="text-on-surface-variant text-sm">
          If the problem persists, contact support.
        </p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 px-4 py-2 text-sm font-medium text-primary border border-primary rounded-sm hover:bg-primary/10 transition-colors"
          >
            Retry
          </button>
        )}
      </div>
    )
  }

  // Empty state — total_calls === 0 (spec: no zero-value cards)
  if (data && data.total_calls === 0) {
    return (
      <div
        data-testid="empty-state"
        className="bg-surface-container-low p-8 text-center"
      >
        <p className="text-on-surface font-medium">
          No calls for this period
        </p>
        <p className="text-on-surface-variant text-sm mt-2">
          Try selecting a different time range to see metrics.
        </p>
      </div>
    )
  }

  // Data — render full metrics grid
  if (data) {
    return <MetricsGrid data={data} />
  }

  return null
}
