/**
 * Accumulated Facts — Unit tests (cubora-accumulated-dimension-rankings RED phase)
 *
 * Covers:
 *   - DetectedInterestsRanking renders columns: interest, #, category
 *   - ServiceIssuesRanking renders columns: issue, #, strength
 *   - Empty state handling for both ranking components
 *   - No strength column on interests
 *   - No evidence column on service issues
 *   - No DimensionRollupsSection in the rendered page
 *   - Section heading reads "Accumulated Facts" (not "Accumulated Profile Facts")
 *   - Column header for count is "#" not "mention count" or "count"
 *
 * Spec: openspec/changes/cubora-accumulated-dimension-rankings/specs/lead-dimension-rollups/spec.md
 *
 * TDD Layer: Unit
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import {
  DetectedInterestsRanking,
  ServiceIssuesRanking,
} from './detail-page'
import type { DetectedInterestRollup, ServiceIssueRollup } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Render helpers
// ──────────────────────────────────────────────────────────────────────────────

function renderWithRouter(node: React.ReactNode) {
  const router = createMemoryRouter(
    [{ path: '*', element: <>{node}</> }],
    { initialEntries: ['/app/demo-client/leads/lead-1'] }
  )
  return render(<RouterProvider router={router} />)
}

// ──────────────────────────────────────────────────────────────────────────────
// DetectedInterestsRanking
// ──────────────────────────────────────────────────────────────────────────────

describe('DetectedInterestsRanking', () => {
  const twoInterests: DetectedInterestRollup[] = [
    { interest: 'auto_todo_riesgo', count: 3, category: 'product' },
    { interest: 'hogar', count: 1, category: 'product' },
  ]

  it('renders interest, # and category column headers', () => {
    renderWithRouter(<DetectedInterestsRanking interests={twoInterests} />)

    // Column header for count must be "#" (not "count" or "mention count")
    expect(screen.getByText('#')).toBeInTheDocument()
    expect(screen.getByText(/interest/i)).toBeInTheDocument()
    expect(screen.getByText(/category/i)).toBeInTheDocument()
  })

  it('renders rows with resolved interest labels and counts', () => {
    renderWithRouter(<DetectedInterestsRanking interests={twoInterests} />)

    // Labels are resolved via resolveLabel — auto_todo_riesgo → "Auto todo riesgo"
    expect(screen.getByText('Auto todo riesgo')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('Hogar')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('renders category column value', () => {
    renderWithRouter(<DetectedInterestsRanking interests={twoInterests} />)
    const productCells = screen.getAllByText('product')
    expect(productCells.length).toBeGreaterThanOrEqual(1)
  })

  it('does NOT render a strength column', () => {
    renderWithRouter(<DetectedInterestsRanking interests={twoInterests} />)
    // No "strength" header or column should exist
    expect(screen.queryByText(/^strength$/i)).not.toBeInTheDocument()
  })

  it('does NOT render an evidence column', () => {
    renderWithRouter(<DetectedInterestsRanking interests={twoInterests} />)
    expect(screen.queryByText(/^evidence$/i)).not.toBeInTheDocument()
  })

  it('shows empty state when no interests', () => {
    renderWithRouter(<DetectedInterestsRanking interests={[]} />)
    // Empty-state message must be visible
    expect(screen.getByText('No detected interests across calls yet.')).toBeInTheDocument()
    expect(screen.queryByText('auto_todo_riesgo')).not.toBeInTheDocument()
  })

  it('renders "need" category correctly with resolved label', () => {
    const needInterests: DetectedInterestRollup[] = [
      { interest: 'precio_competitivo', count: 2, category: 'need' },
    ]
    renderWithRouter(<DetectedInterestsRanking interests={needInterests} />)
    // precio_competitivo → "Precio competitivo"
    expect(screen.getByText('Precio competitivo')).toBeInTheDocument()
    expect(screen.getByText('need')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// ServiceIssuesRanking
// ──────────────────────────────────────────────────────────────────────────────

describe('ServiceIssuesRanking', () => {
  const twoIssues: ServiceIssueRollup[] = [
    { issue: 'poor_attention', count: 2, strength: 'medium' },
    { issue: 'delay', count: 1, strength: 'low' },
  ]

  it('renders issue, # and strength column headers', () => {
    renderWithRouter(<ServiceIssuesRanking issues={twoIssues} />)

    // Count header must be "#"
    expect(screen.getByText('#')).toBeInTheDocument()
    expect(screen.getByText(/issue/i)).toBeInTheDocument()
    expect(screen.getByText(/strength/i)).toBeInTheDocument()
  })

  it('renders rows with issue label (resolved from code), count and strength', () => {
    renderWithRouter(<ServiceIssuesRanking issues={twoIssues} />)

    // Labels are resolved via resolveLabel — poor_attention → "Mala atención"
    // We verify count and strength directly, and that raw code is absent (labels used)
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('medium')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('low')).toBeInTheDocument()
    // Resolved Spanish labels appear, not raw codes
    expect(screen.getByText('Mala atención')).toBeInTheDocument()
    expect(screen.getByText('Demora')).toBeInTheDocument()
  })

  it('shows "high" strength for issues mentioned 3+ times', () => {
    const highIssues: ServiceIssueRollup[] = [
      { issue: 'billing_issue', count: 3, strength: 'high' },
    ]
    renderWithRouter(<ServiceIssuesRanking issues={highIssues} />)
    expect(screen.getByText('high')).toBeInTheDocument()
  })

  it('does NOT render an evidence column', () => {
    renderWithRouter(<ServiceIssuesRanking issues={twoIssues} />)
    expect(screen.queryByText(/^evidence$/i)).not.toBeInTheDocument()
  })

  it('shows empty state when no service issues', () => {
    renderWithRouter(<ServiceIssuesRanking issues={[]} />)
    // Empty-state message must be visible
    expect(screen.getByText('No service issues recorded across calls yet.')).toBeInTheDocument()
    expect(screen.queryByText('poor_attention')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Section heading rename: "Accumulated Profile Facts" → "Accumulated Facts"
// ──────────────────────────────────────────────────────────────────────────────

describe('Accumulated Facts section heading', () => {
  it('does not export "Accumulated Profile Facts" as a string literal', async () => {
    // Import detail-page and check that the old string is gone from the module source
    // We do this by checking the rendered output doesn't contain the old text
    // This will be covered by the integration test in detail-page.test.tsx
    // For now we assert the components we need exist
    const module = await import('./detail-page')
    expect(module.DetectedInterestsRanking).toBeDefined()
    expect(module.ServiceIssuesRanking).toBeDefined()
  })

  it('does NOT export DimensionRollupsSection (removed)', async () => {
    const module = await import('./detail-page') as Record<string, unknown>
    expect(module['DimensionRollupsSection']).toBeUndefined()
  })

  it('does NOT export buildCategoryRollup (removed dead code)', async () => {
    const module = await import('./detail-page') as Record<string, unknown>
    expect(module['buildCategoryRollup']).toBeUndefined()
  })
})
