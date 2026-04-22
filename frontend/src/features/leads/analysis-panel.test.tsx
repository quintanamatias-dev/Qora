/**
 * AnalysisPanel — Unit tests
 *
 * Spec: sdd/qora-post-call-analysis/spec — Requirements:
 *   - Detected Interests Chips
 *   - Identified Problem Card
 *
 * TDD Layer: Unit (pure presentational component)
 * TDD: RED phase — tests written before analysis-panel.tsx exists
 *
 * Tests:
 * - Chips render for detected interests products
 * - Empty interests section is hidden
 * - Problem card renders with primary_need, pain_points, urgency
 * - Missing analysis data → graceful degradation (no crash, no UI)
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AnalysisPanel } from './analysis-panel'
import type { DetectedInterests, IdentifiedProblem } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Chips render for detected interests
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalysisPanel — detected interests chips', () => {
  it('renders a chip for each product in detected_interests.products', () => {
    const interests: DetectedInterests = {
      products: ['todo_riesgo', 'terceros_completo'],
      specific_needs: [],
      buying_signals: [],
    }
    render(<AnalysisPanel interests={interests} problem={null} />)

    expect(screen.getByText('todo_riesgo')).toBeInTheDocument()
    expect(screen.getByText('terceros_completo')).toBeInTheDocument()
  })

  it('renders chips for specific_needs when present', () => {
    const interests: DetectedInterests = {
      products: [],
      specific_needs: ['precio_competitivo', 'atencion_personalizada'],
      buying_signals: [],
    }
    render(<AnalysisPanel interests={interests} problem={null} />)

    expect(screen.getByText('precio_competitivo')).toBeInTheDocument()
    expect(screen.getByText('atencion_personalizada')).toBeInTheDocument()
  })

  it('renders chips for buying_signals when present', () => {
    const interests: DetectedInterests = {
      products: [],
      specific_needs: [],
      buying_signals: ['asked about monthly price', 'comparing quotes'],
    }
    render(<AnalysisPanel interests={interests} problem={null} />)

    expect(screen.getByText('asked about monthly price')).toBeInTheDocument()
    expect(screen.getByText('comparing quotes')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Empty interests — section hidden
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalysisPanel — empty interests hidden', () => {
  it('does not render interests section when all lists are empty', () => {
    const emptyInterests: DetectedInterests = {
      products: [],
      specific_needs: [],
      buying_signals: [],
    }
    const { queryByTestId } = render(
      <AnalysisPanel interests={emptyInterests} problem={null} />
    )
    expect(queryByTestId('analysis-interests')).not.toBeInTheDocument()
  })

  it('does not render interests section when interests is null', () => {
    const { queryByTestId } = render(
      <AnalysisPanel interests={null} problem={null} />
    )
    expect(queryByTestId('analysis-interests')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Identified problem card renders
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalysisPanel — identified problem card', () => {
  it('renders primary_need text when problem is present', () => {
    const problem: IdentifiedProblem = {
      primary_need: 'Needs comprehensive coverage for new Toyota.',
      pain_points: ['no current insurance', 'worried about accidents'],
      urgency: 'high',
    }
    render(<AnalysisPanel interests={null} problem={problem} />)

    expect(
      screen.getByText('Needs comprehensive coverage for new Toyota.')
    ).toBeInTheDocument()
  })

  it('renders each pain point in the problem card', () => {
    const problem: IdentifiedProblem = {
      primary_need: 'Needs coverage.',
      pain_points: ['no current insurance', 'worried about accidents'],
      urgency: 'medium',
    }
    render(<AnalysisPanel interests={null} problem={problem} />)

    expect(screen.getByText('no current insurance')).toBeInTheDocument()
    expect(screen.getByText('worried about accidents')).toBeInTheDocument()
  })

  it('renders urgency indicator — high urgency is visible', () => {
    const problem: IdentifiedProblem = {
      primary_need: 'Needs immediate coverage.',
      pain_points: [],
      urgency: 'high',
    }
    render(<AnalysisPanel interests={null} problem={problem} />)

    // Should show "high urgency" indicator text
    expect(screen.getByText(/high urgency/i)).toBeInTheDocument()
  })

  it('renders urgency indicator — low urgency is visible', () => {
    const problem: IdentifiedProblem = {
      primary_need: 'Needs attention eventually.',
      pain_points: [],
      urgency: 'low',
    }
    render(<AnalysisPanel interests={null} problem={problem} />)

    // Should show "low urgency" indicator text
    expect(screen.getByText(/low urgency/i)).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Graceful degradation — no problem data
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalysisPanel — graceful degradation', () => {
  it('renders nothing when both interests and problem are null', () => {
    const { container } = render(
      <AnalysisPanel interests={null} problem={null} />
    )
    // Should render empty / no content
    expect(container.firstChild).toBeNull()
  })

  it('does not throw when problem is null', () => {
    expect(() =>
      render(<AnalysisPanel interests={null} problem={null} />)
    ).not.toThrow()
  })

  it('does not render problem card when problem is null', () => {
    const { queryByTestId } = render(
      <AnalysisPanel interests={null} problem={null} />
    )
    expect(queryByTestId('analysis-problem')).not.toBeInTheDocument()
  })

  it('does not render problem card when problem is undefined', () => {
    const { queryByTestId } = render(
      <AnalysisPanel interests={null} problem={undefined} />
    )
    expect(queryByTestId('analysis-problem')).not.toBeInTheDocument()
  })
})
