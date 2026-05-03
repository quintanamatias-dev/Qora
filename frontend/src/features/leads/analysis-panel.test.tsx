/**
 * AnalysisPanel — Unit tests (qora-problem update, Issue #52)
 *
 * Spec: sdd/qora-problem/spec — Requirements:
 *   - ProblemAxis / PainPoint rendering
 *   - Detected Interests Chips (unchanged)
 *   - Graceful degradation
 *
 * TDD Layer: Unit (pure presentational component)
 *
 * Tests cover:
 * - Chips render for detected interests products (unchanged)
 * - Empty interests section is hidden
 * - Pain point card renders with category, description, evidence, urgency
 * - Primary pain point has primary indicator
 * - Non-primary pain points have no primary indicator
 * - Empty pain_points renders gracefully (no crash)
 * - null/undefined problem renders gracefully
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AnalysisPanel } from './analysis-panel'
import type { DetectedInterests, ProblemAxis, PainPoint } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Test fixture helpers
// ──────────────────────────────────────────────────────────────────────────────

function makePainPoint(overrides: Partial<PainPoint> = {}): PainPoint {
  return {
    category: 'cost',
    description: 'El lead quiere pagar menos por su seguro',
    evidence: 'Quiero pagar menos, el seguro actual es muy caro',
    urgency: 'medium',
    confidence: 'high',
    is_primary: false,
    ...overrides,
  }
}

function makeProblemAxis(pain_points: PainPoint[] = []): ProblemAxis {
  return { pain_points }
}

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Chips render for detected interests (unchanged from prior tests)
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
// Scenario: PainPoint card renders (qora-problem new schema)
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalysisPanel — PainPoint rendering', () => {
  it('renders pain point description', () => {
    const problem = makeProblemAxis([
      makePainPoint({ description: 'El lead quiere cobertura más amplia', is_primary: true }),
    ])
    render(<AnalysisPanel interests={null} problem={problem} />)

    expect(screen.getByText('El lead quiere cobertura más amplia')).toBeInTheDocument()
  })

  it('renders category badge for each pain point', () => {
    const problem = makeProblemAxis([
      makePainPoint({ category: 'cost' }),
    ])
    render(<AnalysisPanel interests={null} problem={problem} />)

    // Category badge should be visible
    const badge = screen.getByTestId('pain-point-category')
    expect(badge).toBeInTheDocument()
  })

  it('renders evidence quote for each pain point', () => {
    const problem = makeProblemAxis([
      makePainPoint({ evidence: 'El seguro actual me está costando mucho' }),
    ])
    render(<AnalysisPanel interests={null} problem={problem} />)

    expect(screen.getByTestId('pain-point-evidence')).toBeInTheDocument()
    expect(screen.getByText(/El seguro actual me está costando mucho/)).toBeInTheDocument()
  })

  it('renders urgency for each pain point', () => {
    const problem = makeProblemAxis([
      makePainPoint({ urgency: 'high' }),
    ])
    render(<AnalysisPanel interests={null} problem={problem} />)

    expect(screen.getByTestId('pain-point-urgency')).toBeInTheDocument()
  })

  it('renders multiple pain points', () => {
    const problem = makeProblemAxis([
      makePainPoint({ category: 'cost', description: 'Costo elevado', is_primary: true }),
      makePainPoint({ category: 'bad_experience', description: 'Mala experiencia pasada' }),
    ])
    render(<AnalysisPanel interests={null} problem={problem} />)

    const descriptions = screen.getAllByTestId('pain-point-description')
    expect(descriptions).toHaveLength(2)
    expect(screen.getByText('Costo elevado')).toBeInTheDocument()
    expect(screen.getByText('Mala experiencia pasada')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Primary indicator
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalysisPanel — primary pain indicator', () => {
  it('shows primary indicator when is_primary=true', () => {
    const problem = makeProblemAxis([
      makePainPoint({ is_primary: true }),
    ])
    render(<AnalysisPanel interests={null} problem={problem} />)

    expect(screen.getByTestId('pain-point-primary')).toBeInTheDocument()
  })

  it('does NOT show primary indicator when is_primary=false', () => {
    const problem = makeProblemAxis([
      makePainPoint({ is_primary: false }),
    ])
    render(<AnalysisPanel interests={null} problem={problem} />)

    expect(screen.queryByTestId('pain-point-primary')).not.toBeInTheDocument()
  })

  it('shows primary indicator for primary pain, not for non-primary', () => {
    const problem = makeProblemAxis([
      makePainPoint({ category: 'cost', description: 'Primary one', is_primary: true }),
      makePainPoint({ category: 'bad_experience', description: 'Non-primary', is_primary: false }),
    ])
    render(<AnalysisPanel interests={null} problem={problem} />)

    const primaryBadges = screen.getAllByTestId('pain-point-primary')
    expect(primaryBadges).toHaveLength(1)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Graceful degradation — empty / null problem
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalysisPanel — graceful degradation', () => {
  it('renders nothing when both interests and problem are null', () => {
    const { container } = render(
      <AnalysisPanel interests={null} problem={null} />
    )
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

  it('does not render problem card when pain_points is empty', () => {
    const problem = makeProblemAxis([])  // empty pain_points
    const { queryByTestId } = render(
      <AnalysisPanel interests={null} problem={problem} />
    )
    expect(queryByTestId('analysis-problem')).not.toBeInTheDocument()
  })

  it('renders problem card when pain_points has items', () => {
    const problem = makeProblemAxis([makePainPoint()])
    const { queryByTestId } = render(
      <AnalysisPanel interests={null} problem={problem} />
    )
    expect(queryByTestId('analysis-problem')).toBeInTheDocument()
  })
})
