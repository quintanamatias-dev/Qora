/**
 * AppLayout — shell grid + collapsed-state persistence
 */

import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, beforeEach } from 'vitest'
import { AppLayout } from './app-layout'

function renderLayout(initialEntry = '/app/demo-client/dashboard') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/app/:clientId" element={<AppLayout />}>
            <Route path="dashboard" element={<p>Dashboard placeholder</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AppLayout', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('renders Sidebar, TopBar and the routed Outlet content inside the `.app` grid', () => {
    const { container } = renderLayout()
    expect(container.querySelector('.app')).toBeInTheDocument()
    expect(screen.getByRole('navigation')).toBeInTheDocument()
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByText('Dashboard placeholder')).toBeInTheDocument()
  })

  it('toggling the sidebar collapse button adds `.collapsed` and persists it to localStorage', () => {
    const { container } = renderLayout()
    expect(container.querySelector('.app.collapsed')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTitle('Colapsar'))

    expect(container.querySelector('.app.collapsed')).toBeInTheDocument()
    expect(window.localStorage.getItem('qora-sidebar-collapsed')).toBe('true')
  })

  it('starts collapsed when localStorage already has the collapsed flag set', () => {
    window.localStorage.setItem('qora-sidebar-collapsed', 'true')
    const { container } = renderLayout()
    expect(container.querySelector('.app.collapsed')).toBeInTheDocument()
  })
})
