/**
 * CAP-3: Layout Primitives Tests (Sidebar, TopBar, PageContainer)
 * TDD Layer: Integration — render tests
 *
 * REQ-3.5: Sidebar, TopBar, PageContainer render without errors
 * REQ-4.2: Active navigation state — active link shows aria-current="page"
 *
 * Sidebar/TopBar now fetch real client/leads/agents data via TanStack Query
 * (useClient/useLeads/useAgents), so every render needs a QueryClientProvider.
 * MSW handlers (tests/mocks/handlers.ts) back 'demo-client' and 'acme-motors'.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect } from 'vitest'
import { Sidebar } from './sidebar'
import { TopBar } from './top-bar'
import { PageContainer } from './page-container'

function renderWithProviders(ui: React.ReactElement, initialEntries = ['/app/demo-client/dashboard']) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Sidebar', () => {
  it('renders without crashing', () => {
    renderWithProviders(<Sidebar clientId="demo-client" />)
    expect(screen.getByRole('navigation')).toBeInTheDocument()
  })

  it('renders navigation links for Resumen and Leads (Spanish labels)', () => {
    renderWithProviders(<Sidebar clientId="demo-client" />)
    expect(screen.getByText('Resumen')).toBeInTheDocument()
    expect(screen.getByText('Leads')).toBeInTheDocument()
  })

  it('displays clientId-based real hrefs', () => {
    renderWithProviders(<Sidebar clientId="acme-motors" />)
    const link = screen.getByRole('link', { name: /Resumen/i })
    expect(link).toHaveAttribute('href', '/app/acme-motors/dashboard')
  })

  it('shows the real client name and client_id in the workspace block', async () => {
    renderWithProviders(<Sidebar clientId="demo-client" />)
    await waitFor(() => expect(screen.getByText('Demo Broker')).toBeInTheDocument())
    expect(screen.getByText('demo-client')).toBeInTheDocument()
  })

  it('shows the Leads count from useLeads', async () => {
    renderWithProviders(<Sidebar clientId="demo-client" />)
    const leadsLink = await screen.findByRole('link', { name: /Leads/i })
    await waitFor(() => expect(leadsLink).toHaveTextContent('2'))
  })

  it('shows agent status dots (En línea / Config.) from useAgents', async () => {
    renderWithProviders(<Sidebar clientId="demo-client" />)
    await waitFor(() => expect(screen.getByText('Primary Agent')).toBeInTheDocument())
    expect(screen.getByText('En línea')).toBeInTheDocument()
    expect(screen.getByText('Secondary Agent')).toBeInTheDocument()
    expect(screen.getByText('Config.')).toBeInTheDocument()
  })

  it('does not render a fake user identity in the footer', () => {
    renderWithProviders(<Sidebar clientId="demo-client" />)
    expect(screen.queryByText('Juan Quintana')).not.toBeInTheDocument()
    expect(screen.queryByText('Administrador')).not.toBeInTheDocument()
  })
})

describe('TopBar', () => {
  it('renders without crashing', () => {
    renderWithProviders(<TopBar clientId="demo-client" />)
    expect(screen.getByRole('banner')).toBeInTheDocument()
  })

  it('displays the real client name as breadcrumb context', async () => {
    renderWithProviders(<TopBar clientId="acme-motors" />, ['/app/acme-motors/dashboard'])
    await waitFor(() => expect(screen.getByText('Acme Motors')).toBeInTheDocument())
  })

  it('does NOT render Qora wordmark (lives in sidebar only)', () => {
    renderWithProviders(<TopBar clientId="demo-client" />)
    expect(screen.queryByText('Qora')).not.toBeInTheDocument()
  })

  it('shows the current page label as the last breadcrumb', () => {
    renderWithProviders(<TopBar clientId="demo-client" />, ['/app/demo-client/leads'])
    expect(screen.getByText('Leads')).toBeInTheDocument()
  })

  it('lead detail breadcrumb shows client > Leads (link) > "Lead" while the lead name loads', () => {
    renderWithProviders(<TopBar clientId="demo-client" />, ['/app/demo-client/leads/lead-1'])
    expect(screen.getByRole('button', { name: 'Leads' })).toBeInTheDocument()
    expect(screen.getByText('Lead')).toBeInTheDocument()
  })

  it('lead detail breadcrumb shows the real lead name once useLead resolves', async () => {
    renderWithProviders(<TopBar clientId="demo-client" />, ['/app/demo-client/leads/lead-1'])
    await waitFor(() => expect(screen.getByText('John Doe')).toBeInTheDocument())
    expect(screen.queryByText('Lead')).not.toBeInTheDocument()
  })
})

describe('PageContainer', () => {
  it('renders children content', () => {
    render(
      <PageContainer>
        <p>Page content here</p>
      </PageContainer>,
    )
    expect(screen.getByText('Page content here')).toBeInTheDocument()
  })

  it('renders as main element', () => {
    render(
      <PageContainer>
        <p>Content</p>
      </PageContainer>,
    )
    expect(screen.getByRole('main')).toBeInTheDocument()
  })
})

describe('Shell renders together without crash', () => {
  it('renders Sidebar + TopBar + PageContainer without errors', () => {
    renderWithProviders(
      <>
        <TopBar clientId="demo-client" />
        <Sidebar clientId="demo-client" />
        <PageContainer>
          <p>Dashboard placeholder</p>
        </PageContainer>
      </>,
    )
    expect(screen.getByRole('navigation')).toBeInTheDocument()
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByText('Dashboard placeholder')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// REQ-4.2: Active nav link styling
// NavLink adds aria-current="page" on the active route — behavioral assertion
// ──────────────────────────────────────────────────────────────────────────────
describe('REQ-4.2 Sidebar active navigation state', () => {
  it('Leads link is active (aria-current=page) when at /app/demo-client/leads', () => {
    renderWithProviders(<Sidebar clientId="demo-client" />, ['/app/demo-client/leads'])
    const leadsLink = screen.getByRole('link', { name: /Leads/i })
    expect(leadsLink).toHaveAttribute('aria-current', 'page')
  })

  it('Resumen link is NOT active when at /app/demo-client/leads', () => {
    renderWithProviders(<Sidebar clientId="demo-client" />, ['/app/demo-client/leads'])
    const dashboardLink = screen.getByRole('link', { name: 'Resumen' })
    expect(dashboardLink).not.toHaveAttribute('aria-current', 'page')
  })

  it('Resumen link is active (aria-current=page) when at /app/demo-client/dashboard', () => {
    renderWithProviders(<Sidebar clientId="demo-client" />, ['/app/demo-client/dashboard'])
    const dashboardLink = screen.getByRole('link', { name: 'Resumen' })
    expect(dashboardLink).toHaveAttribute('aria-current', 'page')
  })
})
