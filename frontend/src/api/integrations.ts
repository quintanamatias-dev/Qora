/**
 * Integrations API — typed endpoint functions
 *
 * Endpoints:
 * - GET    /api/v1/clients/{client_id}/integrations → IntegrationConfig[]
 * - GET    /api/v1/clients/{client_id}/integrations/available → AvailableIntegration[]
 * - PUT    /api/v1/clients/{client_id}/integrations/{provider} → IntegrationConfig
 * - POST   /api/v1/clients/{client_id}/integrations/{provider}/connect → IntegrationConfig
 * - POST   /api/v1/clients/{client_id}/integrations/{provider}/test → IntegrationTestResult
 * - DELETE /api/v1/clients/{client_id}/integrations/{provider}/disconnect → DisconnectResult
 *
 * SECURITY: api_key_env is always an env var name, never the actual secret.
 */

import { apiFetch } from './client'
import type {
  IntegrationConfig,
  UpdateIntegrationPayload,
  IntegrationTestResult,
  AvailableIntegration,
  ConnectIntegrationPayload,
  DisconnectResult,
} from './types'

/**
 * GET /api/v1/clients/{client_id}/integrations
 * Returns all configured integrations for the client.
 * Returns empty array if no integrations configured.
 */
export async function fetchIntegrations(clientId: string): Promise<IntegrationConfig[]> {
  return apiFetch<IntegrationConfig[]>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/integrations`,
  )
}

/**
 * PUT /api/v1/clients/{client_id}/integrations/{provider}
 * Updates an integration's configuration.
 * Returns the updated IntegrationConfig.
 */
export async function updateIntegration(
  clientId: string,
  provider: string,
  payload: UpdateIntegrationPayload,
): Promise<IntegrationConfig> {
  return apiFetch<IntegrationConfig>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/integrations/${encodeURIComponent(provider)}`,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
    },
  )
}

/**
 * POST /api/v1/clients/{client_id}/integrations/{provider}/test
 * Tests the connection for an integration.
 * Returns success/failure with a message and optional record count.
 */
export async function testIntegrationConnection(
  clientId: string,
  provider: string,
): Promise<IntegrationTestResult> {
  return apiFetch<IntegrationTestResult>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/integrations/${encodeURIComponent(provider)}/test`,
    {
      method: 'POST',
    },
  )
}

/**
 * GET /api/v1/clients/{client_id}/integrations/available
 * Returns all supported integration providers with their connection status.
 */
export async function fetchAvailableIntegrations(
  clientId: string,
): Promise<AvailableIntegration[]> {
  return apiFetch<AvailableIntegration[]>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/integrations/available`,
  )
}

/**
 * POST /api/v1/clients/{client_id}/integrations/{provider}/connect
 * Creates a new integration config (crm.yaml) with default mappings.
 * Returns the created IntegrationConfig.
 * SECURITY: api_key_env in payload is the env var NAME only.
 */
export async function connectIntegration(
  clientId: string,
  provider: string,
  payload: ConnectIntegrationPayload,
): Promise<IntegrationConfig> {
  return apiFetch<IntegrationConfig>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/integrations/${encodeURIComponent(provider)}/connect`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}

/**
 * DELETE /api/v1/clients/{client_id}/integrations/{provider}/disconnect
 * Removes the integration config (crm.yaml) for the client.
 */
export async function disconnectIntegration(
  clientId: string,
  provider: string,
): Promise<DisconnectResult> {
  return apiFetch<DisconnectResult>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/integrations/${encodeURIComponent(provider)}/disconnect`,
    {
      method: 'DELETE',
    },
  )
}
