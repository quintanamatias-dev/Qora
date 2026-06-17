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
    evidence: 'sí, vivo en Palermo',
    // `applied` is the per-call analysis field; `applied_to_qora` is the
    // analytics-parity alias. Both map to the same honest "Applied" state.
    applied: true,
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
// Scenario: Data corrections — light inline rows, no per-row cards/badges
//
// Latest UI feedback: each correction is a simple `field → value` row at roughly
// the field-key font size. No per-correction gray card, no per-row sync badges,
// and no heavy headline-weight value typography.
// ──────────────────────────────────────────────────────────────────────────────

describe('CallAnalysisPanel — DataCorrectionsCard inline rows', () => {
  it('shows the corrected value inline next to the field name', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ corrected_value: 'Palermo', field: 'zona' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('correction-value').textContent).toContain('Palermo')
    expect(screen.getByText(/zona/)).toBeInTheDocument()
  })

  it('renders the value at field-key weight (not a heavy headline)', () => {
    const analysis = makeAnalysis({
      data_corrections: [{ field: 'car_make', corrected_value: 'Volkswagen', applied: true }],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    const value = screen.getByTestId('correction-value')
    // Light inline typography: small size, not bold/medium headline.
    expect(value.className).toContain('text-xs')
    expect(value.className).not.toContain('text-sm')
    expect(value.className).not.toContain('font-medium')
    expect(value.className).not.toContain('font-semibold')
  })

  it('does NOT wrap each correction in its own gray card', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        makeCorrection({ field: 'zona', corrected_value: 'Palermo' }),
        makeCorrection({ field: 'car_make', corrected_value: 'Volkswagen' }),
      ],
    })
    const { container } = render(<CallAnalysisPanel analysis={analysis} />)

    const list = screen.getByTestId('corrections-list')
    const rows = list.querySelectorAll('li')
    expect(rows).toHaveLength(2)
    // No per-row card chrome (border + bg-pearl box) on the correction rows.
    rows.forEach((row) => {
      expect(row.className).not.toContain('bg-pearl')
      expect(row.className).not.toContain('rounded-md')
    })
    expect(container).toBeTruthy()
  })

  it('does NOT render per-row sync/applied badges', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ applied: true, crm_sync_status: 'in_sync' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.queryByTestId('correction-applied-label')).not.toBeInTheDocument()
    expect(screen.queryByTestId('correction-pending-label')).not.toBeInTheDocument()
    expect(screen.queryByTestId('correction-crm-label')).not.toBeInTheDocument()
    expect(screen.queryByTestId('correction-crm-unknown-label')).not.toBeInTheDocument()
    // No per-row "Applied to Qora" / "CRM unknown" text either.
    expect(screen.queryByText(/Applied to Qora/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/CRM unknown/i)).not.toBeInTheDocument()
  })

  it('does NOT render a confidence percentage', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ confidence: 1.0 })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/100%/)).not.toBeInTheDocument()
  })

  it('keeps evidence readable but compact under the row', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ evidence: 'sí, vivo en Palermo' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('correction-evidence').textContent).toContain('sí, vivo en Palermo')
  })

  it('shows the old value when present (for inspection)', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        { field: 'zona', corrected_value: 'Palermo', old_value: 'Caballito' },
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByText(/Caballito/)).toBeInTheDocument()
  })

  it('shows a rejection reason when present', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        { field: 'zona', corrected_value: 'Palermo', rejection_reason: 'Field locked in CRM' },
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('correction-rejection-reason').textContent).toContain('Field locked in CRM')
  })

  it('renders an honest superseded note when superseded=true', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        makeCorrection({ field: 'zona', corrected_value: 'Palermo', superseded: true }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    const note = screen.getByTestId('correction-superseded-note')
    expect(note.textContent).toMatch(/superseded|later call/i)
  })

  it('does NOT render a superseded note for a current correction', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ applied: true, crm_sync_status: null })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.queryByTestId('correction-superseded-note')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Section-level (batch) Qora + CRM status badges
//
// Application and CRM sync are effectively batch-level for these corrections, so
// the honest status lives ONCE in the section header — not per row. If one
// correction is out of sync, the section CRM status reflects the issue.
// ──────────────────────────────────────────────────────────────────────────────

describe('CallAnalysisPanel — section-level correction status badges', () => {
  it('renders the section-level status badges when corrections exist', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ applied: true })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('corrections-status-badges')).toBeInTheDocument()
    expect(screen.getByTestId('corrections-qora-status')).toBeInTheDocument()
    expect(screen.getByTestId('corrections-crm-status')).toBeInTheDocument()
  })

  it('shows "Qora applied" when every correction is applied', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        makeCorrection({ field: 'zona', applied: true }),
        makeCorrection({ field: 'car_make', applied: true }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('corrections-qora-status').textContent).toMatch(/applied/i)
  })

  it('shows "Qora partial" when some corrections are applied and some are not', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        makeCorrection({ field: 'zona', applied: true }),
        makeCorrection({ field: 'car_make', applied: false }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('corrections-qora-status').textContent).toMatch(/partial/i)
  })

  it('shows "Qora pending" when no corrections are applied', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ applied: false })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('corrections-qora-status').textContent).toMatch(/pending/i)
  })

  it('shows "CRM synced" only when every correction is in_sync', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        makeCorrection({ field: 'zona', applied: true, crm_sync_status: 'in_sync' }),
        makeCorrection({ field: 'car_make', applied: true, crm_sync_status: 'in_sync' }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('corrections-crm-status').textContent).toMatch(/synced/i)
  })

  it('shows "CRM out of sync" if any correction is out_of_sync (batch reflects the issue)', () => {
    const analysis = makeAnalysis({
      data_corrections: [
        makeCorrection({ field: 'zona', applied: true, crm_sync_status: 'in_sync' }),
        makeCorrection({ field: 'car_make', applied: true, crm_sync_status: 'out_of_sync' }),
      ],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('corrections-crm-status').textContent).toMatch(/out of sync/i)
  })

  it('shows an honest "CRM unknown" when sync status is null/unknown/stale (no fake sync)', () => {
    const analysis = makeAnalysis({
      data_corrections: [makeCorrection({ applied: true, crm_sync_status: 'stale' })],
    })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.getByTestId('corrections-crm-status').textContent).toMatch(/unknown/i)
    // Never a fake current-sync claim from a stale status.
    expect(screen.queryByText(/synced/i)).not.toBeInTheDocument()
  })

  it('does NOT render status badges when there are no corrections', () => {
    const analysis = makeAnalysis({ data_corrections: [] })
    render(<CallAnalysisPanel analysis={analysis} />)

    expect(screen.queryByTestId('corrections-status-badges')).not.toBeInTheDocument()
  })
})
