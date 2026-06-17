/**
 * DimensionRollupsSection / buildCategoryRollup — Unit tests (PR 3)
 *
 * Covers the lead-level rollup contract from the call-detail-inspection-ui spec:
 *   - "Lead View Rollups Are Separate from Call Detail"
 *   - "Lead view shows objection frequency rollup" with per-call drilldown links
 *
 * Spec: openspec/changes/post-call-analysis-bi-friendly/specs/call-detail-inspection-ui/spec.md
 *
 * TDD Layer: Unit
 *   - buildCategoryRollup: pure function (counts, sorting, sessionId tracking)
 *   - DimensionRollupsSection: presentational component (rollup rows, no-data
 *     fallback, drilldown links) rendered inside a router for <Link>.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { buildCategoryRollup, DimensionRollupsSection } from './detail-page'
import type { CallSession } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Fixtures
// ──────────────────────────────────────────────────────────────────────────────

function makeSession(
  id: string,
  extracted_facts: Record<string, unknown> | null = null
): CallSession {
  return {
    id,
    client_id: 'demo-client',
    lead_id: 'lead-1',
    status: 'completed',
    started_at: '2026-01-10T10:00:00Z',
    ended_at: '2026-01-10T10:05:00Z',
    duration_seconds: 300,
    summary: null,
    outcome: null,
    closed_reason: null,
    billable_minutes: null,
    total_user_turns: null,
    total_agent_turns: null,
    extracted_facts,
  }
}

function renderSection(node: React.ReactNode) {
  const router = createMemoryRouter(
    [{ path: '*', element: <>{node}</> }],
    { initialEntries: ['/app/demo-client/leads/lead-1'] }
  )
  return render(<RouterProvider router={router} />)
}

// ──────────────────────────────────────────────────────────────────────────────
// buildCategoryRollup — pure function
// ──────────────────────────────────────────────────────────────────────────────

describe('buildCategoryRollup', () => {
  it('counts occurrences per category across calls', () => {
    const sessions = [
      makeSession('s1', { primary_objection_category: 'price' }),
      makeSession('s2', { primary_objection_category: 'price' }),
      makeSession('s3', { primary_objection_category: 'current_provider' }),
    ]

    const rollup = buildCategoryRollup(sessions, 'primary_objection_category')

    const price = rollup.find((r) => r.category === 'price')
    const provider = rollup.find((r) => r.category === 'current_provider')
    expect(price?.count).toBe(2)
    expect(provider?.count).toBe(1)
  })

  it('tracks the contributing session ids per category', () => {
    const sessions = [
      makeSession('s1', { primary_objection_category: 'price' }),
      makeSession('s2', { primary_objection_category: 'price' }),
    ]

    const rollup = buildCategoryRollup(sessions, 'primary_objection_category')
    const price = rollup.find((r) => r.category === 'price')
    expect(price?.sessionIds).toEqual(['s1', 's2'])
  })

  it('sorts categories by descending count', () => {
    const sessions = [
      makeSession('s1', { primary_pain_category: 'coverage_gap' }),
      makeSession('s2', { primary_pain_category: 'cost' }),
      makeSession('s3', { primary_pain_category: 'cost' }),
    ]

    const rollup = buildCategoryRollup(sessions, 'primary_pain_category')
    expect(rollup[0].category).toBe('cost')
    expect(rollup[0].count).toBe(2)
  })

  it('ignores sessions with no extracted_facts or missing key', () => {
    const sessions = [
      makeSession('s1', null),
      makeSession('s2', { something_else: 'x' }),
      makeSession('s3', { primary_objection_category: 'price' }),
    ]

    const rollup = buildCategoryRollup(sessions, 'primary_objection_category')
    expect(rollup).toHaveLength(1)
    expect(rollup[0]).toMatchObject({ category: 'price', count: 1 })
  })

  it('returns an empty array when no sessions carry the dimension', () => {
    const sessions = [makeSession('s1', null), makeSession('s2', {})]
    expect(buildCategoryRollup(sessions, 'primary_objection_category')).toEqual([])
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// DimensionRollupsSection — rendering
// ──────────────────────────────────────────────────────────────────────────────

describe('DimensionRollupsSection', () => {
  it('renders nothing when there are no sessions', () => {
    const { container } = renderSection(
      <DimensionRollupsSection sessions={[]} clientId="demo-client" />
    )
    expect(container.querySelector('[data-testid="dimension-rollups-section"]')).toBeNull()
  })

  it('renders objection rollup rows with counts', () => {
    const sessions = [
      makeSession('s1', { primary_objection_category: 'price' }),
      makeSession('s2', { primary_objection_category: 'price' }),
    ]
    renderSection(
      <DimensionRollupsSection sessions={sessions} clientId="demo-client" />
    )

    const rows = screen.getAllByTestId('objection-rollup-row')
    expect(rows).toHaveLength(1)
    expect(rows[0].textContent).toContain('price')
    expect(rows[0].textContent).toContain('2')
  })

  it('renders pain rollup rows independently from objections', () => {
    const sessions = [
      makeSession('s1', { primary_pain_category: 'cost' }),
    ]
    renderSection(
      <DimensionRollupsSection sessions={sessions} clientId="demo-client" />
    )

    const rows = screen.getAllByTestId('pain-rollup-row')
    expect(rows).toHaveLength(1)
    expect(rows[0].textContent).toContain('cost')
  })

  it('shows drilldown links to each contributing call detail page', () => {
    const sessions = [
      makeSession('s1', { primary_objection_category: 'price' }),
      makeSession('s2', { primary_objection_category: 'price' }),
    ]
    renderSection(
      <DimensionRollupsSection sessions={sessions} clientId="demo-client" />
    )

    const links = screen.getAllByTestId('rollup-call-link')
    expect(links.length).toBe(2)
    expect(links[0]).toHaveAttribute('href', '/app/demo-client/calls/s1')
    expect(links[1]).toHaveAttribute('href', '/app/demo-client/calls/s2')
  })

  it('falls back to a call list with links when no dimension data is present', async () => {
    const user = userEvent.setup()
    const sessions = [makeSession('s1', null), makeSession('s2', {})]
    renderSection(
      <DimensionRollupsSection sessions={sessions} clientId="demo-client" />
    )

    // Section still renders (sessions exist) but collapses by default with no
    // rollup data. Expand it to inspect the honest no-data fallback.
    expect(screen.getByTestId('dimension-rollups-section')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /dimension rollups/i }))

    // No-data fallback message + per-call links, no rollup rows.
    expect(screen.getByText(/No dimension summary data available yet/i)).toBeInTheDocument()
    expect(screen.queryByTestId('objection-rollup-row')).not.toBeInTheDocument()
    const links = screen.getAllByTestId('rollup-call-link')
    expect(links).toHaveLength(2)
    expect(links[0]).toHaveAttribute('href', '/app/demo-client/calls/s1')
  })
})
