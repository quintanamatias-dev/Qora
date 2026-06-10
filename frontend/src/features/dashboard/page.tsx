/**
 * DashboardPage — Container component for client call metrics
 *
 * Spec: sdd/qora-dashboard-metrics/spec
 * Design: container-presentational pattern
 *   - Reads clientId from URL params
 *   - Manages period state (default: "all" — show all-time by default)
 *   - Computes UTC date range from period
 *   - Calls useMetrics and routes to loading/error/empty/data UI branches
 *
 * Layout: two-column
 *   Left (~60%): metrics + period selector + status breakdown
 *   Right (~40%): active integrations card + agent status
 */

import { useState, useMemo } from 'react'
import { useParams } from 'react-router'
import { useMetrics, useAgents } from '@/api/hooks'
import { LiveIndicator } from '@/design/components'
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
  const activeClientId = clientId ?? ''
  const [period, setPeriod] = useState<Period>('all')

  // useMemo prevents new Date() from generating a different queryKey on every render,
  // which would cause an infinite refetch loop in TanStack Query.
  // Re-computes only when `period` changes (user clicks a different tab).
  const dateRange = useMemo(() => periodToDateRange(period), [period])
  const { data, isLoading, isError, refetch } = useMetrics(activeClientId, dateRange)

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-medium text-ink">
            Dashboard
          </h1>
          {clientId && (
            <p className="text-xs text-ink-3 font-mono uppercase tracking-[0.10em] mt-0.5">
              {clientId}
            </p>
          )}
        </div>
        {/* Period selector — always interactive (spec: remains interactive during loading) */}
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      {/* Two-column layout */}
      <div className="flex gap-8 items-start">
        {/* Left column — metrics (~60%) */}
        <div className="flex-[3] min-w-0 space-y-6">
          <MetricsArea
            loading={isLoading}
            error={isError}
            data={data ?? null}
            onRetry={refetch}
          />
        </div>

        {/* Right column — integrations + agent status (~40%) */}
        <div className="flex-[2] min-w-0 space-y-4">
          <ActiveIntegrationsCard />
          <AgentStatusCard clientId={activeClientId} />
        </div>
      </div>
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
        className="bg-paper border border-line rounded-lg p-8 text-center space-y-4"
      >
        <p className="text-ink font-medium">
          Unable to load metrics. Please try again.
        </p>
        <p className="text-ink-2 text-sm">
          If the problem persists, contact support.
        </p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 px-4 py-2 text-sm font-medium text-teal border border-teal-line rounded-full hover:bg-teal-faint transition-colors"
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
        className="bg-paper border border-line rounded-lg p-8 text-center"
      >
        <p className="text-ink font-medium">
          No calls for this period
        </p>
        <p className="text-ink-2 text-sm mt-2">
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

// ──────────────────────────────────────────────────────────────────────────────
// ActiveIntegrationsCard — right column top panel
// ──────────────────────────────────────────────────────────────────────────────

function ActiveIntegrationsCard() {
  return (
    <div className="bg-paper border border-line rounded-lg shadow-md p-6">
      <p className="font-mono text-xs font-medium uppercase tracking-[0.20em] text-ink-3 mb-4">
        Active Integrations
      </p>
      {/* Airtable integration entry — connected indicator */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-md overflow-hidden flex-shrink-0">
          <img
            src="/images/integrations/airtable-icon.webp"
            alt="Airtable"
            width={32}
            height={32}
            className="w-full h-full object-cover"
          />
        </div>
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-ink">Airtable</span>
        </div>
        <span className="inline-flex items-center gap-1 text-[10px] font-mono font-semibold uppercase tracking-[0.15em] text-teal bg-teal-faint border border-teal-line px-2 py-0.5 rounded-full">
          <span className="w-1.5 h-1.5 rounded-full bg-teal" />
          Connected
        </span>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// AgentStatusCard — right column secondary panel
// ──────────────────────────────────────────────────────────────────────────────

function AgentStatusCard({ clientId }: { clientId: string }) {
  const { data: agents, isLoading } = useAgents(clientId)

  return (
    <div className="bg-paper border border-line rounded-lg shadow-md p-6">
      <p className="font-mono text-xs font-medium uppercase tracking-[0.20em] text-ink-3 mb-4">
        Agent Status
      </p>

      {isLoading && (
        <div className="space-y-2">
          <div className="h-12 bg-mist rounded-md animate-pulse" />
          <div className="h-12 bg-mist rounded-md animate-pulse" />
        </div>
      )}

      {!isLoading && (!agents || agents.length === 0) && (
        <p className="text-sm text-ink-3">No agents configured.</p>
      )}

      {!isLoading && agents && agents.length > 0 && (
        <div className="space-y-2">
          {agents.map((agent) => (
            <div
              key={agent.agent_id}
              className="flex items-center gap-3 bg-pearl rounded-md px-3 py-2.5 border border-line"
            >
              {/* Live indicator */}
              {agent.is_active && agent.is_conversation_ready ? (
                <LiveIndicator size="sm" className="flex-shrink-0" />
              ) : (
                <span
                  className={[
                    'w-2.5 h-2.5 rounded-full flex-shrink-0',
                    agent.is_active ? 'bg-amber-400' : 'bg-ink-4',
                  ].join(' ')}
                  title={agent.is_active ? 'Active but not ready' : 'Inactive'}
                />
              )}
              {/* Agent info */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-ink truncate">{agent.name}</p>
                <p className="text-[11px] font-mono text-ink-3 truncate">{agent.slug}</p>
              </div>
              {/* Status label */}
              <span
                className={[
                  'text-[9px] font-mono font-semibold uppercase tracking-[0.15em] px-2 py-0.5 rounded-full border',
                  agent.is_active && agent.is_conversation_ready
                    ? 'text-teal bg-teal-faint border-teal-line'
                    : agent.is_active
                      ? 'text-amber-600 bg-amber-50 border-amber-200'
                      : 'text-ink-4 bg-mist border-line',
                ].join(' ')}
              >
                {agent.is_active && agent.is_conversation_ready
                  ? 'Live'
                  : agent.is_active
                    ? 'Setup'
                    : 'Inactive'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
