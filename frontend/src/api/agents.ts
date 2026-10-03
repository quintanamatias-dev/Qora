/**
 * Agents API — typed endpoint functions
 *
 * URL paths match backend FastAPI routes at /api/v1/clients/:clientId/agents/*.
 */

import { apiFetch } from './client'
import type {
  Agent,
  AgentConfigPatchPayload,
  AgentConfigRevision,
  CreateAgentPayload,
  EffectiveConfig,
  UpdateAgentPayload,
} from './types'

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
 * GET /api/v1/clients/:clientId/agents/:agentId/revisions
 * Returns all config revisions for an agent, newest first.
 */
export async function fetchAgentRevisions(
  clientId: string,
  agentId: string,
): Promise<AgentConfigRevision[]> {
  return apiFetch<AgentConfigRevision[]>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/agents/${encodeURIComponent(agentId)}/revisions`,
  )
}

/**
 * GET /api/v1/clients/:clientId/agents/:agentId/effective-config
 * Returns every config field's resolved value, provenance (standard/client/agent),
 * and policy, plus completeness markers.
 */
export async function fetchAgentEffectiveConfig(
  clientId: string,
  agentId: string,
): Promise<EffectiveConfig> {
  return apiFetch<EffectiveConfig>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/agents/${encodeURIComponent(agentId)}/effective-config`,
  )
}

/**
 * PATCH /api/v1/clients/:clientId/agents/:agentId/config
 * Sparse override write: a null value removes an existing override (inherit again).
 */
export async function patchAgentConfig(
  clientId: string,
  agentId: string,
  payload: AgentConfigPatchPayload,
): Promise<AgentConfigRevision> {
  return apiFetch<AgentConfigRevision>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/agents/${encodeURIComponent(agentId)}/config`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    },
  )
}

/**
 * POST /api/v1/clients/:clientId/agents/:agentId/revisions/:revisionId/rollback
 * Creates and activates a new revision copying the target revision's config.
 */
export async function rollbackAgentRevision(
  clientId: string,
  agentId: string,
  revisionId: string,
): Promise<AgentConfigRevision> {
  return apiFetch<AgentConfigRevision>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/agents/${encodeURIComponent(agentId)}/revisions/${encodeURIComponent(revisionId)}/rollback`,
    { method: 'POST' },
  )
}
