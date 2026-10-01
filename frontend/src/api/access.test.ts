/**
 * Access admin API tests (multi-tenant-auth §8)
 */

import { describe, it, expect } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '../../tests/mocks/server'
import { makeAccessState, makeInvitation } from '../../tests/mocks/access'
import { fetchAccessState, linkOrganization, createInvitation, revokeInvitation } from './access'
import { ApiError } from './client'

describe('fetchAccessState', () => {
  it('returns the access state for a client', async () => {
    server.use(http.get('/api/v1/clients/:clientId/access', () => HttpResponse.json(makeAccessState({ organization_id: 'org_1' }))))
    const result = await fetchAccessState('acme-motors')
    expect(result.organization_id).toBe('org_1')
  })
})

describe('linkOrganization', () => {
  it('POSTs to /access/organization and returns the resulting state', async () => {
    const result = await linkOrganization('acme-motors')
    expect(result.organization_id).toBe('org_default')
  })
})

describe('createInvitation', () => {
  it('POSTs the email and returns the created invitation', async () => {
    const result = await createInvitation('acme-motors', 'new@acme-motors.com')
    expect(result.email).toBe('new@acme-motors.com')
    expect(result.state).toBe('pending')
  })

  it('throws ApiError with reason organization_not_linked on 409', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/access/invitations', () =>
        HttpResponse.json({ error: { code: 409, message: 'Organization not linked', reason: 'organization_not_linked', request_id: '' } }, { status: 409 }),
      ),
    )
    await expect(createInvitation('acme-motors', 'x@acme-motors.com')).rejects.toMatchObject({
      status: 409,
      reason: 'organization_not_linked',
    })
  })

  it('throws ApiError with reason auth_not_configured on 503', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/access/invitations', () =>
        HttpResponse.json({ error: { code: 503, message: 'Auth not configured', reason: 'auth_not_configured', request_id: '' } }, { status: 503 }),
      ),
    )
    const error: ApiError = await createInvitation('acme-motors', 'x@acme-motors.com').catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.reason).toBe('auth_not_configured')
  })
})

describe('revokeInvitation', () => {
  it('DELETEs the invitation and resolves without a body (204)', async () => {
    const makeInvitationFixture = makeInvitation()
    server.use(
      http.delete('/api/v1/clients/:clientId/access/invitations/:invitationId', ({ params }) => {
        expect(params.invitationId).toBe(makeInvitationFixture.id)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    await expect(revokeInvitation('acme-motors', makeInvitationFixture.id)).resolves.toBeUndefined()
  })
})
