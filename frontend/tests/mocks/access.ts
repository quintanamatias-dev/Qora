/**
 * Access-admin MSW fixtures (multi-tenant-auth §8) — default state is an
 * unlinked client; tests opt into a linked organization via server.use().
 */

import { http, HttpResponse } from 'msw'
import type { AccessState, Invitation } from '../../src/api/access'

export function makeAccessState(overrides: Partial<AccessState> = {}): AccessState {
  return {
    organization_id: null,
    members: [],
    invitations: [],
    ...overrides,
  }
}

export function makeInvitation(overrides: Partial<Invitation> = {}): Invitation {
  return {
    id: 'invitation_default',
    email: 'new-member@acme-motors.com',
    state: 'pending',
    expires_at: '2026-10-01T00:00:00Z',
    ...overrides,
  }
}

export const accessHandlers = [
  http.get('/api/v1/clients/:clientId/access', () => HttpResponse.json(makeAccessState())),
  http.post('/api/v1/clients/:clientId/access/organization', () =>
    HttpResponse.json(makeAccessState({ organization_id: 'org_default' })),
  ),
  http.post('/api/v1/clients/:clientId/access/invitations', async ({ request }) => {
    const body = (await request.json()) as { email: string }
    return HttpResponse.json(makeInvitation({ email: body.email }), { status: 201 })
  }),
  http.delete('/api/v1/clients/:clientId/access/invitations/:invitationId', () => new HttpResponse(null, { status: 204 })),
]
