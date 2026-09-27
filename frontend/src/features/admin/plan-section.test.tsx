/**
 * PlanSection — superadmin plan & entitlement editor (multi-tenant-readiness WU3)
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { makeEntitlements } from '../../../tests/mocks/entitlements'
import { PlanSection } from './plan-section'

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <PlanSection clientId="acme-motors" />
    </QueryClientProvider>,
  )
}

function captureSave() {
  const saved: { body?: unknown } = {}
  server.use(
    http.put('/api/v1/clients/:clientId/entitlements', async ({ request }) => {
      saved.body = await request.json()
      const body = saved.body as { plan: string }
      return HttpResponse.json(makeEntitlements({ plan: body.plan }))
    }),
  )
  return saved
}

describe('PlanSection', () => {
  it('shows the current plan and this month usage', async () => {
    renderSection()
    expect(await screen.findByLabelText('Plan')).toHaveValue('pilot')
    expect(screen.getByTestId('plan-usage')).toHaveTextContent('34 min')
    expect(screen.getByTestId('plan-usage')).toHaveTextContent('12 calls')
  })

  it('switching plan loads that plan defaults and saves no overrides', async () => {
    const saved = captureSave()
    const user = userEvent.setup()
    renderSection()

    await user.selectOptions(await screen.findByLabelText('Plan'), 'starter')
    expect(screen.getByLabelText('Live monitor')).not.toBeChecked()
    expect(screen.getByLabelText('Monthly minutes')).toHaveValue(200)

    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(saved.body).toEqual({ plan: 'starter', overrides: {} }))
  })

  it('saves only the differences from the plan as overrides', async () => {
    const saved = captureSave()
    const user = userEvent.setup()
    renderSection()

    await user.selectOptions(await screen.findByLabelText('Plan'), 'starter')
    await user.click(screen.getByLabelText('Live monitor'))
    const minutes = screen.getByLabelText('Monthly minutes')
    await user.clear(minutes)
    await user.type(minutes, '500')
    await user.clear(screen.getByLabelText('Agents'))

    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() =>
      expect(saved.body).toEqual({
        plan: 'starter',
        overrides: {
          features: { live_monitor: true },
          limits: { max_monthly_minutes: 500, max_agents: null },
        },
      }),
    )
  })

  it('loads existing overrides into the form', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/entitlements', () =>
        HttpResponse.json(
          makeEntitlements({
            plan: 'starter',
            features: { auto_dialer: false, crm_integration: false, live_monitor: true },
            limits: { max_agents: 1, max_concurrent_calls: 1, max_monthly_minutes: 200 },
            overrides: { features: { live_monitor: true } },
          }),
        ),
      ),
    )
    renderSection()
    expect(await screen.findByLabelText('Live monitor')).toBeChecked()
    expect(screen.getByText(/1 exception/)).toBeInTheDocument()
  })

  it('surfaces a save error', async () => {
    server.use(
      http.put('/api/v1/clients/:clientId/entitlements', () =>
        HttpResponse.json({ error: { code: 422, message: 'Unknown plan', reason: 'unknown_plan', request_id: '' } }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    renderSection()
    await user.click(await screen.findByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Unknown plan')
  })
})
