/**
 * TranscriptViewer — Presentational component for call transcript display
 *
 * Spec: sdd/qora-basic-crm/spec — Requirement: Turn-by-Turn Display
 * Design:
 *   - Accepts sessionId prop, fetches via useTranscript hook
 *   - Agent turns: left-aligned, role label "Agent"
 *   - User turns: right-aligned, role label "User"
 *   - filler_detected: preserved in data model for historical data; no visual dimming
 *   - Loading: data-testid="transcript-loading"
 *   - Empty: "No transcript available"
 *   - Error: "Could not load transcript"
 */

import { useTranscript } from '@/api/hooks'
import type { TranscriptTurn } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Props
// ──────────────────────────────────────────────────────────────────────────────

interface TranscriptViewerProps {
  sessionId: string
}

// ──────────────────────────────────────────────────────────────────────────────
// Pure helper — format ISO timestamp to HH:MM:SS
// ──────────────────────────────────────────────────────────────────────────────

export function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso)
    const hh = String(d.getUTCHours()).padStart(2, '0')
    const mm = String(d.getUTCMinutes()).padStart(2, '0')
    const ss = String(d.getUTCSeconds()).padStart(2, '0')
    return `${hh}:${mm}:${ss}`
  } catch {
    return iso
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// TurnItem — presentational, pure props
// ──────────────────────────────────────────────────────────────────────────────

interface TurnItemProps {
  turn: TranscriptTurn
}

function TurnItem({ turn }: TurnItemProps) {
  const isAgent = turn.role === 'agent'

  return (
    <div
      data-testid="transcript-turn"
      data-role={turn.role}
      className={[
        'flex flex-col gap-0.5 max-w-[75%]',
        isAgent ? 'self-start items-start' : 'self-end items-end',
      ].join(' ')}
    >
      {/* Role label + timestamp */}
      <div className="flex items-center gap-2 text-xs text-ink-3">
        <span className="font-medium">
          {isAgent ? 'Agent' : 'User'}
        </span>
        <span>{formatTimestamp(turn.timestamp)}</span>
      </div>

      {/* Turn content */}
      <div
        className={[
          'px-3 py-2 rounded-md text-sm',
          isAgent
            ? 'bg-mist text-ink'
            : 'bg-teal-faint text-ink',
        ].join(' ')}
      >
        {turn.content}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// TranscriptViewer — container
// ──────────────────────────────────────────────────────────────────────────────

export function TranscriptViewer({ sessionId }: TranscriptViewerProps) {
  const { data, isLoading, isError } = useTranscript(sessionId)

  // Loading state
  if (isLoading) {
    return (
      <div data-testid="transcript-loading" className="py-6 text-center">
        <span className="text-ink-3 text-sm animate-pulse">
          Loading transcript…
        </span>
      </div>
    )
  }

  // Error state
  if (isError) {
    return (
      <div role="alert" className="py-4 text-center">
        <p className="text-error text-sm">Could not load transcript</p>
      </div>
    )
  }

  // Empty state
  if (!data || data.turns.length === 0) {
    return (
      <div className="py-6 text-center">
        <p className="text-ink-3 text-sm">No transcript available</p>
      </div>
    )
  }

  // Data — render turn list
  return (
    <div className="flex flex-col gap-3 py-4 px-2">
      {data.turns.map((turn) => (
        <TurnItem key={turn.id} turn={turn} />
      ))}
    </div>
  )
}
