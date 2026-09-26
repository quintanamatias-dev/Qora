/**
 * AnalyticsDashboardPage — "Analítica"
 *
 * Design: qora-presentacion/project/dashboard/screens-overview.jsx (Analytics)
 * Ported classes come from src/design/dashboard.css (.page/.ph/.kpis/.kpi/.card/...).
 * PageContainer already renders <main className="page"> around the route Outlet —
 * this component renders its content directly, without an extra `.page` wrapper.
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
  useAgents,
} from '@/api/hooks'
import type {
  AnalyticsPeriod,
  AnalyticsOverviewResponse,
  AnalyticsServiceIssuesResponse,
  AnalyticsInterestsResponse,
  AnalyticsAgentStatsResponse,
  Agent,
} from '@/api/types'
import { PeriodSelector } from './period-selector'
import { CustomDateRange } from './custom-date-range'
import { AgentFilter } from './agent-filter'
import { OverviewSection } from './overview-section'
import { ServiceIssuesSection } from './service-issues-section'
import { InterestsSection } from './interests-section'
import { AgentStatsSection } from './agent-stats-section'

const REALTIME_INTERVAL_MS = 30_000

function defaultCustomRange(): { startDate: string; endDate: string } {
  const end = new Date()
  const start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000)
  const toISODate = (d: Date) => d.toISOString().slice(0, 10)
  return { startDate: toISODate(start), endDate: toISODate(end) }
}

// ──────────────────────────────────────────────────────────────────────────────
// AnalyticsDashboardPage (container)
// ──────────────────────────────────────────────────────────────────────────────

export function AnalyticsDashboardPage() {
  const { clientId } = useParams<{ clientId: string }>()
  const activeClientId = clientId ?? ''
  const [period, setPeriod] = useState<AnalyticsPeriod>('month')
  const [agentId, setAgentId] = useState<string>('all')
  const [customRange, setCustomRange] = useState(defaultCustomRange)

  const resolvedAgentId = agentId === 'all' ? undefined : agentId
  const params =
    period === 'custom'
      ? { period, agentId: resolvedAgentId, startDate: customRange.startDate, endDate: customRange.endDate }
      : { period, agentId: resolvedAgentId }

  const overview = useAnalyticsOverview(activeClientId, params, { refetchInterval: REALTIME_INTERVAL_MS })
  const serviceIssues = useAnalyticsServiceIssues(activeClientId, params, { refetchInterval: REALTIME_INTERVAL_MS })
  const interests = useAnalyticsInterests(activeClientId, params, { refetchInterval: REALTIME_INTERVAL_MS })
  const agentStats = useAnalyticsAgentStats(activeClientId, params, { refetchInterval: REALTIME_INTERVAL_MS })
  const agents = useAgents(activeClientId, { refetchInterval: REALTIME_INTERVAL_MS })

  const isLoading = overview.isLoading
  const isError = overview.isError || serviceIssues.isError || interests.isError || agentStats.isError

  const retryAll = () => {
    overview.refetch()
    serviceIssues.refetch()
    interests.refetch()
    agentStats.refetch()
  }

  return (
    <div className="page">
      <div className="ph">
        <div>
          <h1>Analítica</h1>
          <p>Resultados de las conversaciones y lo que dicen tus leads.</p>
        </div>
        <div className="ph-r">
          <AgentFilter clientId={activeClientId} value={agentId} onChange={setAgentId} />
          {period === 'custom' && <CustomDateRange {...customRange} onChange={setCustomRange} />}
          <PeriodSelector value={period} onChange={setPeriod} />
        </div>
      </div>

      <AnalyticsContent
        isLoading={isLoading}
        isError={isError}
        onRetry={retryAll}
        overview={overview.data ?? null}
        serviceIssues={serviceIssues.data ?? null}
        interests={interests.data ?? null}
        agentStats={agentStats.data ?? null}
        agents={agents.data ?? []}
      />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// AnalyticsContent — loading/error/data routing (presentational)
// ──────────────────────────────────────────────────────────────────────────────

interface AnalyticsContentProps {
  isLoading: boolean
  isError: boolean
  onRetry: () => void
  overview: AnalyticsOverviewResponse | null
  serviceIssues: AnalyticsServiceIssuesResponse | null
  interests: AnalyticsInterestsResponse | null
  agentStats: AnalyticsAgentStatsResponse | null
  agents: Agent[]
}

function AnalyticsContent({
  isLoading,
  isError,
  onRetry,
  overview,
  serviceIssues,
  interests,
  agentStats,
  agents,
}: AnalyticsContentProps) {
  if (isLoading) {
    return (
      <div data-testid="analytics-loading">
        <div className="kpis">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="kpi">
              <span className="eyebrow">&nbsp;</span>
              <span
                className="v"
                style={{ display: 'block', height: 34, width: 64, background: 'var(--qd-surface-3)', borderRadius: 6 }}
              />
              <span className="s">&nbsp;</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div data-testid="analytics-error" role="alert" className="card" style={{ padding: 32, textAlign: 'center' }}>
        <p style={{ fontWeight: 500 }}>No pudimos cargar la analítica. Intentá de nuevo.</p>
        <p className="muted" style={{ fontSize: 13 }}>Si el problema persiste, contactá a soporte.</p>
        <button type="button" className="btn" style={{ marginTop: 12 }} onClick={onRetry}>
          Reintentar
        </button>
      </div>
    )
  }

  if (!overview) return null

  if (overview.total_calls === 0) {
    return (
      <div data-testid="empty-state" className="card" style={{ padding: 32, textAlign: 'center' }}>
        <p style={{ fontWeight: 500 }}>No hay llamadas en este período</p>
        <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>
          Probá con un rango de fechas diferente para ver la analítica.
        </p>
      </div>
    )
  }

  const noAnswer = overview.outcome_distribution.no_answer ?? 0
  const wrongNumber = overview.outcome_distribution.wrong_number ?? 0
  const reached = overview.total_calls - noAnswer - wrongNumber
  const contactability = overview.total_calls ? Math.round((reached / overview.total_calls) * 100) : 0
  const conversion = overview.conversion_rate != null ? (overview.conversion_rate * 100).toFixed(1) : '0.0'
  const callbackRequested = overview.outcome_distribution.callback_requested ?? 0

  return (
    <>
      <div className="kpis">
        <div className="kpi">
          <span className="eyebrow">Llamadas</span>
          <span className="v">{overview.total_calls}</span>
          <span className="s">En el período</span>
        </div>
        <div className="kpi">
          <span className="eyebrow">Conversión</span>
          <span className="v">
            {conversion}
            <small>%</small>
          </span>
          <span className="s">Leads que pasaron a cotizado</span>
        </div>
        <div className="kpi">
          <span className="eyebrow">Contactabilidad</span>
          <span className="v">
            {contactability}
            <small>%</small>
          </span>
          <span className="s">
            {reached} de {overview.total_calls} atendieron
          </span>
        </div>
        <div className="kpi">
          <span className="eyebrow">Volver a llamar</span>
          <span className="v" style={{ color: 'var(--qd-teal)' }}>
            {callbackRequested}
          </span>
          <span className="s">Lo pidieron explícitamente</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(340px,1fr))', gap: 20 }}>
        <OverviewSection data={overview} />
        {serviceIssues && <ServiceIssuesSection data={serviceIssues} />}
      </div>

      {interests && <InterestsSection data={interests} />}
      {agentStats && <AgentStatsSection data={agentStats} agents={agents} />}
    </>
  )
}
