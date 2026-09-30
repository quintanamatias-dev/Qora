/**
 * FeatureGate + plan-aware UI (multi-tenant-readiness WU3)
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { makeEntitlements } from '../../../tests/mocks/entitlements'
import { FeatureGate } from './feature-gate'
import { Sidebar } from '../../design/components/sidebar'
import type { FeatureKey } from '../../api/types'

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/app/acme-motors/dashboard']}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

function planWithout(feature: FeatureKey) {
  server.use(
    http.get('/api/v1/clients/:clientId/entitlements', () =>
      HttpResponse.json(makeEntitlements({ features: { [feature]: false } })),
    ),
  )
}

describe('FeatureGate', () => {
  it('renders children when the plan includes the feature', async () => {
    renderWithProviders(
      <FeatureGate clientId="acme-motors" feature="analytics">
        <p>contenido</p>
      </FeatureGate>,
    )
    expect(await screen.findByText('contenido')).toBeInTheDocument()
  })

  it('shows a plan notice instead of children when the feature is off', async () => {
    planWithout('analytics')
    renderWithProviders(
      <FeatureGate clientId="acme-motors" feature="analytics">
        <p>contenido</p>
      </FeatureGate>,
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Tu plan no incluye Analítica')
    expect(screen.queryByText('contenido')).not.toBeInTheDocument()
  })

  it('renders nothing when the feature is off and the notice is disabled', async () => {
    planWithout('live_monitor')
    const { container } = renderWithProviders(
      <FeatureGate clientId="acme-motors" feature="live_monitor" notice={false}>
        <p>contenido</p>
      </FeatureGate>,
    )
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('renders children when entitlements fail to load (backend still enforces)', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/entitlements', () => HttpResponse.json({}, { status: 500 })),
    )
    renderWithProviders(
      <FeatureGate clientId="acme-motors" feature="analytics">
        <p>contenido</p>
      </FeatureGate>,
    )
    expect(await screen.findByText('contenido')).toBeInTheDocument()
  })
})

describe('Sidebar plan gating', () => {
  it('shows Analítica when the plan includes analytics', async () => {
    renderWithProviders(<Sidebar clientId="acme-motors" />)
    expect(await screen.findByRole('link', { name: /Analítica/ })).toBeInTheDocument()
  })

  it('hides Analítica when the plan excludes analytics', async () => {
    planWithout('analytics')
    renderWithProviders(<Sidebar clientId="acme-motors" />)
    await waitFor(() => expect(screen.queryByRole('link', { name: /Analítica/ })).not.toBeInTheDocument())
    expect(screen.getByRole('link', { name: /Leads/ })).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Route-level gating through the production route config
// ──────────────────────────────────────────────────────────────────────────────

import { createMemoryRouter, RouterProvider } from 'react-router'
import { routes } from '../../router'

function renderRoute(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('plan gating per route', () => {
  it('analytics route shows the plan notice when analytics is off', async () => {
    planWithout('analytics')
    renderRoute('/app/acme-motors/analytics')
    expect(await screen.findByText('Tu plan no incluye Analítica')).toBeInTheDocument()
  })

  it('import page replaces the CRM card with the plan notice when CRM is off', async () => {
    planWithout('crm_integration')
    renderRoute('/app/acme-motors/import')
    expect(await screen.findByText('Tu plan no incluye Integración de CRM')).toBeInTheDocument()
  })

  it('dashboard does not request live calls when live monitor is off', async () => {
    planWithout('live_monitor')
    const liveRequests: string[] = []
    server.events.on('request:start', ({ request }) => {
      if (request.url.includes('/api/v1/calls/active')) liveRequests.push(request.url)
    })
    renderRoute('/app/acme-motors/dashboard')
    expect(await screen.findByRole('heading', { name: 'Resumen' })).toBeInTheDocument()
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50))
    })
    server.events.removeAllListeners()
    expect(liveRequests).toEqual([])
  })
})
