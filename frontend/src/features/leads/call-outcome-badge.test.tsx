/**
 * CallOutcomeBadge — Unit tests
 *
 * Spec: sdd/qora-post-call-analysis/spec — Requirement: Per-Call Outcome Badge
 *
 * TDD Layer: Unit (pure presentational component, no API calls)
 * TDD: RED phase — tests written before call-outcome-badge.tsx exists
 *
 * Tests:
 * - Renders correct label for each classification value
 * - Does NOT render when call_outcome is null/undefined
 * - Graceful degradation for missing classification
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CallOutcomeBadge } from './call-outcome-badge'
import type { CallOutcome } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Badge renders for analyzed call
// ──────────────────────────────────────────────────────────────────────────────

describe('CallOutcomeBadge — rendering', () => {
  it('renders "Interested" label when classification is "interested"', () => {
    const outcome: CallOutcome = {
      classification: 'interested',
      reason: 'Lead was enthusiastic.',
      engagement_quality: 'high',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/interested/i)).toBeInTheDocument()
  })

  it('renders "Not Interested" label when classification is "not_interested"', () => {
    const outcome: CallOutcome = {
      classification: 'not_interested',
      reason: 'Lead already has insurance.',
      engagement_quality: 'low',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/not.interested/i)).toBeInTheDocument()
  })

  it('renders "Busy" label when classification is "busy"', () => {
    const outcome: CallOutcome = {
      classification: 'busy',
      reason: 'Lead was driving.',
      engagement_quality: 'none',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/busy/i)).toBeInTheDocument()
  })

  it('renders "Follow Up" label when classification is "follow_up"', () => {
    const outcome: CallOutcome = {
      classification: 'follow_up',
      reason: 'Lead asked to be called back.',
      engagement_quality: 'medium',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/follow.up/i)).toBeInTheDocument()
  })

  it('renders "No Answer" label when classification is "no_answer"', () => {
    const outcome: CallOutcome = {
      classification: 'no_answer',
      reason: 'No response.',
      engagement_quality: 'none',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/no.answer/i)).toBeInTheDocument()
  })

  it('renders "Hostile" label when classification is "hostile"', () => {
    const outcome: CallOutcome = {
      classification: 'hostile',
      reason: 'Lead was aggressive.',
      engagement_quality: 'low',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/hostile/i)).toBeInTheDocument()
  })

  it('renders "Confused" label when classification is "confused"', () => {
    const outcome: CallOutcome = {
      classification: 'confused',
      reason: 'Lead did not understand.',
      engagement_quality: 'low',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByText(/confused/i)).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: No badge for legacy call — graceful degradation
// ──────────────────────────────────────────────────────────────────────────────

describe('CallOutcomeBadge — graceful degradation', () => {
  it('renders nothing when outcome is null', () => {
    const { container } = render(<CallOutcomeBadge outcome={null} />)
    // Should render nothing — empty container
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when outcome is undefined', () => {
    const { container } = render(<CallOutcomeBadge outcome={undefined} />)
    expect(container.firstChild).toBeNull()
  })

  it('does not throw when outcome is null', () => {
    // This proves graceful degradation — no runtime error
    expect(() => render(<CallOutcomeBadge outcome={null} />)).not.toThrow()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Engagement quality indicator renders
// ──────────────────────────────────────────────────────────────────────────────

describe('CallOutcomeBadge — engagement indicator', () => {
  it('renders high-engagement indicator when engagement_quality is "high"', () => {
    const outcome: CallOutcome = {
      classification: 'interested',
      reason: 'Lead was engaged.',
      engagement_quality: 'high',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    // Should render some visual indicator for high engagement
    expect(screen.getByRole('img', { name: /high/i })).toBeInTheDocument()
  })

  it('renders medium-engagement indicator when engagement_quality is "medium"', () => {
    const outcome: CallOutcome = {
      classification: 'follow_up',
      reason: 'Lead was somewhat engaged.',
      engagement_quality: 'medium',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByRole('img', { name: /medium/i })).toBeInTheDocument()
  })

  it('renders low-engagement indicator when engagement_quality is "low"', () => {
    const outcome: CallOutcome = {
      classification: 'not_interested',
      reason: 'Lead was not engaged.',
      engagement_quality: 'low',
    }
    render(<CallOutcomeBadge outcome={outcome} />)
    expect(screen.getByRole('img', { name: /low/i })).toBeInTheDocument()
  })
})
