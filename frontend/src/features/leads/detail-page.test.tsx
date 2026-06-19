/**
 * LeadDetailPage — Integration tests (Phase A UI Clarity Update)
 *
 * Covers:
 *   - Two-column layout (data-testid="detail-two-column")
 *   - Quote Readiness Fields section (renamed from "Quote Fields")
 *   - current_insurance as CRM-provided data (not a required target)
 *   - Parsed profile fact rendering (Category / Fact / Evidence / Confidence)
 *   - Post-call dimension source label on profile facts
 *   - Zona mismatch warning when lifestyle fact looks like location + zona not set
 *   - Call history still in right column
 *   - Context preview still lazy-loads
 *   - Loading and Error States for LeadDetailPage
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
          { path: 'calls/:sessionId', element: <div>Call Detail Page</div> },
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
  it('renders lead name in page heading', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /John Doe/i })).toBeInTheDocument()
    )
  })

  it('renders lead phone in header', async () => {
    renderDetailPage()
    await waitFor(() => {
      const phoneElements = screen.getAllByText('+1-555-0100')
      expect(phoneElements.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders status badge in header', async () => {
    renderDetailPage()
    await waitFor(() => {
      const badge = document.querySelector('[data-status="new"]')
      expect(badge).toBeInTheDocument()
    })
  })

  it('renders interest level when present', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText('75%')).toBeInTheDocument()
    )
  })

  it('renders summary_last_call when present', async () => {
    renderDetailPage()
    await waitFor(() => {
      const summaryEl = screen.getByText(/Client interested in full coverage/i)
      expect(summaryEl).toBeInTheDocument()
    })
  })

  it('shows dash placeholders for null fields (lead-2)', async () => {
    renderDetailPage('demo-client', 'lead-2')
    await waitFor(() => {
      const dashes = screen.getAllByText('—')
      expect(dashes.length).toBeGreaterThan(0)
    })
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Two-column layout
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — two-column layout', () => {
  it('renders the two-column container', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /John Doe/i })).toBeInTheDocument()
    )
    expect(document.querySelector('[data-testid="detail-two-column"]')).toBeInTheDocument()
  })

  it('renders Call History section (right column present)', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText(/call history/i)).toBeInTheDocument()
    )
  })

  it('renders Next-Call Context Preview section (right column present)', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText(/next-call context preview/i)).toBeInTheDocument()
    )
  })

  it('applies the responsive two-column grid template at xl', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /John Doe/i })).toBeInTheDocument()
    )
    const grid = document.querySelector('[data-testid="detail-two-column"]')
    expect(grid).toHaveClass('xl:grid-cols-[1fr_minmax(0,560px)]')
  })

  it('keeps the right column sticky below the header at xl', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /John Doe/i })).toBeInTheDocument()
    )
    const grid = document.querySelector('[data-testid="detail-two-column"]')
    const rightColumn = grid?.children[1]
    expect(rightColumn).toHaveClass('xl:sticky', 'xl:top-24')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Quote Readiness Fields — renamed section + CRM-provided data separation
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — Quote Readiness Fields section', () => {
  it('renders section with new name "Quote Readiness Fields"', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText('Quote Readiness Fields')).toBeInTheDocument()
    )
  })

  it('shows "Fields for Quoting" subsection header for required fields', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText('Fields for Quoting')).toBeInTheDocument()
    )
  })

  it('shows "Additional CRM-provided data" subsection for optional fields like current_insurance', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText('Additional CRM-provided data')).toBeInTheDocument()
    )
  })

  it('labels current_insurance as "crm-provided" (not "required")', async () => {
    renderDetailPage()
    await waitFor(() => {
      // The crm-provided label should appear for current_insurance
      const crmLabels = screen.getAllByText('crm-provided')
      expect(crmLabels.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders quote field labels and field types from metadata', async () => {
    renderDetailPage()
    await waitFor(() => expect(screen.getByText('Car Make')).toBeInTheDocument())
    expect(screen.getByText('Car Model')).toBeInTheDocument()
    expect(screen.getByText('Current Insurance')).toBeInTheDocument()
    expect(screen.getAllByText('string').length).toBeGreaterThanOrEqual(3)
  })

  it('renders filled required field with its current value', async () => {
    renderDetailPage()
    await waitFor(() => expect(screen.getByText('Toyota')).toBeInTheDocument())
    // current_insurance value is shown as CRM-provided context
    expect(screen.getByText('State Farm')).toBeInTheDocument()
  })

  it('marks missing quote-ready fields with "not set" and a required badge', async () => {
    renderDetailPage()
    // car_model and zona are quote-ready but unfilled → both show "not set"
    await waitFor(() => expect(screen.getAllByText('not set').length).toBeGreaterThanOrEqual(1))
    // "required" badge appears only for quote-ready fields (car_make + car_model + zona),
    // never for current_insurance (CRM-provided).
    expect(screen.getAllByText('required').length).toBeGreaterThanOrEqual(2)
  })

  it('shows readiness-fill ratio badge driven by quote_ready_fields', async () => {
    renderDetailPage()
    // 1 of 3 quote-ready fields filled (car_make filled; car_model + zona missing).
    // Ratio is counted from in_quote_ready_fields, NOT the legacy required flag.
    await waitFor(() => expect(screen.getByText('1/3 required')).toBeInTheDocument())
  })

  it('renders tooltip/context note about agent not collecting CRM-provided fields', async () => {
    renderDetailPage()
    await waitFor(() => {
      const tooltip = document.querySelector('[data-testid="crm-provided-tooltip"]')
      expect(tooltip).toBeInTheDocument()
    })
  })

  it('renders empty state when no custom fields (lead-2)', async () => {
    renderDetailPage('demo-client', 'lead-2')
    await waitFor(() => {
      expect(screen.getByText('Quote Readiness Fields')).toBeInTheDocument()
    })
  })

  it('forwards data-testid to the Section root (quote-readiness-section)', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(document.querySelector('[data-testid="quote-readiness-section"]')).toBeInTheDocument()
    )
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Profile facts — structured parsing (Category / Fact / Evidence / Confidence)
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — parsed profile facts', () => {
  it('renders profile fact items for lead-1', async () => {
    renderDetailPage()
    await waitFor(() => {
      const factItems = screen.getAllByTestId('profile-fact-item')
      expect(factItems.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('shows structured fact text from parsed JSON', async () => {
    renderDetailPage()
    await waitFor(() => {
      // The fact text appears in fact-text testid (may also appear in mismatch warning)
      const factTexts = screen.getAllByTestId('fact-text')
      const lifestyleFact = factTexts.find(el =>
        el.textContent?.includes('Vicente López')
      )
      expect(lifestyleFact).toBeInTheDocument()
    })
  })

  it('shows fact evidence quote from parsed JSON', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText(/Mencionó que vive en Vicente López/i)).toBeInTheDocument()
    )
  })

  it('shows fact category badge', async () => {
    renderDetailPage()
    await waitFor(() => {
      const categories = screen.getAllByTestId('fact-category')
      expect(categories.length).toBeGreaterThanOrEqual(1)
      // lifestyle category should appear
      const lifestyleCategory = categories.find(el => el.textContent?.toLowerCase().includes('lifestyle'))
      expect(lifestyleCategory).toBeInTheDocument()
    })
  })

  it('shows confidence level for parsed fact', async () => {
    renderDetailPage()
    await waitFor(() => {
      const confidenceEls = screen.getAllByTestId('fact-confidence')
      expect(confidenceEls.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('shows dimension source label at group header level (not per item)', async () => {
    renderDetailPage()
    await waitFor(() => {
      // Source label is now ONE element at group header, not per-item badges
      const dimensionLabels = screen.getAllByTestId('fact-dimension-source')
      expect(dimensionLabels.length).toBe(1)
      expect(dimensionLabels[0].textContent).toMatch(/profile_facts/)
    })
  })

  it('shows "source: post-call analysis · profile_facts" at group header', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText(/source: post-call analysis · profile_facts/i)).toBeInTheDocument()
    )
  })

  it('does not show per-item source badges inside fact items', async () => {
    renderDetailPage()
    await waitFor(() => {
      // After source moved to group header, individual fact items have no source badge
      const factItems = screen.getAllByTestId('profile-fact-item')
      expect(factItems.length).toBeGreaterThanOrEqual(1)
    })
    // The single source label is at the group level only
    const dimensionLabels = screen.getAllByTestId('fact-dimension-source')
    expect(dimensionLabels.length).toBe(1)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Zona mismatch warning
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — zona mismatch warning', () => {
  it('shows zona mismatch warning when lifestyle fact looks like location and zona not set', async () => {
    // lead-1 fixture has "Lives in Vicente López" (lifestyle) + no zona quote field
    renderDetailPage()
    await waitFor(() => {
      expect(document.querySelector('[data-testid="zona-mismatch-warning"]')).toBeInTheDocument()
    })
  })

  it('mismatch warning mentions structured zona field', async () => {
    renderDetailPage()
    await waitFor(() => {
      const warning = document.querySelector('[data-testid="zona-mismatch-warning"]')
      expect(warning?.textContent).toMatch(/zona/)
    })
  })

  it('mismatch warning frames issue as data consistency gap, not agent error', async () => {
    renderDetailPage()
    await waitFor(() => {
      const warning = document.querySelector('[data-testid="zona-mismatch-warning"]')
      // Copy should frame this as a data-capture problem, not a UI or agent bug
      expect(warning?.textContent).toMatch(/data consistency/i)
      expect(warning?.textContent).toMatch(/data.capture gap|post-call corrections/i)
    })
  })

  it('does not show mismatch warning for lead-2 (no profile facts)', async () => {
    renderDetailPage('demo-client', 'lead-2')
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /Jane Smith/i })).toBeInTheDocument()
    )
    expect(document.querySelector('[data-testid="zona-mismatch-warning"]')).not.toBeInTheDocument()
  })

  it('does not show mismatch warning when client has no zona field configured (lead-3)', async () => {
    // lead-3 has a location-like profile fact but its crm.yaml has no `zona`
    // quote field — there is nothing to be "not set", so no warning.
    renderDetailPage('no-zona-client', 'lead-3')
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /No Zona Client/i })).toBeInTheDocument()
    )
    expect(document.querySelector('[data-testid="zona-mismatch-warning"]')).not.toBeInTheDocument()
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

  it('renders "View detail" link for each call session', async () => {
    renderDetailPage()
    await waitFor(() => {
      const detailLinks = screen.getAllByTestId('call-detail-link')
      expect(detailLinks.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('"View detail" points at the call detail route', async () => {
    renderDetailPage()
    await waitFor(() => {
      expect(screen.getAllByTestId('call-detail-link').length).toBeGreaterThanOrEqual(1)
    })
    const detailLink = screen.getAllByTestId('call-detail-link')[0]
    expect(detailLink).toHaveAttribute(
      'href',
      expect.stringMatching(/^\/app\/demo-client\/calls\/.+/)
    )
  })

  it('clicking "View detail" navigates to the call page instead of expanding the transcript', async () => {
    const user = userEvent.setup()
    renderDetailPage()

    await waitFor(() => {
      expect(screen.getAllByTestId('call-detail-link')).toHaveLength(2)
    })

    const detailLinks = screen.getAllByTestId('call-detail-link')
    // Click the detail link — should navigate to the call detail route,
    // not reveal the transcript viewer inline.
    await user.click(detailLinks[0])

    await waitFor(() =>
      expect(screen.getByText('Call Detail Page')).toBeInTheDocument()
    )
    expect(screen.queryByTestId('transcript-viewer')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Transcript accordion — click to expand
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — transcript accordion', () => {
  it('clicking a call item expands the transcript viewer', async () => {
    const user = userEvent.setup()
    renderDetailPage()

    await waitFor(() => {
      expect(screen.getAllByTestId('call-history-item')).toHaveLength(2)
    })

    const items = screen.getAllByTestId('call-history-item')
    await user.click(items[0])

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

    await user.click(items[0])

    await waitFor(() => {
      const el =
        screen.queryByTestId('transcript-loading') ||
        screen.queryByTestId('transcript-viewer')
      return el !== null
    })

    await user.click(items[0])

    await waitFor(() => {
      expect(screen.queryByTestId('transcript-viewer')).not.toBeInTheDocument()
      expect(screen.queryByTestId('transcript-loading')).not.toBeInTheDocument()
    })
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Next-call context preview (Section F) — lazy load on click
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — context preview', () => {
  async function openAndLoadPreview(user: ReturnType<typeof userEvent.setup>) {
    const header = await screen.findByRole('button', { name: /next-call context preview/i })
    await user.click(header)
    const trigger = await screen.findByRole('button', { name: /load context preview/i })
    await user.click(trigger)
  }

  it('does not fetch the preview until "Load context preview" is clicked', async () => {
    const user = userEvent.setup()
    renderDetailPage()

    const header = await screen.findByRole('button', { name: /next-call context preview/i })
    await user.click(header)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /load context preview/i })).toBeInTheDocument()
    )
    expect(screen.queryByText('Lead Profile')).not.toBeInTheDocument()
  })

  it('loads and renders literal context blocks after clicking the trigger', async () => {
    const user = userEvent.setup()
    renderDetailPage()

    await openAndLoadPreview(user)

    await waitFor(() =>
      expect(screen.getByText(/present, not shown/i)).toBeInTheDocument()
    )

    expect(screen.getByText('Lead Profile')).toBeInTheDocument()
    expect(screen.getByText(/Auto: Toyota Camry 2022/)).toBeInTheDocument()
    expect(screen.getAllByText('Call History').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText(/Solicitó cotización para el Corolla/)).toBeInTheDocument()
    expect(screen.getByText('Misc Notes')).toBeInTheDocument()
    expect(screen.getByText('Prefers afternoon callbacks.')).toBeInTheDocument()
    expect(screen.getByText('Skills Index')).toBeInTheDocument()

    expect(screen.getByText('get_lead_details')).toBeInTheDocument()
    expect(screen.getByText('capture_data')).toBeInTheDocument()

    expect(screen.getByText('Call #3')).toBeInTheDocument()
    expect(screen.getByText('Returning caller')).toBeInTheDocument()
  })

  it('shows empty-state rows for sparse context (lead-2)', async () => {
    const user = userEvent.setup()
    renderDetailPage('demo-client', 'lead-2')

    await openAndLoadPreview(user)

    await waitFor(() =>
      expect(screen.getByText(/Lead profile: empty/i)).toBeInTheDocument()
    )
    expect(screen.getByText(/Call history: none stored/i)).toBeInTheDocument()
    expect(screen.getByText(/Misc notes: none/i)).toBeInTheDocument()
    expect(screen.getByText(/Skills index: no registry configured/i)).toBeInTheDocument()
    expect(screen.getByText('First call')).toBeInTheDocument()
  })

  it('shows an error message when the preview request fails', async () => {
    server.use(
      http.get('/api/v1/leads/:leadId/context-preview', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 })
      )
    )

    const user = userEvent.setup()
    renderDetailPage()

    await openAndLoadPreview(user)

    await waitFor(
      () => expect(screen.getByText(/Failed to load context preview/i)).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Accumulated Facts section — cubora-accumulated-dimension-rankings
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — Accumulated Facts section', () => {
  it('shows "Accumulated Facts" section heading (not "Accumulated Profile Facts")', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText('Accumulated Facts')).toBeInTheDocument()
    )
    // Old label must be gone
    expect(screen.queryByText('Accumulated Profile Facts')).not.toBeInTheDocument()
  })

  it('renders Detected Interests sub-section heading', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByText(/Detected Interests/i)).toBeInTheDocument()
    )
  })

  it('renders Service Issues sub-section heading', async () => {
    renderDetailPage()
    await waitFor(() => {
      // "Service Issues" appears as a sub-section header (may also appear in subtitle)
      const els = screen.getAllByText(/Service Issues/i)
      expect(els.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders Profile sub-section inside Accumulated Facts', async () => {
    renderDetailPage()
    await waitFor(() => {
      // "Profile" appears as a sub-section header inside Accumulated Facts
      const els = screen.getAllByText(/^Profile$/i)
      expect(els.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('does NOT render a standalone Dimension Rollups section', async () => {
    renderDetailPage()
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /John Doe/i })).toBeInTheDocument()
    )
    expect(screen.queryByText('Dimension Rollups')).not.toBeInTheDocument()
  })

  it('surfaces a rollups error instead of empty rankings when /dimension-rollups fails', async () => {
    server.use(
      http.get('/api/v1/leads/:leadId/dimension-rollups', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 })
      )
    )

    renderDetailPage()

    await waitFor(
      () => expect(screen.getByTestId('rollups-error')).toBeInTheDocument(),
      { timeout: 5000 }
    )

    // A failed query must NOT masquerade as "no interests / no service issues".
    expect(screen.queryByText('No detected interests across calls yet.')).not.toBeInTheDocument()
    expect(screen.queryByText('No service issues recorded across calls yet.')).not.toBeInTheDocument()
  })

  it('keeps empty-state messages (not an error) when rollups load successfully but are empty', async () => {
    // lead-2 fixture returns successful, fully-empty rollup arrays. Its
    // Accumulated Facts section is collapsed by default (no profile/summary),
    // so expand it before asserting the ranking children.
    const user = userEvent.setup()
    renderDetailPage('demo-client', 'lead-2')

    const header = await screen.findByRole('button', { name: /Accumulated Facts/i })
    await user.click(header)

    await waitFor(() =>
      expect(screen.getByText('No detected interests across calls yet.')).toBeInTheDocument()
    )
    expect(screen.getByText('No service issues recorded across calls yet.')).toBeInTheDocument()
    expect(screen.queryByTestId('rollups-error')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rollups-loading')).not.toBeInTheDocument()
  })

  it('shows a loading state (not empty rankings) while /dimension-rollups is in flight', async () => {
    // Delay the rollups response so the query is observably pending. During
    // this window the component must NOT render "No detected interests…" —
    // that would falsely claim emptiness while the request (or a retry) is
    // still resolving.
    server.use(
      http.get('/api/v1/leads/:leadId/dimension-rollups', async () => {
        await new Promise(r => setTimeout(r, 200))
        return HttpResponse.json({
          detected_interests: [],
          service_issues: [],
          objections: [],
          pain_points: [],
        })
      })
    )

    renderDetailPage()

    // Loading indicator appears and empty-state is suppressed while pending.
    await waitFor(() =>
      expect(screen.getByTestId('rollups-loading')).toBeInTheDocument()
    )
    expect(screen.queryByText('No detected interests across calls yet.')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rollups-error')).not.toBeInTheDocument()

    // Once resolved, the loading indicator goes away and the empty state shows.
    await waitFor(
      () => expect(screen.queryByTestId('rollups-loading')).not.toBeInTheDocument(),
      { timeout: 5000 }
    )
    expect(screen.getByText('No detected interests across calls yet.')).toBeInTheDocument()
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

    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1, name: /John Doe/i })).toBeInTheDocument()
    )

    await waitFor(
      () => {
        const errorEl = screen.getByText(/Unable to load call history/i)
        expect(errorEl).toBeInTheDocument()
      },
      { timeout: 5000 }
    )
  })
})
