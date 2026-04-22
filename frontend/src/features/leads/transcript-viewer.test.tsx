/**
 * TranscriptViewer — Unit/Integration tests
 *
 * Spec: sdd/qora-basic-crm/spec — Requirement: Transcript Viewer Component
 * Design: Receives SessionTranscript prop, renders turns with role differentiation.
 *         Agent turns left-aligned, user turns right-aligned.
 *         filler_detected turns get visual indicator (opacity-50 → aria-label="filler").
 *
 * TDD Layer: Unit (direct props, no router needed)
 * TDD: RED phase — tests written before implementation
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { TranscriptViewer } from './transcript-viewer'

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function createTestClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  })
}

function renderViewer(sessionId: string) {
  const qc = createTestClient()
  render(
    <QueryClientProvider client={qc}>
      <TranscriptViewer sessionId={sessionId} />
    </QueryClientProvider>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Loading state
// ──────────────────────────────────────────────────────────────────────────────

describe('TranscriptViewer — loading state', () => {
  it('shows loading indicator while transcript is fetching', async () => {
    server.use(
      http.get('/api/v1/calls/:sessionId/transcript', async () => {
        await new Promise(r => setTimeout(r, 200))
        return HttpResponse.json({
          session_id: 'session-abc',
          turn_count: 0,
          turns: [],
        })
      })
    )

    renderViewer('session-abc')
    // While loading, a loading indicator is visible
    expect(screen.getByTestId('transcript-loading')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Empty transcript
// ──────────────────────────────────────────────────────────────────────────────

describe('TranscriptViewer — empty state', () => {
  it('shows "No transcript available" when turns array is empty', async () => {
    server.use(
      http.get('/api/v1/calls/:sessionId/transcript', () =>
        HttpResponse.json({
          session_id: 'session-empty',
          turn_count: 0,
          turns: [],
        })
      )
    )

    renderViewer('session-empty')
    const msg = await screen.findByText('No transcript available')
    expect(msg).toBeInTheDocument()
  })

  it('does not render any turn items when empty', async () => {
    server.use(
      http.get('/api/v1/calls/:sessionId/transcript', () =>
        HttpResponse.json({
          session_id: 'session-empty',
          turn_count: 0,
          turns: [],
        })
      )
    )

    renderViewer('session-empty')
    await screen.findByText('No transcript available')
    expect(screen.queryAllByTestId('transcript-turn')).toHaveLength(0)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Error state
// ──────────────────────────────────────────────────────────────────────────────

describe('TranscriptViewer — error state', () => {
  it('shows "Could not load transcript" on fetch error', async () => {
    server.use(
      http.get('/api/v1/calls/:sessionId/transcript', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      )
    )

    renderViewer('session-bad')
    const msg = await screen.findByText('Could not load transcript')
    expect(msg).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Turn-by-turn display
// ──────────────────────────────────────────────────────────────────────────────

describe('TranscriptViewer — renders turns', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/v1/calls/:sessionId/transcript', () =>
        HttpResponse.json({
          session_id: 'session-abc',
          turn_count: 3,
          turns: [
            {
              id: 't1',
              role: 'agent',
              content: 'Hello, this is the agent speaking.',
              timestamp: '2026-01-15T10:00:01Z',
              filler_detected: false,
            },
            {
              id: 't2',
              role: 'user',
              content: 'Yes, I was expecting your call.',
              timestamp: '2026-01-15T10:00:05Z',
              filler_detected: false,
            },
            {
              id: 't3',
              role: 'agent',
              content: 'Great! Let me explain our options.',
              timestamp: '2026-01-15T10:00:08Z',
              filler_detected: false,
            },
          ],
        })
      )
    )
  })

  it('renders all 3 turns from transcript', async () => {
    renderViewer('session-abc')
    const turns = await screen.findAllByTestId('transcript-turn')
    expect(turns).toHaveLength(3)
  })

  it('renders turn content text', async () => {
    renderViewer('session-abc')
    expect(await screen.findByText('Hello, this is the agent speaking.')).toBeInTheDocument()
    expect(screen.getByText('Yes, I was expecting your call.')).toBeInTheDocument()
    expect(screen.getByText('Great! Let me explain our options.')).toBeInTheDocument()
  })

  it('renders "Agent" label for agent turns', async () => {
    renderViewer('session-abc')
    await screen.findAllByTestId('transcript-turn')
    const agentLabels = screen.getAllByText('Agent')
    expect(agentLabels).toHaveLength(2)
  })

  it('renders "User" label for user turns', async () => {
    renderViewer('session-abc')
    await screen.findAllByTestId('transcript-turn')
    const userLabels = screen.getAllByText('User')
    expect(userLabels).toHaveLength(1)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Role differentiation (agent vs user)
// ──────────────────────────────────────────────────────────────────────────────

describe('TranscriptViewer — role differentiation', () => {
  it('agent turns have data-role="agent" attribute', async () => {
    server.use(
      http.get('/api/v1/calls/:sessionId/transcript', () =>
        HttpResponse.json({
          session_id: 'session-abc',
          turn_count: 2,
          turns: [
            { id: 't1', role: 'agent', content: 'Agent message', timestamp: '2026-01-15T10:00:01Z', filler_detected: false },
            { id: 't2', role: 'user', content: 'User message', timestamp: '2026-01-15T10:00:05Z', filler_detected: false },
          ],
        })
      )
    )

    renderViewer('session-abc')
    const turns = await screen.findAllByTestId('transcript-turn')
    expect(turns[0]).toHaveAttribute('data-role', 'agent')
    expect(turns[1]).toHaveAttribute('data-role', 'user')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Filler detected turns show visual indicator
// ──────────────────────────────────────────────────────────────────────────────

describe('TranscriptViewer — filler detected', () => {
  it('filler turns have data-filler="true" attribute', async () => {
    server.use(
      http.get('/api/v1/calls/:sessionId/transcript', () =>
        HttpResponse.json({
          session_id: 'session-filler',
          turn_count: 2,
          turns: [
            { id: 't1', role: 'agent', content: 'Normal turn', timestamp: '2026-01-15T10:00:01Z', filler_detected: false },
            { id: 't2', role: 'agent', content: 'Hmm, uh, let me think...', timestamp: '2026-01-15T10:00:03Z', filler_detected: true },
          ],
        })
      )
    )

    renderViewer('session-filler')
    const turns = await screen.findAllByTestId('transcript-turn')
    expect(turns).toHaveLength(2)
    expect(turns[0]).toHaveAttribute('data-filler', 'false')
    expect(turns[1]).toHaveAttribute('data-filler', 'true')
  })
})
