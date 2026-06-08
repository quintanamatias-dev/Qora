/**
 * CAP-3: Layout Primitives Tests (Sidebar, TopBar, PageContainer)
 * TDD Layer: Integration — render tests
 *
 * REQ-3.5: Sidebar, TopBar, PageContainer render without errors
 * REQ-4.2: Active navigation state — active link shows aria-current="page"
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, it, expect } from 'vitest'
import { Sidebar } from './sidebar'
import { TopBar } from './top-bar'
import { PageContainer } from './page-container'

describe('Sidebar', () => {
  it('renders without crashing', () => {
    render(
      <MemoryRouter>
        <Sidebar clientId="demo-client" />
      </MemoryRouter>,
    )
    // Sidebar should have a nav role
    expect(screen.getByRole('navigation')).toBeInTheDocument()
  })

  it('renders navigation links for dashboard and leads', () => {
    render(
      <MemoryRouter>
        <Sidebar clientId="demo-client" />
      </MemoryRouter>,
    )
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Leads')).toBeInTheDocument()
  })

  it('displays clientId-based links', () => {
    render(
      <MemoryRouter>
        <Sidebar clientId="acme-motors" />
      </MemoryRouter>,
    )
    const dashboardLink = screen.getByRole('link', { name: /dashboard/i })
    expect(dashboardLink).toHaveAttribute('href', '/app/acme-motors/dashboard')
  })
})

describe('TopBar', () => {
  it('renders without crashing', () => {
    render(<TopBar clientId="demo-client" />)
    expect(screen.getByRole('banner')).toBeInTheDocument()
  })

  it('displays the clientId as context', () => {
    render(<TopBar clientId="acme-motors" />)
    expect(screen.getByText('acme-motors')).toBeInTheDocument()
  })

  it('does NOT render Qora wordmark (lives in sidebar only)', () => {
    render(<TopBar clientId="demo-client" />)
    expect(screen.queryByText('Qora')).not.toBeInTheDocument()
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
    render(
      <MemoryRouter>
        <TopBar clientId="demo-client" />
        <Sidebar clientId="demo-client" />
        <PageContainer>
          <p>Dashboard placeholder</p>
        </PageContainer>
      </MemoryRouter>,
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
    render(
      <MemoryRouter initialEntries={['/app/demo-client/leads']}>
        <Sidebar clientId="demo-client" />
      </MemoryRouter>,
    )
    const leadsLink = screen.getByRole('link', { name: 'Leads' })
    expect(leadsLink).toHaveAttribute('aria-current', 'page')
  })

  it('Dashboard link is NOT active when at /app/demo-client/leads', () => {
    render(
      <MemoryRouter initialEntries={['/app/demo-client/leads']}>
        <Sidebar clientId="demo-client" />
      </MemoryRouter>,
    )
    const dashboardLink = screen.getByRole('link', { name: 'Dashboard' })
    expect(dashboardLink).not.toHaveAttribute('aria-current', 'page')
  })

  it('Dashboard link is active (aria-current=page) when at /app/demo-client/dashboard', () => {
    render(
      <MemoryRouter initialEntries={['/app/demo-client/dashboard']}>
        <Sidebar clientId="demo-client" />
      </MemoryRouter>,
    )
    const dashboardLink = screen.getByRole('link', { name: 'Dashboard' })
    expect(dashboardLink).toHaveAttribute('aria-current', 'page')
  })
})
