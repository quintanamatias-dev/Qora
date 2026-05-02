/**
 * CallOutcomeBadge — Unit tests
 *
 * Spec: sdd/qora-outcome/spec — Requirement: CallOutcomeBadge Component
 *
 * TDD Layer: Unit (pure presentational component, no API calls)
 * TDD: Updated for qora-outcome (Issue #50) — 11 classifications, no engagement
 *
 * Tests:
 * - Renders correct label for all 11 classification values
 * - Does NOT render when call_outcome is null/undefined
 * - No engagement indicator in DOM (engagement_quality removed)
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CallOutcomeBadge } from './call-outcome-badge'
import type { CallOutcome } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Badge renders for all 11 classifications (qora-outcome spec)
// ──────────────────────────────────────────────────────────────────────────────

describe('CallOutcomeBadge — 11 classifications (qora-outcome)', () => {
  it('renders label for "no_answer"', () => {
    const outcome: CallOutcome = {
      classification: 'no_answer',
      reason: 'No response.',
      confidence: 'low',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/no.answer/i)).toBeInTheDocument()
  })

  it('renders label for "busy"', () => {
    const outcome: CallOutcome = {
      classification: 'busy',
      reason: 'Lead was driving.',
      confidence: 'medium',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/busy/i)).toBeInTheDocument()
  })

  it('renders label for "callback_requested"', () => {
    const outcome: CallOutcome = {
      classification: 'callback_requested',
      reason: 'Lead asked to be called back.',
      confidence: 'high',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/callback/i)).toBeInTheDocument()
  })

  it('renders label for "completed_positive"', () => {
    const outcome: CallOutcome = {
      classification: 'completed_positive',
      reason: 'Lead purchased the policy.',
      confidence: 'high',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/positive/i)).toBeInTheDocument()
  })

  it('renders label for "completed_neutral"', () => {
    const outcome: CallOutcome = {
      classification: 'completed_neutral',
      reason: 'Call completed without commitment.',
      confidence: 'medium',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/neutral/i)).toBeInTheDocument()
  })

  it('renders label for "completed_negative"', () => {
    const outcome: CallOutcome = {
      classification: 'completed_negative',
      reason: 'Lead clearly declined.',
      confidence: 'high',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/negative/i)).toBeInTheDocument()
  })

  it('renders label for "do_not_contact"', () => {
    const outcome: CallOutcome = {
      classification: 'do_not_contact',
      reason: 'Lead explicitly asked not to be contacted.',
      confidence: 'high',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/contact/i)).toBeInTheDocument()
  })

  it('renders label for "wrong_number"', () => {
    const outcome: CallOutcome = {
      classification: 'wrong_number',
      reason: 'Wrong person answered.',
      confidence: 'high',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/wrong/i)).toBeInTheDocument()
  })

  it('renders label for "hostile"', () => {
    const outcome: CallOutcome = {
      classification: 'hostile',
      reason: 'Lead was aggressive.',
      confidence: 'high',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/hostile/i)).toBeInTheDocument()
  })

  it('renders label for "confused"', () => {
    const outcome: CallOutcome = {
      classification: 'confused',
      reason: 'Lead did not understand.',
      confidence: 'medium',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/confused/i)).toBeInTheDocument()
  })

  it('renders label for "technical_issue"', () => {
    const outcome: CallOutcome = {
      classification: 'technical_issue',
      reason: 'Call dropped due to audio problems.',
      confidence: 'high',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/technical/i)).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: No badge for null/undefined — graceful degradation
// ──────────────────────────────────────────────────────────────────────────────

describe('CallOutcomeBadge — graceful degradation', () => {
  it('renders nothing when outcome is null', () => {
    const { container } = render(<CallOutcomeBadge outcome={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when outcome is undefined', () => {
    const { container } = render(<CallOutcomeBadge outcome={undefined} />)
    expect(container.firstChild).toBeNull()
  })

  it('does not throw when outcome is null', () => {
    expect(() => render(<CallOutcomeBadge outcome={null} />)).not.toThrow()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: NO engagement indicator in DOM (qora-outcome spec)
// ──────────────────────────────────────────────────────────────────────────────

describe('CallOutcomeBadge — no engagement indicator', () => {
  it('does NOT render any engagement role="img" element', () => {
    const outcome: CallOutcome = {
      classification: 'completed_positive',
      reason: 'Lead bought the policy.',
      confidence: 'high',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    // ENGAGEMENT_ICONS and role="img" must be completely absent
    const imgRoles = screen.queryAllByRole('img')
    const engagementImgs = imgRoles.filter(el =>
      el.getAttribute('aria-label')?.toLowerCase().includes('engagement')
    )
    expect(engagementImgs).toHaveLength(0)
  })

  it('does NOT mention "engagement" anywhere in rendered text', () => {
    const outcome: CallOutcome = {
      classification: 'hostile',
      reason: 'Lead was rude.',
      confidence: 'high',
    }
    const { container } = render(<CallOutcomeBadge outcome={outcome} />)
    expect(container.textContent?.toLowerCase()).not.toContain('engagement')
  })
})
