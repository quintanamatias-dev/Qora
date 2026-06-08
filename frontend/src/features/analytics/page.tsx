/**
 * AnalyticsDashboardPage — Container component for analytics dashboard
 *
 * Spec: analytics-dashboard-ui
 * Design: container-presentational pattern
 *   - Reads clientId from URL params
 *   - Manages period state (default: "month")
 *   - Manages agentId state (default: undefined = all agents)
 *   - Calls all 4 analytics hooks
 *   - Routes to loading/error/data UI branches
 *
 * Route: /app/:clientId/analytics
 */

import { useState } from 'react'
import { useParams } from 'react-router'
import {
  useAnalyticsOverview,
  useAnalyticsServiceIssues,
  useAnalyticsInterests,
  useAnalyticsAgentStats,
} from '@/api/hooks'
import type { AnalyticsPeriod } from '@/api/types'
import { PeriodSelector } from './period-selector'
import { AgentFilter } from './agent-filter'
import { OverviewSection } from './overview-section'
import { ServiceIssuesSection } from './service-issues-section'
import { InterestsSection } from './interests-section'
import { AgentStatsSection } from './agent-stats-section'

// ──────────────────────────────────────────────────────────────────────────────
// AnalyticsDashboardPage (container)
// ──────────────────────────────────────────────────────────────────────────────

export function AnalyticsDashboardPage() {
  const { clientId } = useParams<{ clientId: string }>()
  const [period, setPeriod] = useState<AnalyticsPeriod>('month')
  const [agentId, setAgentId] = useState<string>('all')

  // Convert 'all' sentinel to undefined for API params
  const resolvedAgentId = agentId === 'all' ? undefined : agentId
  const params = { period, agentId: resolvedAgentId }

  const overview = useAnalyticsOverview(clientId ?? '', params)
  const serviceIssues = useAnalyticsServiceIssues(clientId ?? '', params)
  const interests = useAnalyticsInterests(clientId ?? '', params)
  const agentStats = useAnalyticsAgentStats(clientId ?? '', params)

  const isLoading = overview.isLoading
  // CRITICAL 8: Check all 4 query error states
  const isError =
    overview.isError || serviceIssues.isError || interests.isError || agentStats.isError

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-medium text-ink">
            Analytics
          </h1>
          {clientId && (
            <p className="text-sm text-ink-2 mt-1">
              Client: <span className="text-teal font-medium">{clientId}</span>
            </p>
          )}
        </div>

        {/* Filters — period and agent selectors */}
        <div className="flex items-center gap-3">
          <AgentFilter
            clientId={clientId ?? ''}
            value={agentId}
            onChange={setAgentId}
          />
          <PeriodSelector value={period} onChange={setPeriod} />
        </div>
      </div>

      {/* Analytics content area */}
      <AnalyticsContent
        isLoading={isLoading}
        isError={isError}
        overview={overview.data ?? null}
        serviceIssues={serviceIssues.data ?? null}
        interests={interests.data ?? null}
        agentStats={agentStats.data ?? null}
      />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// AnalyticsContent — UI branch routing (presentational)
// ──────────────────────────────────────────────────────────────────────────────

import type {
  AnalyticsOverviewResponse,
  AnalyticsServiceIssuesResponse,
  AnalyticsInterestsResponse,
  AnalyticsAgentStatsResponse,
} from '@/api/types'

interface AnalyticsContentProps {
  isLoading: boolean
  isError: boolean
  overview: AnalyticsOverviewResponse | null
  serviceIssues: AnalyticsServiceIssuesResponse | null
  interests: AnalyticsInterestsResponse | null
  agentStats: AnalyticsAgentStatsResponse | null
}

function AnalyticsContent({
  isLoading,
  isError,
  overview,
  serviceIssues,
  interests,
  agentStats,
}: AnalyticsContentProps) {
  // Loading
  if (isLoading) {
    return (
      <div data-testid="analytics-loading" className="space-y-4 animate-pulse">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 bg-mist rounded-lg" />
        ))}
      </div>
    )
  }

  // Error (any section)
  if (isError) {
    return (
      <div
        data-testid="analytics-error"
        role="alert"
        className="bg-paper border border-line rounded-lg p-8 text-center space-y-4"
      >
        <p className="text-ink font-medium">
          Unable to load analytics. Please try again.
        </p>
      </div>
    )
  }

  // Data
  return (
    <div className="space-y-6">
      {overview && <OverviewSection data={overview} />}
      {serviceIssues && <ServiceIssuesSection data={serviceIssues} />}
      {interests && <InterestsSection data={interests} />}
      {agentStats && <AgentStatsSection data={agentStats} />}
    </div>
  )
}
