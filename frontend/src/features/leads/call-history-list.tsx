/**
 * CallHistoryList — Presentational component for call session history
 *
 * Spec: sdd/qora-basic-crm/spec — Requirement: Call History List
 * Design:
 *   - Pure presentational — receives sessions + expandedSessionId + onToggleSession
 *   - Each item: started_at (formatted), duration (mm:ss), status badge, outcome, summary snippet
 *   - Click item → onToggleSession(sessionId) — toggle expand/collapse
 *   - Empty: "No calls yet"
 */

import { useParams, useNavigate } from 'react-router'
import type { CallSession, CallOutcome } from '@/api/types'
import { Badge } from '@/design/components/badge'
import { formatDuration } from '@/lib/format-duration'
import { TranscriptViewer } from './transcript-viewer'
import { CallOutcomeBadge } from './call-outcome-badge'

// ──────────────────────────────────────────────────────────────────────────────
// Props
// ──────────────────────────────────────────────────────────────────────────────

interface CallHistoryListProps {
  sessions: CallSession[]
  expandedSessionId: string | null
  onToggleSession: (sessionId: string) => void
}

// ──────────────────────────────────────────────────────────────────────────────
// Pure helpers
// ──────────────────────────────────────────────────────────────────────────────

export function formatCallDate(isoOrNull: string | null): string {
  if (!isoOrNull) return '—'
  try {
    return new Date(isoOrNull).toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return isoOrNull
  }
}

export function truncateSummary(summary: string | null, maxLength = 100): string {
  if (!summary) return ''
  return summary.length > maxLength ? `${summary.slice(0, maxLength)}…` : summary
}

// ──────────────────────────────────────────────────────────────────────────────
// CallHistoryList
// ──────────────────────────────────────────────────────────────────────────────

export function CallHistoryList({
  sessions,
  expandedSessionId,
  onToggleSession,
}: CallHistoryListProps) {
  const { clientId } = useParams<{ clientId: string }>()
  const navigate = useNavigate()

  if (sessions.length === 0) {
    return (
      <div className="py-8 text-center">
        <p className="text-ink-3 text-sm">No calls yet</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {sessions.map((session) => {
        const isExpanded = expandedSessionId === session.id
        const statusBadge = session.status === 'completed' ? 'success' : 'neutral'
        const summarySnippet = truncateSummary(session.summary)

        const callOutcome = session.extracted_facts?.call_outcome as CallOutcome | null | undefined

        return (
          <div key={session.id} className="border border-line rounded-md">
            {/* Session row — clickable */}
            <div
              data-testid="call-history-item"
              onClick={() => onToggleSession(session.id)}
              className="flex items-center gap-4 px-4 py-3 cursor-pointer hover:bg-pearl/50 transition-colors rounded-t-md"
            >
              {/* Date */}
              <span className="text-sm text-ink min-w-[140px]">
                {formatCallDate(session.started_at)}
              </span>

              {/* Duration */}
              <span className="text-sm text-ink-3 min-w-[60px]">
                {session.duration_seconds != null
                  ? formatDuration(session.duration_seconds)
                  : '—'}
              </span>

              {/* Status badge */}
              <Badge status={statusBadge}>
                {session.status}
              </Badge>

              {/* Phase 5: Call outcome badge (replaces/augments legacy outcome) */}
              {callOutcome ? (
                <CallOutcomeBadge outcome={callOutcome} />
              ) : session.outcome ? (
                <span className="text-xs text-ink-3">
                  {session.outcome}
                </span>
              ) : null}

              {/* Summary snippet */}
              {summarySnippet && (
                <span className="text-xs text-ink-3 flex-1 truncate">
                  {summarySnippet}
                </span>
              )}

              {/* Detail link + expand indicator */}
              <div className="ml-auto flex items-center gap-3">
                <button
                  type="button"
                  data-testid="call-detail-link"
                  onClick={(e) => {
                    e.stopPropagation()
                    navigate(`/app/${clientId}/calls/${session.id}`)
                  }}
                  className="text-xs text-teal hover:underline"
                >
                  View detail
                </button>
                <span className="text-ink-3 text-xs">
                  {isExpanded ? '▲' : '▼'}
                </span>
              </div>
            </div>

            {/* Transcript viewer — inline accordion */}
            {isExpanded && (
              <div
                data-testid="transcript-viewer"
                className="border-t border-line bg-mist max-h-[500px] overflow-y-auto rounded-b-md"
              >
                <TranscriptViewer sessionId={session.id} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
