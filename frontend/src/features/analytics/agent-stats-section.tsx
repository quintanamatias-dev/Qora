/**
 * AgentStatsSection — Per-agent call statistics table
 *
 * Shows: agent name, total calls, conversion rate, engagement quality
 * Design: presentational, receives data as props.
 */

import type { AnalyticsAgentStatsResponse } from '@/api/types'

interface AgentStatsSectionProps {
  data: AnalyticsAgentStatsResponse
}

export function AgentStatsSection({ data }: AgentStatsSectionProps) {
  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-on-surface">Agent Stats</h2>
      {data.agents.length === 0 ? (
        <p className="text-sm text-on-surface-variant">No agent data for this period.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-on-surface-variant">
                <th className="text-left py-2 px-3 font-medium">Agent</th>
                <th className="text-right py-2 px-3 font-medium">Calls</th>
                <th className="text-right py-2 px-3 font-medium">Conversion</th>
                <th className="text-right py-2 px-3 font-medium">Engagement</th>
              </tr>
            </thead>
            <tbody>
              {data.agents.map((agent) => (
                <tr
                  key={agent.agent_id}
                  className="border-b border-border/50 hover:bg-surface-container-low"
                >
                  <td className="py-2 px-3 text-on-surface font-medium">
                    {agent.agent_name ?? agent.agent_id}
                  </td>
                  <td className="py-2 px-3 text-right text-on-surface">
                    {agent.total_calls}
                  </td>
                  <td className="py-2 px-3 text-right text-on-surface">
                    {agent.conversion_rate !== null
                      ? `${(agent.conversion_rate * 100).toFixed(1)}%`
                      : 'N/A'}
                  </td>
                  <td className="py-2 px-3 text-right text-on-surface">
                    {agent.avg_engagement_quality ?? 'N/A'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
