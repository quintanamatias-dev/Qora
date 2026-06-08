/**
 * CallAnalysisPanel — Presentational component for full call analysis display
 *
 * Renders all 12 analysis dimensions for a single call session.
 * Design: Pure presentational — receives CallAnalysis | null
 *   - Shows "No analysis available" when null
 *   - Top summary: summary text, interest level bar, classification badge, next action
 *   - Grid of dimension cards: objections, pain points, service issues,
 *     detected interests, commitments, profile facts, misc notes, data corrections
 *   - Bottom audit section (collapsible): analysis_status, analysis_error, analyzed_at
 */

import { useState } from 'react'
import type { CallAnalysis } from '@/api/types'
import { Badge } from '@/design/components/badge'
import { Card } from '@/design/components/card'

// ──────────────────────────────────────────────────────────────────────────────
// Classification → badge status mapping
// ──────────────────────────────────────────────────────────────────────────────

function classificationBadgeStatus(
  classification: string | null
): 'success' | 'error' | 'warning' | 'neutral' {
  if (!classification) return 'neutral'
  if (classification.includes('positive')) return 'success'
  if (classification.includes('negative') || classification === 'hostile' || classification === 'do_not_contact') return 'error'
  if (classification === 'busy' || classification === 'confused' || classification === 'callback_requested') return 'warning'
  return 'neutral'
}

function urgencyStyle(urgency: string | null): string {
  switch (urgency) {
    case 'high': return 'text-error font-semibold'
    case 'medium': return 'text-warning font-medium'
    case 'low': return 'text-ink-3'
    default: return 'text-ink-3'
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Small helpers
// ──────────────────────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs text-ink-3 uppercase tracking-wider mb-1.5">
      {children}
    </p>
  )
}

function Chip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 text-xs rounded-full bg-mist text-ink-3 border border-line">
      {label}
    </span>
  )
}

