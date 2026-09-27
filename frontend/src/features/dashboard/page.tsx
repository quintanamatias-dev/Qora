/**
 * DashboardPage — "Resumen" (Overview)
 *
 * Design: qora-presentacion/project/dashboard/screens-overview.jsx (Overview + BarChart)
 * Ported classes come from src/design/dashboard.css (.page/.ph/.kpis/.kpi/.card/...).
 * PageContainer already renders <main className="page"> around the route Outlet —
 * this component renders its content directly, without an extra `.page` wrapper.
 */

import { LivePanel } from '@/features/live'
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { useMetrics, useCallSessions, useAgents, useLeads, useClient, useIntegrations } from '@/api/hooks'
import { Icon } from '@/design/components'
import { formatDuration } from '@/lib/format-duration'
import { bucketCallSessions, type Period, type ChartSeries } from './chart-buckets'
import type { CallMetricsResponse, CallSession, Agent, IntegrationConfig } from '@/api/types'
import {
  DEFAULT_TIMEZONE,
  resolveTimezone,
  startOfDayInZone,
  endOfDayInZone,
  createZonedFormatter,
} from '@/lib/timezone'

const REALTIME_INTERVAL_MS = 15_000

// ──────────────────────────────────────────────────────────────────────────────
// Pure helper — period → date range, computed in the client's timezone
// ──────────────────────────────────────────────────────────────────────────────

interface DateRange {
  date_from?: string
  date_to?: string
}

