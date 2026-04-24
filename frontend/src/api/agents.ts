/**
 * Agents API — typed endpoint functions
 *
 * URL paths match backend FastAPI routes at /api/v1/clients/:clientId/agents/*.
 */

import { apiFetch } from './client'
import type { Agent, CreateAgentPayload, UpdateAgentPayload } from './types'

/**
 * GET /api/v1/clients/:clientId/agents
 * Returns all agents for a client.
 */
export async function fetchAgents(clientId: string): Promise<Agent[]> {
  return apiFetch<Agent[]>(`/api/v1/clients/${encodeURIComponent(clientId)}/agents`)
}

/**
 * POST /api/v1/clients/:clientId/agents
 * Creates a new agent for a client.
 */
export async function createAgent(clientId: string, payload: CreateAgentPayload): Promise<Agent> {
  return apiFetch<Agent>(`/api/v1/clients/${encodeURIComponent(clientId)}/agents`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/**
 * PATCH /api/v1/clients/:clientId/agents/:agentId
 * Updates an agent.
 */
export async function updateAgent(
  clientId: string,
  agentId: string,
  payload: UpdateAgentPayload,
): Promise<Agent> {
  return apiFetch<Agent>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/agents/${encodeURIComponent(agentId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    },
  )
}

/**
 * POST /api/v1/clients/:clientId/agents/:agentId/deactivate
 * Deactivates an agent.
 */
export async function deactivateAgent(clientId: string, agentId: string): Promise<Agent> {
  return apiFetch<Agent>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/agents/${encodeURIComponent(agentId)}/deactivate`,
    { method: 'POST' },
  )
}

/**
 * POST /api/v1/clients/:clientId/agents/:agentId/make-default
 * Sets an agent as the default.
 */
export async function makeAgentDefault(clientId: string, agentId: string): Promise<Agent> {
  return apiFetch<Agent>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/agents/${encodeURIComponent(agentId)}/make-default`,
    { method: 'POST' },
  )
}