function EmptyState({ label }: { label: string }) {
  return (
    <p className="text-xs text-ink-3 italic">{label}</p>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Interest Level Bar
// ──────────────────────────────────────────────────────────────────────────────

function InterestBar({ level }: { level: number | null }) {
  if (level === null || level === undefined) return null
  const pct = Math.max(0, Math.min(100, level))
  const color = pct >= 70 ? 'bg-teal' : pct >= 40 ? 'bg-warning' : 'bg-error'

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs text-ink-3">
        <span>Interest Level</span>
        <span className="font-medium text-ink">{pct}%</span>
      </div>
      <div className="h-1.5 bg-mist rounded-full overflow-hidden">
        <div
          data-testid="interest-bar"
          className={['h-full rounded-full transition-all', color].join(' ')}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Dimension: Objections
// ──────────────────────────────────────────────────────────────────────────────

function ObjectionsCard({ objections }: { objections: Record<string, unknown>[] | null }) {
  if (!objections || objections.length === 0) {
    return <EmptyState label="No objections recorded" />
  }
  return (
    <ul className="space-y-1.5">
      {objections.map((obj, idx) => {
        const text = (obj['text'] ?? obj['objection'] ?? String(obj)) as string
        const severity = obj['severity'] as string | undefined
        return (
          <li key={idx} className="flex items-start gap-2">
            <span className="text-sm text-ink">{text}</span>
            {severity && (
              <span className={['text-xs font-medium uppercase', urgencyStyle(severity)].join(' ')}>
                {severity}
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Dimension: Pain Points
// ──────────────────────────────────────────────────────────────────────────────

function PainPointsCard({ painPoints }: { painPoints: Record<string, unknown>[] | null }) {
  if (!painPoints || painPoints.length === 0) {
    return <EmptyState label="No pain points identified" />
  }
  return (
    <ul className="space-y-2">
      {painPoints.map((pp, idx) => {
        const category = (pp['category'] ?? '') as string
        const description = (pp['description'] ?? '') as string
        const urgency = (pp['urgency'] ?? '') as string
        return (
          <li key={idx} className="space-y-0.5">
            <div className="flex items-center gap-2 flex-wrap">
              {category && (
                <span className="inline-flex items-center px-1.5 py-0.5 text-xs rounded bg-mist text-ink-3">
                  {category}
                </span>
              )}
              {urgency && (
                <span className={['text-xs font-medium uppercase', urgencyStyle(urgency)].join(' ')}>
                  {urgency}
                </span>
              )}
            </div>
            {description && (
              <p className="text-sm text-ink">{description}</p>
            )}
          </li>
        )
      })}
    </ul>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Dimension: Service Issues
// ──────────────────────────────────────────────────────────────────────────────

function ServiceIssuesCard({ serviceIssues }: { serviceIssues: Record<string, unknown>[] | null }) {
  if (!serviceIssues || serviceIssues.length === 0) {
    return <EmptyState label="No service issues detected" />
  }
  return (
    <ul className="space-y-1">
      {serviceIssues.map((issue, idx) => {
        const text = (issue['issue'] ?? issue['text'] ?? String(issue)) as string
        return (
          <li key={idx} className="text-sm text-ink">
            {text}
          </li>
        )
      })}
    </ul>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Dimension: Profile Facts
// ──────────────────────────────────────────────────────────────────────────────

function ProfileFactsCard({ profileFacts }: { profileFacts: Record<string, unknown>[] | null }) {
  if (!profileFacts || profileFacts.length === 0) {
    return <EmptyState label="No profile facts extracted" />
  }
  return (
    <dl className="space-y-1">
      {profileFacts.map((fact, idx) => {
        const key = (fact['key'] ?? fact['field'] ?? '') as string
        const value = (fact['value'] ?? '') as string
        return (
          <div key={idx} className="flex items-start gap-2">
            {key && (
              <dt className="text-xs text-ink-3 min-w-[80px] shrink-0">
                {key}
              </dt>
            )}
            <dd className="text-sm text-ink">{value}</dd>
          </div>
        )
      })}
    </dl>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Dimension: Commitment Signals
// ──────────────────────────────────────────────────────────────────────────────

function CommitmentsCard({ commitments }: { commitments: Record<string, unknown>[] | null }) {
  if (!commitments || commitments.length === 0) {
    return <EmptyState label="No commitment signals" />
  }
  return (
    <ul className="space-y-1">
      {commitments.map((c, idx) => {
        const text = (c['signal'] ?? c['text'] ?? String(c)) as string
        return (
          <li key={idx} className="text-sm text-ink">
            {text}
          </li>
        )
      })}
    </ul>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Dimension: Misc Notes
// ──────────────────────────────────────────────────────────────────────────────

function MiscNotesCard({ miscNotes }: { miscNotes: Record<string, unknown> | Record<string, unknown>[] | null }) {
  // misc_notes is stored as {"notes": [...]} dict or sometimes as a plain array
  const notes: Record<string, unknown>[] = (() => {
    if (!miscNotes) return []
    if (Array.isArray(miscNotes)) return miscNotes
    if (typeof miscNotes === 'object' && 'notes' in miscNotes && Array.isArray(miscNotes.notes)) {
      return miscNotes.notes as Record<string, unknown>[]
    }
    return []
  })()

  if (notes.length === 0) {
    return <EmptyState label="No additional notes" />
  }
  return (
    <ul className="space-y-1.5">
      {notes.map((note, idx) => (
          <li key={idx} className="text-sm text-ink">
            <span className="text-ink-3 text-xs uppercase mr-2">
            {typeof note.type === 'string' ? note.type.replace(/_/g, ' ') : ''}
          </span>
          {typeof note.note === 'string' ? note.note : JSON.stringify(note)}
        </li>
      ))}
    </ul>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Dimension: Data Corrections
// ──────────────────────────────────────────────────────────────────────────────

function DataCorrectionsCard({ corrections }: { corrections: Record<string, unknown>[] | null }) {
  if (!corrections || corrections.length === 0) {
    return <EmptyState label="No data corrections" />
  }
  return (
    <ul className="space-y-1.5">
      {corrections.map((c, idx) => {
        const field = (c['field'] ?? '') as string
        const oldVal = (c['old_value'] ?? c['old'] ?? '') as string
        const newVal = (c['new_value'] ?? c['new'] ?? '') as string
        return (
          <li key={idx} className="text-sm space-y-0.5">
            {field && <span className="text-xs text-ink-3">{field}</span>}
            <div className="flex items-center gap-2">
              {oldVal && <span className="line-through text-ink-3">{oldVal}</span>}
              {newVal && <span className="text-ink font-medium">→ {newVal}</span>}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Audit Section (collapsible)
// ──────────────────────────────────────────────────────────────────────────────

function AuditSection({ analysis }: { analysis: CallAnalysis }) {
  const [open, setOpen] = useState(false)

  const hasError = Boolean(analysis.analysis_error)
  const statusBadge = analysis.analysis_status === 'ok' ? 'success' : 'warning'

  return (
    <div className="border border-line rounded-md">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-2.5 text-sm text-ink-3 hover:bg-pearl/50 transition-colors rounded-md"
      >
        <span className="font-medium">Audit / Metadata</span>
        <span>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div
          data-testid="audit-section"
          className="px-4 pb-4 space-y-2 border-t border-line"
        >
          <div className="flex items-center gap-2 pt-2">
            <span className="text-xs text-ink-3">Status:</span>
            <Badge status={statusBadge}>{analysis.analysis_status}</Badge>
          </div>
          {hasError && (
            <div>
              <span className="text-xs text-ink-3">Error:</span>
              <p className="text-sm text-error mt-0.5">{analysis.analysis_error}</p>
            </div>
          )}
          <div>
            <span className="text-xs text-ink-3">Analyzed at: </span>
            <span className="text-xs text-ink">
              {new Date(analysis.analyzed_at).toLocaleString()}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Props
// ──────────────────────────────────────────────────────────────────────────────

interface CallAnalysisPanelProps {
  analysis: CallAnalysis | null | undefined
  isLoading?: boolean
}

// ──────────────────────────────────────────────────────────────────────────────
// CallAnalysisPanel — main component
// ──────────────────────────────────────────────────────────────────────────────

export function CallAnalysisPanel({ analysis, isLoading }: CallAnalysisPanelProps) {
  if (isLoading) {
    return (
      <div data-testid="analysis-loading" className="py-6 text-center">
        <span className="text-ink-3 text-sm animate-pulse">
          Loading analysis…
        </span>
      </div>
    )
  }

  if (!analysis) {
    return (
      <div data-testid="analysis-empty" className="py-6 text-center">
        <p className="text-ink-3 text-sm">No analysis available for this call</p>
      </div>
    )
  }

  // Combined detected interests (products + specific_needs)
  const allInterests = [
    ...(analysis.products ?? []),
    ...(analysis.specific_needs ?? []),
  ]

  return (
    <div data-testid="call-analysis-panel" className="space-y-5">

      {/* ── Top Summary Section ── */}
      <Card>
        <div className="space-y-4">
          {/* Summary text */}
          {analysis.summary && (
            <div>
              <SectionLabel>Summary</SectionLabel>
              <p className="text-sm text-ink leading-relaxed">
                {analysis.summary}
              </p>
            </div>
          )}

          {/* Interest level bar */}
          <InterestBar level={analysis.interest_level} />

          {/* Classification + outcome reason */}
          <div className="flex flex-wrap items-start gap-3">
            {analysis.classification && (
              <div>
                <SectionLabel>Classification</SectionLabel>
                <Badge status={classificationBadgeStatus(analysis.classification)}>
                  {analysis.classification.replace(/_/g, ' ')}
                </Badge>
              </div>
            )}
            {analysis.outcome_reason && (
              <div className="flex-1">
                <SectionLabel>Outcome Reason</SectionLabel>
                <p className="text-sm text-ink">{analysis.outcome_reason}</p>
              </div>
            )}
          </div>

          {/* Urgency + Primary need */}
          <div className="grid grid-cols-2 gap-4">
            {analysis.urgency && (
              <div>
                <SectionLabel>Urgency</SectionLabel>
                <p className={['text-sm', urgencyStyle(analysis.urgency)].join(' ')}>
                  {analysis.urgency}
                </p>
              </div>
            )}
            {analysis.primary_need && (
              <div>
                <SectionLabel>Primary Need</SectionLabel>
                <p className="text-sm text-ink">{analysis.primary_need}</p>
              </div>
            )}
          </div>

          {/* Next action */}
          {analysis.next_action_suggested && (
            <div>
              <SectionLabel>Next Action</SectionLabel>
              <Badge status="active">
                {analysis.next_action_suggested}
              </Badge>
            </div>
          )}

          {/* Current insurance */}
          {analysis.current_insurance && (
            <div>
              <SectionLabel>Current Insurance</SectionLabel>
              <p className="text-sm text-ink">{analysis.current_insurance}</p>
            </div>
          )}
        </div>
      </Card>

      {/* ── Dimension Grid ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* Objections */}
        <Card>
          <SectionLabel>Objections</SectionLabel>
          <ObjectionsCard objections={analysis.objections} />
        </Card>

        {/* Pain Points */}
        <Card>
          <SectionLabel>Pain Points</SectionLabel>
          <PainPointsCard painPoints={analysis.pain_points} />
        </Card>

        {/* Service Issues */}
        <Card>
          <SectionLabel>Service Issues</SectionLabel>
          <ServiceIssuesCard serviceIssues={analysis.service_issues} />
        </Card>

        {/* Detected Interests */}
        <Card>
          <SectionLabel>Detected Interests</SectionLabel>
          {allInterests.length === 0 ? (
            <EmptyState label="No interests detected" />
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {allInterests.map((item, idx) => (
                <Chip key={idx} label={typeof item === 'string' ? item : JSON.stringify(item)} />
              ))}
            </div>
          )}
        </Card>

        {/* Commitment Signals */}
        <Card>
          <SectionLabel>Commitment Signals</SectionLabel>
          <CommitmentsCard commitments={analysis.commitment_signals} />
        </Card>

        {/* Profile Facts */}
        <Card>
          <SectionLabel>Profile Facts</SectionLabel>
          <ProfileFactsCard profileFacts={analysis.profile_facts} />
        </Card>

        {/* Misc Notes */}
        <Card>
          <SectionLabel>Notes</SectionLabel>
          <MiscNotesCard miscNotes={analysis.misc_notes} />
        </Card>

        {/* Data Corrections */}
        <Card>
          <SectionLabel>Data Corrections</SectionLabel>
          <DataCorrectionsCard corrections={analysis.data_corrections} />
        </Card>
      </div>

      {/* ── Audit Section ── */}
      <AuditSection analysis={analysis} />
    </div>
  )
}
