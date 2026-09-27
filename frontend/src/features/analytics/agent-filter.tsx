/**
 * AgentFilter — dropdown to filter analytics by agent
 *
 * Renders a <select> element populated with real agents for the current client.
 * Default value "all" means no agent filter (all agents).
 * Design: qora-presentacion/project/dashboard/screens-overview.jsx Analytics — .select
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
      className="select"
      aria-label="Filtrar por agente"
    >
      <option value="all">Todos los agentes</option>
      {agents.map((agent) => (
        <option key={agent.agent_id} value={agent.agent_id}>
          {agent.name}
        </option>
      ))}
    </select>
  )
}
