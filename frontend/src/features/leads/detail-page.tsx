/**
 * LeadDetailPage — Container component for lead detail + call history
 *
 * Spec: sdd/qora-basic-crm/spec — Capability: call-history-view
 * Design: Container-presentational pattern (mirrors DashboardPage).
 *   - Reads clientId + leadId from URL params
 *   - Calls useLead(clientId, leadId) and useCallSessions(clientId, leadId)
 *   - Manages expandedSessionId state for transcript accordion
 *   - Delegates to CallHistoryList (presentational)
 */

import { useState } from 'react'
import { useParams, useNavigate } from 'react-router'
import { useLead, useCallSessions } from '@/api/hooks'
import { Badge } from '@/design/components/badge'
import type { LeadStatus, DetectedInterests, IdentifiedProblem } from '@/api/types'
import { CallHistoryList } from './call-history-list'
import { AnalysisPanel } from './analysis-panel'

// ──────────────────────────────────────────────────────────────────────────────
// Pure helpers
// ──────────────────────────────────────────────────────────────────────────────

function formatInterestLevel(level: number | null): string {
  if (level === null || level === undefined) return '—'
  return `${level}%`
}

// ──────────────────────────────────────────────────────────────────────────────
// LeadDetailPage
// ──────────────────────────────────────────────────────────────────────────────

export function LeadDetailPage() {
  const { clientId, leadId } = useParams<{ clientId: string; leadId: string }>()
  const navigate = useNavigate()
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null)

  const {
    data: lead,
    isLoading: leadLoading,
    isError: leadError,
  } = useLead(clientId ?? '', leadId ?? '')

  const {
    data: sessions,
    isLoading: sessionsLoading,
    isError: sessionsError,
  } = useCallSessions(clientId ?? '', leadId)

  function handleToggleSession(sessionId: string) {
    setExpandedSessionId(prev => (prev === sessionId ? null : sessionId))
  }

  // Lead loading — page-level skeleton
  if (leadLoading) {
    return (
      <div data-testid="lead-loading" className="space-y-4">
        <div className="h-8 bg-surface-container-low rounded-sm animate-pulse w-1/3" />
        <div className="h-32 bg-surface-container-low rounded-sm animate-pulse" />
      </div>
    )
  }

  // Lead error
  if (leadError || !lead) {
    return (
      <div
        data-testid="lead-error"
        role="alert"
        className="p-8 text-center space-y-4"
      >
        <p className="text-on-surface font-medium">Lead not found</p>
        <button
          type="button"
          onClick={() => navigate(`/app/${clientId}/leads`)}
          className="text-primary text-sm hover:underline"
        >
          ← Back to leads
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Back navigation */}
      <button
        type="button"
        onClick={() => navigate(`/app/${clientId}/leads`)}
        className="text-sm text-on-surface-variant hover:text-on-surface transition-colors"
      >
        ← Leads
      </button>

      {/* Lead header card */}
      <div className="bg-surface-container-low rounded-lg p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="font-display text-2xl font-bold text-on-surface">
              {lead.name}
            </h1>
            <p className="text-on-surface-variant mt-0.5">{lead.phone}</p>
          </div>
          <Badge status={lead.status as LeadStatus}>
            {lead.status.replace('_', ' ')}
          </Badge>
        </div>

        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-on-surface-variant text-xs uppercase tracking-wider mb-1">
              Interest Level
            </p>
            <p className="text-on-surface font-medium">
              {formatInterestLevel(lead.interest_level)}
            </p>
          </div>

          <div>
            <p className="text-on-surface-variant text-xs uppercase tracking-wider mb-1">
              Next Action
            </p>
            <p className="text-on-surface font-medium">
              {lead.next_action ?? '—'}
            </p>
          </div>

          {lead.do_not_call && (
            <div className="col-span-2">
              <Badge status="error">Do Not Call</Badge>
            </div>
          )}
        </div>

        <div>
          <p className="text-on-surface-variant text-xs uppercase tracking-wider mb-1">
            Last Call Summary
          </p>
          <p className="text-on-surface text-sm">
            {lead.summary_last_call ?? 'No summary yet'}
          </p>
        </div>

        {/* Phase 5: Analysis panel — interests chips + problem card from last call */}
        {lead.extracted_facts && (
          <AnalysisPanel
            interests={lead.extracted_facts.detected_interests as DetectedInterests | null}
            problem={lead.extracted_facts.identified_problem as IdentifiedProblem | null}
          />
        )}
      </div>

      {/* Call History section */}
      <section>
        <h2 className="text-lg font-semibold text-on-surface mb-4">
          Call History
        </h2>

        {/* Sessions loading spinner — only in history section */}
        {sessionsLoading ? (
          <div className="py-4 text-center">
            <span className="text-on-surface-variant text-sm animate-pulse">
              Loading calls…
            </span>
          </div>
        ) : sessionsError ? (
          <div
            data-testid="sessions-error"
            role="alert"
            className="py-4 text-center"
          >
            <p className="text-on-surface-variant text-sm">
              Unable to load call history. Please try again.
            </p>
          </div>
        ) : (
          <CallHistoryList
            sessions={sessions ?? []}
            expandedSessionId={expandedSessionId}
            onToggleSession={handleToggleSession}
          />
        )}
      </section>
    </div>
  )
}
