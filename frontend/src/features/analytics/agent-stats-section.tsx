/**
 * AgentStatsSection — "Rendimiento por agente" table
 *
 * Design: qora-presentacion/project/dashboard/screens-overview.jsx Analytics
 *
 * Note: the design mock shows an "Estado" column (live/setup) and a
 * "Duración prom." column. AnalyticsAgentStatsResponse has no per-agent
 * duration field, so that column is omitted. "Estado" is derived from the
 * real Agent record (is_active && is_conversation_ready), joined by agent_id;
 * unmatched/unassigned buckets show "Sin asignar".
 */

import type { AnalyticsAgentStatsResponse, Agent } from '@/api/types'

interface AgentStatsSectionProps {
  data: AnalyticsAgentStatsResponse
  agents: Agent[]
}

export function AgentStatsSection({ data, agents }: AgentStatsSectionProps) {
  const agentById = new Map(agents.map((a) => [a.agent_id, a]))

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h3>Rendimiento por agente</h3>
        </div>
      </div>
      {data.agents.length === 0 ? (
        <div className="empty">Sin datos de agentes en este período.</div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Agente</th>
                <th>Estado</th>
                <th className="r">Llamadas</th>
                <th className="r">Conversión</th>
              </tr>
            </thead>
            <tbody>
              {data.agents.map((stat) => {
                const agent = agentById.get(stat.agent_id)
                const isLive = agent ? agent.is_active && agent.is_conversation_ready : false
                return (
                  <tr key={stat.agent_id}>
                    <td>
                      <div className="lead-cell">
                        <span className="avatar">{(stat.agent_name ?? '?')[0]}</span>
                        <div className="t">
                          <b>{stat.agent_name ?? 'Sin asignar'}</b>
                          {agent && <span>{agent.slug}</span>}
                        </div>
                      </div>
                    </td>
                    <td>
                      {!agent ? (
                        <span className="tag ghost">Sin asignar</span>
                      ) : isLive ? (
                        <span className="tag teal">En línea</span>
                      ) : (
                        <span className="tag ghost">Configurando</span>
                      )}
                    </td>
                    <td className="r num">{stat.total_calls}</td>
                    <td className="r num">
                      {stat.conversion_rate == null ? '—' : `${(stat.conversion_rate * 100).toFixed(1)}%`}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
