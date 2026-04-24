/**
 * Clients API — typed endpoint functions
 *
 * REQ-5.2: Typed functions matching backend API surface for client resources.
 * URL paths match backend FastAPI routes at /api/v1/clients/*.
 */

import { apiFetch } from './client'
import type { Client, CreateClientPayload, UpdateClientPayload } from './types'

/**
 * GET /api/v1/clients
 * Returns all clients.
 */
export async function fetchClients(): Promise<Client[]> {
  return apiFetch<Client[]>('/api/v1/clients')
}

/**
 * GET /api/v1/clients/:clientId
 * Returns a single client by ID.
 */
export async function fetchClient(clientId: string): Promise<Client> {
  return apiFetch<Client>(`/api/v1/clients/${encodeURIComponent(clientId)}`)
}

/**
 * POST /api/v1/clients
 * Creates a new client.
 */
export async function createClient(payload: CreateClientPayload): Promise<Client> {
  return apiFetch<Client>('/api/v1/clients', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/**
 * PATCH /api/v1/clients/:clientId
 * Updates a client.
 */
export async function updateClient(clientId: string, payload: UpdateClientPayload): Promise<Client> {
  return apiFetch<Client>(`/api/v1/clients/${encodeURIComponent(clientId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

/**
 * DELETE /api/v1/clients/:clientId
 * Deactivates (soft delete) a client.
 */
export async function deactivateClient(clientId: string): Promise<Client> {
  return apiFetch<Client>(`/api/v1/clients/${encodeURIComponent(clientId)}`, {
    method: 'DELETE',
  })
}
