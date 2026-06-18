/**
 * CallDetailPage — Behavior tests (final review readiness)
 *
 * Focus: the analysis column must distinguish a real fetch error from the
 * "no analysis available" empty state. When `useCallAnalysis` reports
 * `isError: true`, the page MUST render an explicit analysis error UI and MUST
 * NOT render the CallAnalysisPanel "analysis-empty" state (which would imply the
 * call simply has no analysis rather than that the request failed).
 *
 * TDD Layer: Behavior (container page — routing + hook state)
 *
 * Strategy: mock `@/api/hooks` so we can drive `useCallAnalysis` state directly
 * and stub `useTranscript` (CallDetailPage renders TranscriptViewer).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router'
import { CallDetailPage } from './call-detail-page'

// ──────────────────────────────────────────────────────────────────────────────
// Hook mocks — control useCallAnalysis state, stub useTranscript
// ──────────────────────────────────────────────────────────────────────────────

const useCallAnalysisMock = vi.fn()
const useTranscriptMock = vi.fn()

vi.mock('@/api/hooks', () => ({
  useCallAnalysis: (sessionId: string) => useCallAnalysisMock(sessionId),
  useTranscript: (sessionId: string) => useTranscriptMock(sessionId),
}))

function renderCallDetail(sessionId = 'session-1') {
  return render(
    <MemoryRouter initialEntries={[`/app/demo-client/calls/${sessionId}`]}>
      <Routes>
        <Route path="/app/:clientId/calls/:sessionId" element={<CallDetailPage />} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  // TranscriptViewer just needs a stable, non-erroring hook result. It reads
  // `data.turns`, so provide the expected shape.
  useTranscriptMock.mockReturnValue({
    data: { turns: [] },
    isLoading: false,
    isError: false,
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: useCallAnalysis reports a real fetch error
// ──────────────────────────────────────────────────────────────────────────────

describe('CallDetailPage — analysis error state', () => {
  it('renders an explicit analysis error UI when isError=true', () => {
    useCallAnalysisMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    })

    renderCallDetail()

    const errorBox = screen.getByTestId('analysis-error')
    expect(errorBox).toBeInTheDocument()
    expect(errorBox.textContent).toMatch(/failed to load analysis/i)
  })

  it('does NOT render the "no analysis" empty state when isError=true', () => {
    useCallAnalysisMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    })

    renderCallDetail()

    // A real error must not be mistaken for "this call has no analysis".
    expect(screen.queryByTestId('analysis-empty')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: unified masonry flow — transcript is the FIRST card in the SAME
// column flow as the analysis cards, NOT a separate floated/sticky region.
//
// Correction history:
//   1. sticky left column        → rejected (frozen column).
//   2. floated transcript aside  → rejected (analysis still stayed to the right;
//      empty space below a short transcript was left blank).
//
// Final intent: Transcript + analysis sections share ONE responsive CSS-columns
// masonry flow. The transcript is just the first card (top-left); analysis cards
// flow through the same columns and FILL the space below the transcript in the
// left column. No separate float/sticky region, no fixed grid column.
// ──────────────────────────────────────────────────────────────────────────────

describe('CallDetailPage — unified masonry flow (transcript is a card in the flow)', () => {
  beforeEach(() => {
    useCallAnalysisMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
    })
  })

  it('does NOT pin the transcript (no sticky/fixed frozen column)', () => {
    renderCallDetail()

    const transcript = screen.getByTestId('transcript-region')
    // The transcript scrolls away with the page — never pinned.
    expect(transcript.className).not.toContain('sticky')
    expect(transcript.className).not.toContain('fixed')
  })

  it('does NOT make the transcript a separate floated aside region anymore', () => {
    renderCallDetail()

    const transcript = screen.getByTestId('transcript-region')
    // Rejected layouts: a dedicated floated/width-locked transcript column.
    // The transcript now participates in the shared column flow instead.
    expect(transcript.className).not.toContain('float-left')
    expect(transcript.className).not.toContain('float-right')
    expect(transcript.className).not.toMatch(/(^|\s|:)w-2\/5/)
  })

  it('makes the transcript a break-avoiding card in the shared flow', () => {
    renderCallDetail()

    const transcript = screen.getByTestId('transcript-region')
    // As the first card in the CSS-columns flow it must avoid splitting across
    // a column boundary, exactly like the analysis cards.
    expect(transcript.className).toContain('break-inside-avoid')
  })

  it('wraps transcript and analysis in ONE shared responsive columns/masonry flow', () => {
    renderCallDetail()

    const content = screen.getByTestId('call-detail-content')
    // Unified masonry: 1 col small, 2 on lg, 3 on 2xl — the same flow that
    // holds both the transcript card and the analysis cards. This is what lets
    // analysis cards fill space BELOW the transcript instead of only to the right.
    expect(content.className).toContain('columns-1')
    expect(content.className).toContain('lg:columns-2')
    expect(content.className).toContain('2xl:columns-3')
    // The rejected float-containment wrapper must be gone.
    expect(content.className).not.toContain('flow-root')
  })

  it('renders the transcript inside the same flow container as the analysis cards', () => {
    renderCallDetail()

    const content = screen.getByTestId('call-detail-content')
    const transcript = screen.getByTestId('transcript-region')
    // Structural proof that transcript and analysis share one flow: the
    // transcript card is a direct child of the unified columns container.
    expect(transcript.parentElement).toBe(content)
  })
})
