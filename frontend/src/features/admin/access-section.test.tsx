/**
 * AccessSection tests (multi-tenant-auth §8, §9)
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { makeAccessState, makeInvitation } from '../../../tests/mocks/access'
import { AccessSection } from './access-section'

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <AccessSection clientId="acme-motors" />
    </QueryClientProvider>,
  )
}

describe('AccessSection', () => {
  it('shows a "Conectar con WorkOS" button when no organization is linked', async () => {
    renderSection()
    expect(await screen.findByRole('button', { name: 'Conectar con WorkOS' })).toBeInTheDocument()
    expect(screen.getByText('No hay miembros todavía.')).toBeInTheDocument()
    expect(screen.getByText('No hay invitaciones pendientes.')).toBeInTheDocument()
  })

  it('links the organization on click and shows the resulting organization id', async () => {
    const user = userEvent.setup()
    renderSection()

    await user.click(await screen.findByRole('button', { name: 'Conectar con WorkOS' }))

    expect(await screen.findByTestId('access-organization-id')).toHaveTextContent('org_default')
  })

  it('shows the linked organization, members and pending invitations', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/access', () =>
        HttpResponse.json(
          makeAccessState({
            organization_id: 'org_acme',
            members: [{ user_id: 'user_1', email: 'owner@acme-motors.com', name: 'Acme Owner' }],
            invitations: [makeInvitation({ id: 'inv-1', email: 'new@acme-motors.com' })],
          }),
        ),
      ),
    )
    renderSection()

    expect(await screen.findByTestId('access-organization-id')).toHaveTextContent('org_acme')
    expect(screen.getByText('owner@acme-motors.com')).toBeInTheDocument()
    expect(screen.getByText('new@acme-motors.com')).toBeInTheDocument()
    expect(screen.getByTestId('revoke-invitation-inv-1')).toBeInTheDocument()
  })

  it('revokes a pending invitation', async () => {
    let revoked = false
    server.use(
      http.get('/api/v1/clients/:clientId/access', () =>
        HttpResponse.json(
          makeAccessState({
            organization_id: 'org_acme',
            invitations: revoked ? [] : [makeInvitation({ id: 'inv-1', email: 'new@acme-motors.com' })],
          }),
        ),
      ),
      http.delete('/api/v1/clients/:clientId/access/invitations/:invitationId', () => {
        revoked = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderSection()

    await user.click(await screen.findByTestId('revoke-invitation-inv-1'))

    await waitFor(() => expect(screen.getByText('No hay invitaciones pendientes.')).toBeInTheDocument())
  })

  it('invites a member by email', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/access', () =>
        HttpResponse.json(makeAccessState({ organization_id: 'org_acme' })),
      ),
    )
    const user = userEvent.setup()
    renderSection()

    await user.type(await screen.findByLabelText('Email'), 'new-member@acme-motors.com')
    await user.click(screen.getByRole('button', { name: 'Invitar' }))

    expect(await screen.findByText('Invitación enviada.')).toBeInTheDocument()
  })

  it('shows a clear message on 409 organization_not_linked', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/access/invitations', () =>
        HttpResponse.json(
          { error: { code: 409, message: 'Organization not linked', reason: 'organization_not_linked', request_id: '' } },
          { status: 409 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderSection()

    await user.type(await screen.findByLabelText('Email'), 'new-member@acme-motors.com')
    await user.click(screen.getByRole('button', { name: 'Invitar' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Vinculá la organización con WorkOS antes de invitar miembros.',
    )
  })

  it('shows a clear message on 503 auth_not_configured', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/access/invitations', () =>
        HttpResponse.json(
          { error: { code: 503, message: 'Auth not configured', reason: 'auth_not_configured', request_id: '' } },
          { status: 503 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderSection()

    await user.type(await screen.findByLabelText('Email'), 'new-member@acme-motors.com')
    await user.click(screen.getByRole('button', { name: 'Invitar' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('La integración con WorkOS no está configurada.')
  })

  it('shows a clear message when the whole section fails to load due to auth_not_configured', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/access', () =>
        HttpResponse.json(
          { error: { code: 503, message: 'Auth not configured', reason: 'auth_not_configured', request_id: '' } },
          { status: 503 },
        ),
      ),
    )
    renderSection()
    expect(await screen.findByRole('alert')).toHaveTextContent('La integración con WorkOS no está configurada.')
  })
})
