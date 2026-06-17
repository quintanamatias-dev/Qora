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
