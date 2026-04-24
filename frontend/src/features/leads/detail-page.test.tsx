/**
 * LeadDetailPage — Integration tests
 *
 * Spec: sdd/qora-basic-crm/spec — Requirement: Lead Header Card, Call History List,
 *       Loading and Error States for LeadDetailPage
 * Design: Container with useLead + useCallSessions, expandedSessionId state,
 *         TranscriptViewer expands inline on session click.
 *
 * TDD Layer: Integration (RTL + MSW)
 * TDD: RED phase — tests written before implementation
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider, Outlet } from 'react-router'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { LeadDetailPage } from './detail-page'

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function createTestClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  })
}

function renderDetailPage(clientId = 'demo-client', leadId = 'lead-1') {
  const qc = createTestClient()
  const router = createMemoryRouter(
    [
      {
        path: '/app/:clientId',
        element: <Outlet />,
        children: [
          { path: 'leads', element: <div>Leads List</div> },
          { path: 'leads/:leadId', element: <LeadDetailPage /> },
        ],
      },
    ],
    { initialEntries: [`/app/${clientId}/leads/${leadId}`] }
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return { qc }
}

// ──────────────────────────────────────────────────────────────────────────────
// Lead header card
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — lead header', () => {
  it('renders lead name in header', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    )
  })

  it('renders lead phone in header', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText('+1-555-0100')).toBeInTheDocument()
    )
  })

  it('renders status badge in header', async () => {
    renderDetailPage()
    await waitFor(() => {
      // lead-1 has status "new" — badge should be present
      expect(screen.getByText(/new/i)).toBeInTheDocument()
    })
  })

  it('renders interest level when present', async () => {
    renderDetailPage()
    // lead-1 has interest_level: 75
    await waitFor(() =>
      expect(screen.getByText('75%')).toBeInTheDocument()
    )
  })

  it('renders summary_last_call when present', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText('Client interested in full coverage')).toBeInTheDocument()
    )
  })

  it('renders "—" for null interest level (lead-2)', async () => {
    renderDetailPage('demo-client', 'lead-2')
    await waitFor(() => {
      const dashes = screen.getAllByText('—')
      expect(dashes.length).toBeGreaterThan(0)
    })
  })

  it('renders "No summary yet" when summary_last_call is null', async () => {
    renderDetailPage('demo-client', 'lead-2')
    await waitFor(() =>
      expect(screen.getByText('No summary yet')).toBeInTheDocument()
    )
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Call history list
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — call history list', () => {
  it('renders call history section heading', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText(/call history/i)).toBeInTheDocument()
    )
  })

  it('renders call session items from fixture', async () => {
    renderDetailPage()
    await waitFor(() => {
      const items = screen.getAllByTestId('call-history-item')
      expect(items).toHaveLength(2)
    })
  })

  it('shows "No calls yet" when sessions list is empty', async () => {
    server.use(
      http.get('/api/v1/calls', () => HttpResponse.json([]))
    )

    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText('No calls yet')).toBeInTheDocument()
    )
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Transcript accordion — click to expand
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — transcript accordion', () => {
  it('clicking a call item expands the transcript viewer', async () => {
    const user = userEvent.setup()
    renderDetailPage()

    // Wait for call history items to appear
    await waitFor(() => {
      expect(screen.getAllByTestId('call-history-item')).toHaveLength(2)
    })

    // Click first call item
    const items = screen.getAllByTestId('call-history-item')
    await user.click(items[0])

    // TranscriptViewer should appear (loading indicator or turns)
    await waitFor(() => {
      const transcriptEl =
        screen.queryByTestId('transcript-loading') ||
        screen.queryAllByTestId('transcript-turn').length > 0 ||
        screen.queryByText('No transcript available')
      expect(transcriptEl).toBeTruthy()
    })
  })

  it('clicking a call item again collapses the transcript (toggle)', async () => {
    const user = userEvent.setup()
    renderDetailPage()

    await waitFor(() => {
      expect(screen.getAllByTestId('call-history-item')).toHaveLength(2)
    })

    const items = screen.getAllByTestId('call-history-item')

    // Click to expand
    await user.click(items[0])

    // Wait for transcript to appear
    await waitFor(() => {
      const el =
        screen.queryByTestId('transcript-loading') ||
        screen.queryByTestId('transcript-viewer')
      return el !== null
    })

    // Click again to collapse
    await user.click(items[0])

    // Transcript viewer should be gone
    await waitFor(() => {
      expect(screen.queryByTestId('transcript-viewer')).not.toBeInTheDocument()
      expect(screen.queryByTestId('transcript-loading')).not.toBeInTheDocument()
    })
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Loading states
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — loading state', () => {
  it('shows page-level skeleton while lead is loading', async () => {
    server.use(
      http.get('/api/v1/leads/:leadId', async () => {
        await new Promise(r => setTimeout(r, 200))
        return HttpResponse.json({
          id: 'lead-1',
          client_id: 'demo-client',
          name: 'John Doe',
          phone: '+1-555-0100',
          status: 'new',
          call_count: 0,
          last_called_at: null,
          car_make: null,
          car_model: null,
          car_year: null,
          current_insurance: null,
          notes: null,
          created_at: null,
          updated_at: null,
          summary_last_call: null,
          objections_heard: null,
          interest_level: null,
          extracted_facts: null,
          do_not_call: false,
          next_action: null,
          next_action_at: null,
          next_scheduled_call_at: null,
        })
      })
    )

    renderDetailPage()
    expect(screen.getByTestId('lead-loading')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Error states
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — error state', () => {
  it('shows error message when lead fetch fails', async () => {
    server.use(
      http.get('/api/v1/leads/:leadId', () =>
        HttpResponse.json({ detail: 'Not found' }, { status: 404 })
      )
    )

    renderDetailPage()
    await waitFor(
      () => expect(screen.getByTestId('lead-error')).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })

  it('shows call history error when sessions fetch fails', async () => {
    server.use(
      http.get('/api/v1/calls', () =>
        HttpResponse.json({ detail: 'Internal server error' }, { status: 500 })
      )
    )

    renderDetailPage()

    // Lead should still load and render the header
    await waitFor(() =>
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    )

    // Sessions error should show an error message in the call history section
    await waitFor(
      () => expect(screen.getByTestId('sessions-error')).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })
})
