/**
 * AgentFilter — dropdown to filter analytics by agent
 *
 * Renders a <select> element populated with agents for the current client.
 * Default value "all" means no agent filter (all agents).
 */

import { useAgents } from '@/api/hooks'

interface AgentFilterProps {
  clientId: string
  value: string
  onChange: (agentId: string) => void
}

export function AgentFilter({ clientId, value, onChange }: AgentFilterProps) {
  const { data: agents = [] } = useAgents(clientId)

  return (
    <select
      data-testid="agent-filter"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border border-outline bg-surface px-3 py-1.5 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
      aria-label="Filter by agent"
    >
      <option value="all">All agents</option>
      {agents.map((agent) => (
        <option key={agent.agent_id} value={agent.agent_id}>
          {agent.name}
        </option>
      ))}
    </select>
  )
}
