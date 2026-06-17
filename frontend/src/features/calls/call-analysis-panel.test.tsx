/**
 * CallAnalysisPanel — Unit tests (PR 3: structured inspection + CRM parity)
 *
 * Covers tasks 3.5 (call-detail-inspection-ui) and 3.7 (CRM parity + correction states).
 *
 * Spec refs:
 *   - openspec/changes/post-call-analysis-bi-friendly/specs/call-detail-inspection-ui/spec.md
 *   - openspec/changes/post-call-analysis-bi-friendly/specs/crm-parity/spec.md
 *
 * TDD Layer: Unit (pure presentational component — no hooks, no routing)
 *
 * Tests cover:
 * === call-detail-inspection-ui ===
 * - Objection category is shown as a structured label/value field
 * - Objection strength and resolution_status are shown as structured fields
 * - Evidence quote is displayed inline (visible or behind toggle)
 * - Multiple objections are listed as separate structured entries
 * - Empty objections renders "no objections" empty state
 * - null analysis renders empty/no-analysis state
 *
 * === CRM parity / data corrections ===
 * - applied_to_qora=true, crm_sync_status=null → shows "Applied to Qora" label, NO CRM label
 * - applied_to_qora=true, crm_sync_status="in_sync" → shows both labels as distinct states
 * - applied_to_qora=false → shows pending/unapplied indicator (no "Applied" label)
 * - crm_sync_status=null → NO sync indicator/icon shown
 * - crm_sync_status="unknown" → NO sync indicator shown
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CallAnalysisPanel } from './call-analysis-panel'
import type { CallAnalysis } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Fixture helpers
// ──────────────────────────────────────────────────────────────────────────────

function makeAnalysis(overrides: Partial<CallAnalysis> = {}): CallAnalysis {
  return {
    session_id: 'session-test',
    summary: null,
    interest_level: null,
    classification: null,
    outcome_reason: null,
    urgency: null,
    primary_need: null,
    next_action_suggested: null,
    current_insurance: null,
    objections: null,
    products: null,
    pain_points: null,
    service_issues: null,
    profile_facts: null,
    commitment_signals: null,
    specific_needs: null,
    misc_notes: null,
    data_corrections: null,
    extra_axes_data: null,
    was_abrupt: null,
    abandonment_trigger: null,
    analysis_status: 'ok',
    analysis_error: null,
    analyzed_at: '2026-01-10T10:00:00Z',
    primary_objection_category: null,
    primary_pain_category: null,
    objections_count: null,
    pain_points_count: null,
    service_issues_count: null,
    ...overrides,
  }
}

function makeObjection(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    category: 'current_provider',
    strength: 'medium',
    resolution_status: 'unresolved',
    evidence: 'recién cambié hace 6 meses, no vale la pena',
    is_primary: true,
    ...overrides,
  }
}

function makeCorrection(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    field: 'zona',
    corrected_value: 'Palermo',
    confidence: 0.92,
    evidence: 'sí, vivo en Palermo',
    applied_to_qora: true,
    crm_sync_status: null,
    ...overrides,
  }
}

function makeServiceIssue(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    category: 'delay',
    description: 'El proveedor tardó tres semanas en responder el reclamo',
    source: 'current_provider',
    severity: 'high',
    evidence: 'me dejaron esperando tres semanas sin respuesta',
    confidence: 'high',
    ...overrides,
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: null analysis → empty state
// ──────────────────────────────────────────────────────────────────────────────

describe('CallAnalysisPanel — null analysis', () => {
  it('renders empty state when analysis is null', () => {
    render(<CallAnalysisPanel analysis={null} />)
    expect(screen.getByTestId('analysis-empty')).toBeInTheDocument()
  })

  it('shows loading state when isLoading=true', () => {
    render(<CallAnalysisPanel analysis={null} isLoading />)
    expect(screen.getByTestId('analysis-loading')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Objection displayed with normalized structured values
// ──────────────────────────────────────────────────────────────────────────────

describe('CallAnalysisPanel — structured objection rendering', () => {
  it('renders objection category as a visible structured value', () => {
    const analysis = makeAnalysis({
      objections: [makeObjection({ category: 'current_provider' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    // Category code must appear as a structured field (not buried in a prose card)
    expect(screen.getByTestId('objection-category')).toBeInTheDocument()
    expect(screen.getByTestId('objection-category').textContent).toContain('current_provider')
  })

  it('renders objection strength as a structured field', () => {
    const analysis = makeAnalysis({
      objections: [makeObjection({ strength: 'medium' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('objection-strength')).toBeInTheDocument()
    expect(screen.getByTestId('objection-strength').textContent).toContain('medium')
  })

  it('renders objection resolution_status as a structured field', () => {
    const analysis = makeAnalysis({
      objections: [makeObjection({ resolution_status: 'unresolved' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('objection-resolution')).toBeInTheDocument()
    expect(screen.getByTestId('objection-resolution').textContent).toContain('unresolved')
  })

  it('renders objection evidence quote', () => {
    const analysis = makeAnalysis({
      objections: [makeObjection({ evidence: 'recién cambié hace 6 meses' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('objection-evidence')).toBeInTheDocument()
    expect(screen.getByTestId('objection-evidence').textContent).toContain('recién cambié hace 6 meses')
  })

  it('renders multiple objections as separate structured entries', () => {
    const analysis = makeAnalysis({
      objections: [
        makeObjection({ category: 'current_provider', strength: 'medium' }),
        makeObjection({ category: 'price', strength: 'high' }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    const categories = screen.getAllByTestId('objection-category')
    expect(categories).toHaveLength(2)
    expect(categories[0].textContent).toContain('current_provider')
    expect(categories[1].textContent).toContain('price')
  })

  it('renders empty state when objections is empty array', () => {
    const analysis = makeAnalysis({ objections: [] })
    render(<CallAnalysisPanel analysis={analysis} />)

    // Should render some empty state for objections section
    expect(screen.getByTestId('call-analysis-panel')).toBeInTheDocument()
    // no objection-category testids should exist
    expect(screen.queryByTestId('objection-category')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Service issues displayed as structured normalized values + evidence
//
// Spec: call-detail-inspection-ui — "Dimensions Displayed as Structured
// Variable/Value". Service issue data carries category/source/severity/evidence,
// so the inspection view MUST surface those normalized fields, not prose only.
// ──────────────────────────────────────────────────────────────────────────────

describe('CallAnalysisPanel — structured service issue rendering', () => {
  it('renders service issue category as a structured value', () => {
    const analysis = makeAnalysis({
      service_issues: [makeServiceIssue({ category: 'delay' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('service-issue-category')).toBeInTheDocument()
    expect(screen.getByTestId('service-issue-category').textContent).toContain('delay')
  })

  it('renders service issue source and severity as structured fields', () => {
    const analysis = makeAnalysis({
      service_issues: [
        makeServiceIssue({ source: 'current_provider', severity: 'high' }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('service-issue-source').textContent).toContain('current_provider')
    expect(screen.getByTestId('service-issue-severity').textContent).toContain('high')
  })

  it('renders service issue evidence quote', () => {
    const analysis = makeAnalysis({
      service_issues: [
        makeServiceIssue({ evidence: 'me dejaron esperando tres semanas sin respuesta' }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('service-issue-evidence').textContent).toContain(
      'me dejaron esperando tres semanas sin respuesta'
    )
  })

  it('renders multiple service issues as separate structured entries', () => {
    const analysis = makeAnalysis({
      service_issues: [
        makeServiceIssue({ category: 'delay' }),
        makeServiceIssue({ category: 'billing_issue' }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    const categories = screen.getAllByTestId('service-issue-category')
    expect(categories).toHaveLength(2)
    expect(categories[0].textContent).toContain('delay')
    expect(categories[1].textContent).toContain('billing_issue')
  })

  it('falls back to the available normalized field when description is the only text', () => {
    // Honest rendering: if a legacy issue lacks structured fields, still show
    // whatever normalized value exists rather than dropping the data.
    const analysis = makeAnalysis({
      service_issues: [{ description: 'Cobro duplicado en la última factura' }],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(
      screen.getByText(/Cobro duplicado en la última factura/)
    ).toBeInTheDocument()
  })

  it('renders empty state when no service issues', () => {
    const analysis = makeAnalysis({ service_issues: [] })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.queryByTestId('service-issue-category')).not.toBeInTheDocument()
    expect(screen.getByText(/No service issues detected/i)).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Detected interests rendered as normalized values (honest)
//
// products/specific_needs arrive as flat normalized string codes at the API
// boundary (no per-item evidence exists). Render each as a labeled normalized
// value honestly — do NOT fabricate evidence/comment fields the data lacks.
// ──────────────────────────────────────────────────────────────────────────────

describe('CallAnalysisPanel — detected interest rendering', () => {
  it('renders each product/specific_need as a normalized interest value', () => {
    const analysis = makeAnalysis({
      products: ['auto_full'],
      specific_needs: ['comparando_opciones'],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    const items = screen.getAllByTestId('interest-value')
    expect(items).toHaveLength(2)
    const text = items.map((el) => el.textContent).join(' ')
    expect(text).toContain('auto_full')
    expect(text).toContain('comparando_opciones')
  })

  it('shows the source kind (product vs need) for each interest', () => {
    const analysis = makeAnalysis({
      products: ['auto_full'],
      specific_needs: ['comparando_opciones'],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByText(/product/i)).toBeInTheDocument()
    expect(screen.getByText(/need/i)).toBeInTheDocument()
  })

  it('renders empty state when no interests detected', () => {
    const analysis = makeAnalysis({ products: [], specific_needs: [] })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.queryByTestId('interest-value')).not.toBeInTheDocument()
    expect(screen.getByText(/No interests detected/i)).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Data corrections — applied_to_qora vs crm_sync_status states
// ──────────────────────────────────────────────────────────────────────────────

describe('CallAnalysisPanel — DataCorrectionsCard CRM parity states', () => {
  it('shows "Applied to Qora" label when applied_to_qora=true', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ applied_to_qora: true, crm_sync_status: null })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('correction-applied-label')).toBeInTheDocument()
  })

  it('does NOT show CRM sync label when crm_sync_status=null', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ applied_to_qora: true, crm_sync_status: null })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    // No CRM sync indicator should appear
    expect(screen.queryByTestId('correction-crm-label')).not.toBeInTheDocument()
  })

  it('does NOT show CRM sync label when crm_sync_status="unknown"', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ applied_to_qora: true, crm_sync_status: 'unknown' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.queryByTestId('correction-crm-label')).not.toBeInTheDocument()
  })

  it('shows both labels as distinct states when applied=true AND crm_sync_status=in_sync', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ applied_to_qora: true, crm_sync_status: 'in_sync' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('correction-applied-label')).toBeInTheDocument()
    expect(screen.getByTestId('correction-crm-label')).toBeInTheDocument()
  })

  it('does NOT show "Applied" label when applied_to_qora=false', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ applied_to_qora: false, crm_sync_status: null })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.queryByTestId('correction-applied-label')).not.toBeInTheDocument()
  })

  it('shows unapplied/pending indicator when applied_to_qora=false', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ applied_to_qora: false, crm_sync_status: null })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('correction-pending-label')).toBeInTheDocument()
  })

  it('shows the corrected value for each correction', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ corrected_value: 'Palermo', field: 'zona' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    // The corrected value appears as "→ Palermo" in the rendered output
    expect(screen.getByText(/Palermo/)).toBeInTheDocument()
    // The field name must also appear
    expect(screen.getByText(/zona/)).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Older / stale corrections must not imply current sync state
//
// Spec: crm-parity — "Older Calls Do Not Imply Current Sync State" and
// call-detail-inspection-ui — "Older Call Corrections Do Not Show Current Sync
// State". An older call's correction shows the historical applied fact only.
// A `stale` sync status is NOT a current-in-sync claim; a `superseded` flag MAY
// surface an honest "superseded by a later call" note.
// ──────────────────────────────────────────────────────────────────────────────

describe('CallAnalysisPanel — stale / older-call correction behavior', () => {
  it('shows the historical "Applied to Qora" fact for an older call correction', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        makeCorrection({ applied_to_qora: true, crm_sync_status: 'stale' }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('correction-applied-label')).toBeInTheDocument()
  })

  it('does NOT show a current-sync / "Verified in CRM" claim when status is stale', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        makeCorrection({ applied_to_qora: true, crm_sync_status: 'stale' }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    // No in-sync / verified label — stale is not a current sync state.
    expect(screen.queryByTestId('correction-crm-label')).not.toBeInTheDocument()
    expect(screen.queryByText(/Verified in CRM/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/in.?sync/i)).not.toBeInTheDocument()
  })

  it('renders an honest "superseded by a later call" note when superseded=true', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        makeCorrection({
          field: 'zona',
          corrected_value: 'Palermo',
          applied_to_qora: true,
          crm_sync_status: null,
          superseded: true,
        }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    const note = screen.getByTestId('correction-superseded-note')
    expect(note).toBeInTheDocument()
    expect(note.textContent).toMatch(/superseded|later call/i)
    // Still must not imply current CRM sync.
    expect(screen.queryByTestId('correction-crm-label')).not.toBeInTheDocument()
  })

  it('does NOT render a superseded note for a current (non-superseded) correction', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        makeCorrection({ applied_to_qora: true, crm_sync_status: null }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.queryByTestId('correction-superseded-note')).not.toBeInTheDocument()
  })
})