export function periodToDateRange(period: Period, tz: string = DEFAULT_TIMEZONE, now: Date = new Date()): DateRange {
  if (period === 'today') {
    return {
      date_from: startOfDayInZone(now, tz).toISOString(),
      date_to: endOfDayInZone(now, tz).toISOString(),
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

const PERIOD_LABELS: Record<Period, string> = {
  today: 'Hoy',
  '7d': '7 días',
  '30d': '30 días',
  all: 'Todo',
}

function periodSubLabel(period: Period): string {
  const label = PERIOD_LABELS[period]
  if (period === 'all') return 'Desde el inicio'
  if (period === 'today') return 'Hoy'
  return `Últimos ${label.toLowerCase()}`
}

// ──────────────────────────────────────────────────────────────────────────────
// DashboardPage
// ──────────────────────────────────────────────────────────────────────────────

export function DashboardPage() {
  const { clientId } = useParams<{ clientId: string }>()
  const activeClientId = clientId ?? ''
  const navigate = useNavigate()
  const [period, setPeriod] = useState<Period>('all')

  const { data: client } = useClient(activeClientId)
  const tz = useMemo(() => resolveTimezone(client?.scheduler_timezone), [client?.scheduler_timezone])
  const dateRange = useMemo(() => periodToDateRange(period, tz), [period, tz])
  const metrics = useMetrics(activeClientId, dateRange, {
    refetchInterval: REALTIME_INTERVAL_MS,
  })
  const sessions = useCallSessions(activeClientId, undefined, {
    refetchInterval: REALTIME_INTERVAL_MS,
  })
  const leads = useLeads(activeClientId)
  const agents = useAgents(activeClientId)
  const integrations = useIntegrations(activeClientId)

  const leadNames = useMemo(() => {
    const map = new Map<string, string>()
    for (const lead of leads.data ?? []) map.set(lead.id, lead.name)
    return map
  }, [leads.data])

  const clientName = client?.name ?? activeClientId

  return (
    <>
      <LivePanel clientId={activeClientId} embedded />
      <div className="page">
        <div className="ph">
          <div>
            <h1>Resumen</h1>
            <p data-testid="dashboard-subtitle">Lo que hicieron tus agentes de voz para {clientName}.</p>
          </div>
          <div className="ph-r">
            <Seg
              value={period}
              onChange={setPeriod}
              options={[
                ['today', 'Hoy'],
                ['7d', '7 días'],
                ['30d', '30 días'],
                ['all', 'Todo'],
              ]}
            />
          </div>
        </div>

        <MetricsArea
          loading={metrics.isLoading}
          error={metrics.isError}
          data={metrics.data ?? null}
          period={period}
          onRetry={metrics.refetch}
        >
          <div className="grid-2">
            <div className="stack">
              <VolumeChartCard sessions={sessions.data ?? []} loading={sessions.isLoading} period={period} tz={tz} />
              <RecentActivityCard
                sessions={sessions.data ?? []}
                loading={sessions.isLoading}
                leadNames={leadNames}
                clientId={activeClientId}
                tz={tz}
                onNavigateLeads={() => navigate(`/app/${activeClientId}/leads`)}
                onOpenLead={(leadId) => navigate(`/app/${activeClientId}/leads/${leadId}`)}
              />
            </div>
            <div className="stack">
              <AgentsCard agents={agents.data ?? []} loading={agents.isLoading} />
              <ConsumptionCard data={metrics.data ?? null} period={period} />
              <IntegrationsCard
                integrations={integrations.data ?? []}
                loading={integrations.isLoading}
                onManage={() => navigate(`/app/${activeClientId}/import`)}
              />
            </div>
          </div>
        </MetricsArea>
      </div>
    </>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Seg — period segmented control (design: ui.jsx Seg)
// ──────────────────────────────────────────────────────────────────────────────

interface SegProps {
  value: Period
  onChange: (period: Period) => void
  options: [Period, string][]
}

function Seg({ value, onChange, options }: SegProps) {
  return (
    <div className="seg" role="radiogroup" aria-label="Seleccionar período">
      {options.map(([k, l]) => (
        <button
          key={k}
          type="button"
          role="radio"
          aria-checked={value === k}
          className={value === k ? 'on' : ''}
          onClick={() => onChange(k)}
        >
          {l}
        </button>
      ))}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// MetricsArea — KPI strip + loading/error/empty routing for the metrics-derived UI
// ──────────────────────────────────────────────────────────────────────────────

interface MetricsAreaProps {
  loading: boolean
  error: boolean
  data: CallMetricsResponse | null
  period: Period
  onRetry?: () => void
  children: React.ReactNode
}

function MetricsArea({ loading, error, data, period, onRetry, children }: MetricsAreaProps) {
  if (loading) {
    return (
      <>
        <div className="kpis">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="kpi">
              <span className="eyebrow">&nbsp;</span>
              <span
                data-testid="kpi-skeleton"
                className="v"
                style={{
                  display: 'block',
                  height: 34,
                  width: 64,
                  background: 'var(--qd-surface-3)',
                  borderRadius: 6,
                }}
              />
              <span className="s">&nbsp;</span>
            </div>
          ))}
        </div>
        {children}
      </>
    )
  }

  if (error) {
    return (
      <div role="alert" className="card" style={{ padding: 32, textAlign: 'center' }}>
        <p style={{ fontWeight: 500 }}>No pudimos cargar las métricas. Intentá de nuevo.</p>
        <p className="muted" style={{ fontSize: 13 }}>
          Si el problema persiste, contactá a soporte.
        </p>
        {onRetry && (
          <button type="button" className="btn" style={{ marginTop: 12 }} onClick={onRetry}>
            Reintentar
          </button>
        )}
      </div>
    )
  }

  if (data && data.total_calls === 0) {
    return (
      <div data-testid="empty-state" className="card" style={{ padding: 32, textAlign: 'center' }}>
        <p style={{ fontWeight: 500 }}>No hay llamadas en este período</p>
        <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>
          Probá con un rango de fechas diferente para ver métricas.
        </p>
      </div>
    )
  }

  if (!data) return null

  const pc = (n: number) => (data.total_calls ? Math.round((n / data.total_calls) * 100) : 0)

  return (
    <>
      <div className="kpis">
        <div className="kpi">
          <span className="eyebrow">Llamadas</span>
          <span className="v">{data.total_calls}</span>
          <span className="s">{periodSubLabel(period)}</span>
        </div>
        <div className="kpi">
          <span className="eyebrow">Completadas</span>
          <span className="v" style={{ color: 'var(--qd-teal)' }}>
            <span>{data.completed_calls}</span>
            <small>{pc(data.completed_calls)}%</small>
          </span>
          <span className="s">Conversación con el lead</span>
        </div>
        <div className="kpi">
          <span className="eyebrow">Abandonadas</span>
          <span className="v" style={{ color: 'var(--qd-coral)' }}>
            <span>{data.abandoned_calls}</span>
            <small>{pc(data.abandoned_calls)}%</small>
          </span>
          <span className="s">Cortaron o no atendieron</span>
        </div>
        <div className="kpi">
          <span className="eyebrow">Duración prom.</span>
          <span className="v">{formatDuration(data.average_duration_seconds)}</span>
          <span className="s">Total {formatDuration(data.total_duration_seconds)} min</span>
        </div>
      </div>
      {children}
    </>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// VolumeChartCard — "Volumen de llamadas" stacked bar chart
// ──────────────────────────────────────────────────────────────────────────────

function VolumeChartCard({
  sessions,
  loading,
  period,
  tz,
}: {
  sessions: CallSession[]
  loading: boolean
  period: Period
  tz: string
}) {
  const chart: ChartSeries = useMemo(() => bucketCallSessions(sessions, period, new Date(), tz), [sessions, period, tz])

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h3>Volumen de llamadas</h3>
          <p>Por {chart.unit}</p>
        </div>
        <div className="r legend">
          <span>
            <i
              className="sw"
              style={{
                background: 'var(--qd-teal)',
                display: 'inline-block',
                width: 8,
                height: 8,
                borderRadius: 2,
              }}
            />
            Completadas
          </span>
          <span>
            <i
              className="sw"
              style={{
                background: 'var(--qd-bar-off)',
                display: 'inline-block',
                width: 8,
                height: 8,
                borderRadius: 2,
              }}
            />
            Abandonadas
          </span>
        </div>
      </div>
      <div className="card-b">
        {loading ? (
          <div
            style={{
              height: 160,
              background: 'var(--qd-surface-3)',
              borderRadius: 8,
            }}
          />
        ) : (
          <BarChart chart={chart} />
        )}
      </div>
    </section>
  )
}

function BarChart({ chart }: { chart: ChartSeries }) {
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(1, ...chart.series.map((d) => d.t))

  if (chart.series.length === 0) {
    return <div className="empty">Sin llamadas para graficar en este período.</div>
  }

  return (
    <div>
      <div className="chart">
        {chart.series.map((d, i) => (
          <div key={i} className="col" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <i
              style={{
                height: `${(d.c / max) * 100}%`,
                background: 'var(--qd-teal)',
              }}
            />
            <i
              style={{
                height: `${(d.a / max) * 100}%`,
                background: 'var(--qd-bar-off)',
              }}
            />
            {d.t === 0 && <i style={{ height: 2, background: 'var(--qd-line-2)' }} />}
            {hover === i && (
              <span className="tip">
                {d.t} llamadas · {d.c} completadas
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="chart-ax">
        {chart.axis.map((a, i) => (
          <span key={`${a}-${i}`}>{a}</span>
        ))}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// RecentActivityCard — last 5 calls
// ──────────────────────────────────────────────────────────────────────────────

const OUTCOME_LABELS: Record<string, string> = {
  no_answer: 'Sin respuesta',
  callback_requested: 'Pidió que lo llamen',
  wrong_number: 'Número equivocado',
  completed_negative: 'Completada · negativa',
  completed_positive: 'Completada · positiva',
}

function initials(name: string): string {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0])
    .join('')
    .toUpperCase()
}

function outcomeLabel(session: CallSession): string {
  if (session.outcome && OUTCOME_LABELS[session.outcome]) return OUTCOME_LABELS[session.outcome]
  return session.status === 'abandoned' ? 'Abandonada' : 'Completada'
}

function formatWhen(startedAt: string | null, tz: string): string {
  if (!startedAt) return '—'
  const fmt = createZonedFormatter(tz, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
  return fmt.format(new Date(startedAt)).replace(',', ' ·')
}

interface RecentActivityCardProps {
  sessions: CallSession[]
  loading: boolean
  leadNames: Map<string, string>
  clientId: string
  tz: string
  onNavigateLeads: () => void
  onOpenLead: (leadId: string) => void
}

function RecentActivityCard({
  sessions,
  loading,
  leadNames,
  tz,
  onNavigateLeads,
  onOpenLead,
}: RecentActivityCardProps) {
  const recent = useMemo(() => {
    return [...sessions].sort((a, b) => (b.started_at ?? '').localeCompare(a.started_at ?? '')).slice(0, 5)
  }, [sessions])

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h3>Actividad reciente</h3>
          <p>Últimas llamadas de tus agentes</p>
        </div>
        <div className="r">
          <button type="button" className="btn sm quiet" onClick={onNavigateLeads}>
            Ver leads
            <Icon name="arrowR" size={14} />
          </button>
        </div>
      </div>
      <div className="rows">
        {loading && <div className="empty">Cargando actividad reciente…</div>}
        {!loading && recent.length === 0 && <div className="empty">Todavía no hay llamadas.</div>}
        {!loading &&
          recent.map((session) => {
            const leadName = leadNames.get(session.lead_id) ?? session.lead_id
            return (
              <div key={session.id} className="row click" onClick={() => onOpenLead(session.lead_id)}>
                <span className="avatar">{initials(leadName)}</span>
                <div className="t">
                  <b>{leadName}</b>
                  <span>{outcomeLabel(session)}</span>
                </div>
                <span className="muted num" style={{ fontSize: 12.5, width: 110, textAlign: 'right' }}>
                  {formatWhen(session.started_at, tz)}
                </span>
                <span className="mono muted num" style={{ fontSize: 12, width: 40, textAlign: 'right' }}>
                  {session.duration_seconds != null ? formatDuration(session.duration_seconds) : '—'}
                </span>
                <span
                  style={{
                    width: 96,
                    display: 'flex',
                    justifyContent: 'flex-end',
                  }}
                >
                  <CallStatus status={session.status} />
                </span>
              </div>
            )
          })}
      </div>
    </section>
  )
}

function CallStatus({ status }: { status: CallSession['status'] }) {
  return status === 'abandoned' ? (
    <span className="tag ghost">Abandonada</span>
  ) : (
    <span className="tag teal">Completada</span>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// AgentsCard — right rail
// ──────────────────────────────────────────────────────────────────────────────

function AgentsCard({ agents, loading }: { agents: Agent[]; loading: boolean }) {
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h3>Agentes</h3>
        </div>
      </div>
      <div className="rows">
        {loading && <div className="empty">Cargando agentes…</div>}
        {!loading && agents.length === 0 && <div className="empty">Sin agentes configurados.</div>}
        {!loading &&
          agents.map((agent) => {
            const isLive = agent.is_active && agent.is_conversation_ready
            return (
              <div key={agent.agent_id} className="row">
                <span
                  className="avatar"
                  style={
                    isLive
                      ? {
                          background: 'var(--qd-teal-faint)',
                          color: 'var(--qd-teal)',
                        }
                      : undefined
                  }
                >
                  {agent.name[0]}
                </span>
                <div className="t">
                  <b>
                    {agent.name}{' '}
                    <span className="mono muted" style={{ fontSize: 11, fontWeight: 400 }}>
                      {agent.slug}
                    </span>
                  </b>
                </div>
                {isLive ? (
                  <span className="tag teal">
                    <i className="dot live" style={{ boxShadow: 'none' }} />
                    En línea
                  </span>
                ) : (
                  <span className="tag ghost">Configurando</span>
                )}
              </div>
            )
          })}
      </div>
    </section>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// ConsumptionCard — right rail
// ──────────────────────────────────────────────────────────────────────────────

function ConsumptionCard({ data, period }: { data: CallMetricsResponse | null; period: Period }) {
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h3>Consumo</h3>
          <p>{periodSubLabel(period)}</p>
        </div>
      </div>
      <div className="card-b" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
          }}
        >
          <span className="muted">Minutos facturables</span>
          <span style={{ font: '500 22px/1 var(--qd-F)' }} className="num">
            {data?.total_billable_minutes ?? 0} min
          </span>
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
          }}
        >
          <span className="muted">Tiempo en conversación</span>
          <span className="mono num">{formatDuration(data?.total_duration_seconds ?? 0)}</span>
        </div>
        <p className="muted" style={{ margin: 0, fontSize: 12 }}>
          Cada llamada se factura redondeando al minuto siguiente.
        </p>
      </div>
    </section>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// IntegrationsCard — right rail
// ──────────────────────────────────────────────────────────────────────────────

function providerLabel(provider: string): string {
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

function IntegrationsCard({
  integrations,
  loading,
  onManage,
}: {
  integrations: IntegrationConfig[]
  loading: boolean
  onManage: () => void
}) {
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h3>Integraciones</h3>
        </div>
        <div className="r">
          <button type="button" className="btn sm quiet" onClick={onManage}>
            Gestionar
          </button>
        </div>
      </div>
      {loading && <div className="empty">Cargando integraciones…</div>}
      {!loading && integrations.length === 0 && <div className="empty">Sin integraciones conectadas.</div>}
      {!loading &&
        integrations.map((integration) => (
          <div className="row" key={integration.provider}>
            <span className="avatar" style={{ borderRadius: 8, font: '600 11px/1 var(--qd-M)' }}>
              {integration.provider.slice(0, 2).toUpperCase()}
            </span>
            <div className="t">
              <b>{providerLabel(integration.provider)}</b>
              <span className="mono" style={{ fontSize: 11.5 }}>
                {integration.table_id}
              </span>
            </div>
            {integration.connected ? (
              <span className="tag teal">Conectado</span>
            ) : (
              <span className="tag ghost">Desconectado</span>
            )}
          </div>
        ))}
    </section>
  )
}
