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

function formatCustomFieldKey(key: string): string {
  return key
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
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
        <div className="h-8 bg-mist rounded-md animate-pulse w-1/3" />
        <div className="h-32 bg-mist rounded-md animate-pulse" />
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
        <p className="text-ink font-medium">Lead not found</p>
        <button
          type="button"
          onClick={() => navigate(`/app/${clientId}/leads`)}
          className="text-teal text-sm hover:underline"
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
        className="text-sm text-ink-3 hover:text-ink transition-colors"
      >
        ← Leads
      </button>

      {/* Lead header card */}
      <div className="bg-paper border border-line rounded-lg p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="font-display text-2xl font-medium text-ink">
              {lead.name}
            </h1>
            <p className="text-ink-3 mt-0.5">{lead.phone}</p>
          </div>
          <Badge status={lead.status as LeadStatus}>
            {lead.status.replace('_', ' ')}
          </Badge>
        </div>

        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-ink-3 text-xs uppercase tracking-wider mb-1">
              Interest Level
            </p>
            <p className="text-ink font-medium">
              {formatInterestLevel(lead.interest_level)}
            </p>
          </div>

          <div>
            <p className="text-ink-3 text-xs uppercase tracking-wider mb-1">
              Next Action
            </p>
            <p className="text-ink font-medium">
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
          <p className="text-ink-3 text-xs uppercase tracking-wider mb-1">
            Last Call Summary
          </p>
          <p className="text-ink text-sm">
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

      <section className="bg-paper border border-line rounded-lg p-6 space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-ink">Custom Fields</h2>
          <p className="text-sm text-ink-3 mt-1">
            Client-specific lead data captured from CRM imports and calls.
          </p>
        </div>

        {Object.entries(lead.custom_fields ?? {}).length > 0 ? (
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {Object.entries(lead.custom_fields ?? {}).map(([key, value]) => (
              <div key={key} className="rounded-md border border-line bg-pearl px-3 py-2.5">
                <dt className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3">
                  {formatCustomFieldKey(key)}
                </dt>
                <dd className="mt-1 text-sm font-medium text-ink break-words">
                  {value || '—'}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="rounded-md border border-line bg-pearl px-3 py-3 text-sm text-ink-3">
            No custom fields captured yet.
          </p>
        )}
      </section>

      {/* Call History section */}
      <section>
        <h2 className="text-lg font-semibold text-ink mb-4">
          Call History
        </h2>

        {/* Sessions loading spinner — only in history section */}
        {sessionsLoading ? (
          <div className="py-4 text-center">
            <span className="text-ink-3 text-sm animate-pulse">
              Loading calls…
            </span>
          </div>
        ) : sessionsError ? (
          <div
            data-testid="sessions-error"
            role="alert"
            className="py-4 text-center"
          >
            <p className="text-ink-3 text-sm">
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
