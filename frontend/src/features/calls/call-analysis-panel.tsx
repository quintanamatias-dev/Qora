/**
 * CallAnalysisPanel — Presentational component for full call analysis display
 *
 * PR 3 (post-call-analysis-bi-friendly): Refactored from decorative summary cards
 * to structured inspection tables. Each dimension shows normalized variable/value
 * rows with collapsible evidence. DataCorrectionsCard shows honest CRM parity states.
 *
 * Design: Pure presentational — receives CallAnalysis | null
 *   - Shows "No analysis available" when null
 *   - Top summary: summary text, interest level bar, classification badge, next action
 *   - Structured dimension rows: objections, pain points, service issues
 *   - DataCorrectionsCard: light inline field→value rows with section-level
 *     (batch) Qora-applied and CRM-sync status badges in the section header
 *   - Bottom audit section (collapsible): analysis_status, analysis_error, analyzed_at
 *
 * Spec: openspec/changes/post-call-analysis-bi-friendly/specs/call-detail-inspection-ui/spec.md
 * Spec: openspec/changes/post-call-analysis-bi-friendly/specs/crm-parity/spec.md
 */

import { useState } from 'react'
import type { CallAnalysis } from '@/api/types'
import { resolveLabel } from '@/config/dimension-labels'
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

function strengthStyle(strength: string | null | undefined): string {
  switch (strength) {
    case 'high': return 'text-error font-semibold'
    case 'medium': return 'text-warning font-medium'
    case 'low': return 'text-ink-3'
    default: return 'text-ink-3'
  }
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
// Dimension: Objections — structured inspection rows
// ──────────────────────────────────────────────────────────────────────────────

// Evidence toggle wrapper for inline-visible evidence (tasks 3.5/3.6 spec requires it)
function ObjectionEvidenceRow({ evidence }: { evidence: string }) {
  return (
    <div
      data-testid="objection-evidence"
      className="text-xs text-ink-3 italic border-l-2 border-line-2 pl-2 break-words"
    >
      "{evidence}"
    </div>
  )
}

// Augmented ObjectionsCard: evidence always visible inline per spec
function ObjectionsCardFull({ objections }: { objections: Record<string, unknown>[] | null }) {
  if (!objections || objections.length === 0) {
    return <EmptyState label="No objections recorded" />
  }
  return (
    <ul className="space-y-2">
      {objections.map((obj, idx) => {
        const category = (obj['category'] ?? '') as string
        const strength = (obj['strength'] ?? '') as string
        const resolution = (obj['resolution_status'] ?? '') as string
        const evidence = (obj['evidence'] ?? null) as string | null
        const isPrimary = Boolean(obj['is_primary'])

        return (
          <li
            key={idx}
            className="rounded-md border border-line bg-pearl px-3 py-2.5 space-y-1.5"
          >
            {/* Structured fields */}
            <div className="space-y-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  data-testid="objection-category"
                  className="font-mono text-xs px-1.5 py-0.5 rounded bg-mist border border-line text-ink-2"
                >
                  {category || '—'}
                </span>
                {isPrimary && (
                  <span className="text-[10px] font-mono text-teal bg-teal-faint border border-teal-line px-1.5 py-0.5 rounded">
                    primary
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-ink-3 w-24 shrink-0">strength</span>
                <span
                  data-testid="objection-strength"
                  className={['text-xs font-mono uppercase', strengthStyle(strength)].join(' ')}
                >
                  {strength || '—'}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-ink-3 w-24 shrink-0">resolution</span>
                <span
                  data-testid="objection-resolution"
                  className="text-xs font-mono text-ink-2"
                >
                  {resolution || '—'}
                </span>
              </div>
            </div>
            {/* Evidence inline */}
            {evidence && (
              <ObjectionEvidenceRow evidence={evidence} />
            )}
          </li>
        )
      })}
    </ul>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Dimension: Pain Points — structured rows
// ──────────────────────────────────────────────────────────────────────────────

function PainPointsCard({ painPoints }: { painPoints: Record<string, unknown>[] | null }) {
  if (!painPoints || painPoints.length === 0) {
    return <EmptyState label="No pain points identified" />
  }
  return (
    <ul className="space-y-2">
      {painPoints.map((pp, idx) => {
        const category = (pp['category'] ?? '') as string
        const urgency = (pp['urgency'] ?? '') as string
        const description = (pp['description'] ?? null) as string | null
        const evidence = (pp['evidence'] ?? null) as string | null
        const isPrimary = Boolean(pp['is_primary'])

        return (
          <li
            key={idx}
            className="rounded-md border border-line bg-pearl px-3 py-2.5 space-y-1.5"
          >
            <div className="flex items-center gap-2 flex-wrap">
              {category && (
                <span
                  data-testid="pain-category"
                  className="font-mono text-xs px-1.5 py-0.5 rounded bg-mist border border-line text-ink-2"
                >
                  {category}
                </span>
              )}
              {isPrimary && (
                <span className="text-[10px] font-mono text-teal bg-teal-faint border border-teal-line px-1.5 py-0.5 rounded">
                  primary
                </span>
              )}
              {urgency && (
                <span className={['text-xs font-mono uppercase', urgencyStyle(urgency)].join(' ')}>
                  {urgency}
                </span>
              )}
            </div>
            {description && (
              <p className="text-sm text-ink">{description}</p>
            )}
            {evidence && (
              <p className="text-xs text-ink-3 italic border-l-2 border-line-2 pl-2 break-words">
                "{evidence}"
              </p>
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
    <ul className="space-y-2">
      {serviceIssues.map((issue, idx) => {
        // Normalized fields per ServiceIssue schema: category, source, severity,
        // description, evidence, confidence. Render the structured values that
        // exist; never drop available normalized data behind a prose-only line.
        const category = (issue['category'] ?? '') as string
        const source = (issue['source'] ?? '') as string
        const severity = (issue['severity'] ?? '') as string
        const description = (issue['description'] ?? issue['issue'] ?? issue['text'] ?? '') as string
        const evidence = (issue['evidence'] ?? null) as string | null

        return (
          <li
            key={idx}
            className="rounded-md border border-line bg-pearl px-3 py-2.5 space-y-1.5"
          >
            {/* Normalized category / source / severity */}
            <div className="flex items-center gap-2 flex-wrap">
              {category && (
                <span
                  data-testid="service-issue-category"
                  className="font-mono text-xs px-1.5 py-0.5 rounded bg-mist border border-line text-ink-2"
                >
                  {category}
                </span>
              )}
              {source && (
                <span
                  data-testid="service-issue-source"
                  className="text-[10px] font-mono uppercase tracking-wide text-ink-3"
                >
                  {source}
                </span>
              )}
              {severity && (
                <span
                  data-testid="service-issue-severity"
                  className={['text-xs font-mono uppercase', urgencyStyle(severity)].join(' ')}
                >
                  {severity}
                </span>
              )}
            </div>
            {description && (
              <p className="text-sm text-ink">{description}</p>
            )}
            {evidence && (
              <p
                data-testid="service-issue-evidence"
                className="text-xs text-ink-3 italic border-l-2 border-line-2 pl-2 break-words"
              >
                "{evidence}"
              </p>
            )}
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
// Dimension: Data Corrections — honest, section-level CRM parity
//
// Per the latest UI feedback, corrections are shown as light inline rows
// (`field → value`) without per-row cards or per-row sync badges. Application
// and CRM sync are effectively batch-level for these corrections, so the honest
// status lives ONCE at the section level (header badges):
//
// Per the latest feedback the header badges are deliberately MINIMAL: a single
// word ("Qora" / "CRM") whose colour carries the state, instead of verbose
// "Qora applied ✓" / "CRM unknown" pills that dominated the header. The full
// wording survives as a hover `title` so nothing is lost for inspection.
//
//   Qora badge (colour = applied state):
//     - every correction applied            → green  (title "applied")
//     - some applied, some not               → red    (title "partial")
//     - none applied                         → gray   (title "pending")
//
//   CRM badge (colour = batch parity — if one fails the section reflects it):
//     - any out_of_sync                      → red    (title "out of sync")
//     - all in_sync (and at least one)       → green  (title "synced")
//     - otherwise (null/unknown/stale/mixed) → gray   (title "unknown" — never fake sync)
//
// Old value, rejection reason, evidence and superseded notes stay readable but
// compact, inline under each row.
// ──────────────────────────────────────────────────────────────────────────────

// SyncDot — tiny inline status glyph for the section-level status badges.
// Kept as plain markup (no icon dependency) to stay compact and visually calm.
function SyncDot({ tone }: { tone: 'on' | 'off' | 'unknown' }) {
  const color =
    tone === 'on' ? 'bg-teal' : tone === 'off' ? 'bg-coral' : 'bg-ink-4'
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-1.5 w-1.5 rounded-full ${color}`}
    />
  )
}

type AppliedState = 'applied' | 'partial' | 'pending'
type CrmState = 'synced' | 'out_of_sync' | 'unknown'

// Reduce the whole batch of corrections into a single honest applied state.
function deriveAppliedState(corrections: Record<string, unknown>[]): AppliedState {
  const flags = corrections.map((c) => {
    // Per-call payload uses `applied`; analytics-parity uses `applied_to_qora`.
    // The explicit per-call `applied` flag is primary.
    const applied =
      (c['applied'] as boolean | undefined) ??
      (c['applied_to_qora'] as boolean | undefined)
    return applied === true
  })
  if (flags.every((f) => f)) return 'applied'
  if (flags.some((f) => f)) return 'partial'
  return 'pending'
}

// Reduce the whole batch into a single honest CRM parity state.
// A single out_of_sync poisons the batch; we never claim synced unless every
// correction is in_sync. Anything else stays "unknown" (no fake sync claim).
function deriveCrmState(corrections: Record<string, unknown>[]): CrmState {
  const statuses = corrections.map(
    (c) => c['crm_sync_status'] as string | null | undefined
  )
  if (statuses.some((s) => s === 'out_of_sync')) return 'out_of_sync'
  if (statuses.length > 0 && statuses.every((s) => s === 'in_sync')) {
    return 'synced'
  }
  return 'unknown'
}

function CorrectionsStatusBadges({
  corrections,
}: {
  corrections: Record<string, unknown>[]
}) {
  const appliedState = deriveAppliedState(corrections)
  const crmState = deriveCrmState(corrections)

  // Minimal label = just the system name. Colour carries the state; the verbose
  // wording lives in `title` so honesty/detail survives on hover.
  const appliedTone: 'on' | 'off' | 'unknown' =
    appliedState === 'applied' ? 'on' : appliedState === 'partial' ? 'off' : 'unknown'
  const appliedTitle =
    appliedState === 'applied'
      ? 'Qora: all corrections applied'
      : appliedState === 'partial'
        ? 'Qora: some corrections applied, some pending'
        : 'Qora: corrections pending'
  const appliedClass =
    appliedState === 'applied'
      ? 'text-teal bg-teal-faint border-teal-line'
      : appliedState === 'partial'
        ? 'text-coral bg-coral-faint border-coral-line'
        : 'text-ink-3 bg-mist border-line'

  const crmTone: 'on' | 'off' | 'unknown' =
    crmState === 'synced' ? 'on' : crmState === 'out_of_sync' ? 'off' : 'unknown'
  const crmTitle =
    crmState === 'synced'
      ? 'CRM: all corrections synced'
      : crmState === 'out_of_sync'
        ? 'CRM: one or more corrections out of sync'
        : 'CRM: sync state unknown (no integration or not reported)'
  const crmClass =
    crmState === 'synced'
      ? 'text-teal bg-teal-faint border-teal-line'
      : crmState === 'out_of_sync'
        ? 'text-coral bg-coral-faint border-coral-line'
        : 'text-ink-3 bg-mist border-line'

  return (
    <div
      data-testid="corrections-status-badges"
      className="flex items-center gap-1.5"
    >
      <span
        data-testid="corrections-qora-status"
        data-state={appliedState}
        title={appliedTitle}
        className={[
          'inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded-full border',
          appliedClass,
        ].join(' ')}
      >
        <SyncDot tone={appliedTone} />
        Qora
      </span>
      <span
        data-testid="corrections-crm-status"
        data-state={crmState}
        title={crmTitle}
        className={[
          'inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded-full border',
          crmClass,
        ].join(' ')}
      >
        <SyncDot tone={crmTone} />
        CRM
      </span>
    </div>
  )
}

function DataCorrectionsCard({ corrections }: { corrections: Record<string, unknown>[] | null }) {
  if (!corrections || corrections.length === 0) {
    return <EmptyState label="No data corrections" />
  }
  return (
    <ul data-testid="corrections-list" className="divide-y divide-line">
      {corrections.map((c, idx) => {
        const field = (c['field'] ?? '') as string
        const correctedVal = (c['corrected_value'] ?? c['new_value'] ?? c['new'] ?? '') as string
        const oldVal = (c['old_value'] ?? c['previous_value'] ?? c['old'] ?? '') as string
        const rejectionReason = (c['rejection_reason'] ?? '') as string
        const evidence = (c['evidence'] ?? null) as string | null
        const superseded = c['superseded'] === true

        return (
          <li key={idx} className="py-1.5 first:pt-0 last:pb-0 space-y-0.5">
            {/* field → value — light inline row, value at field-key weight */}
            <div className="flex items-baseline gap-1.5 flex-wrap">
              {field && (
                <span className="text-xs font-mono text-ink-3">{field}</span>
              )}
              {correctedVal && (
                <>
                  <span aria-hidden="true" className="text-xs text-ink-4">→</span>
                  <span
                    data-testid="correction-value"
                    className="text-xs font-mono text-ink"
                  >
                    {correctedVal}
                  </span>
                </>
              )}
              {oldVal && (
                <span className="text-[10px] font-mono text-ink-4 line-through">
                  {oldVal}
                </span>
              )}
            </div>

            {/* Compact evidence / rejection reason — readable but secondary */}
            {evidence && (
              <p
                data-testid="correction-evidence"
                className="text-[10px] text-ink-3 italic break-words"
              >
                "{evidence}"
              </p>
            )}
            {rejectionReason && (
              <p
                data-testid="correction-rejection-reason"
                className="text-[10px] text-coral break-words"
              >
                {rejectionReason}
              </p>
            )}

            {/* Superseded note — honest historical treatment. */}
            {superseded && (
              <p
                data-testid="correction-superseded-note"
                className="text-[10px] text-ink-3 italic"
              >
                Superseded by a later call — this reflects only what happened in this call.
              </p>
            )}
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
  /** Client locale for dimension label display (default: 'es') */
  locale?: 'es' | 'en'
}

// ──────────────────────────────────────────────────────────────────────────────
// CallAnalysisPanel — main component
// ──────────────────────────────────────────────────────────────────────────────

export function CallAnalysisPanel({ analysis, isLoading, locale = 'es' }: CallAnalysisPanelProps) {
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

  // Combined detected interests (products + specific_needs).
  // These arrive as flat normalized string codes at the API boundary — there is
  // no per-item evidence/comment. Render each as a normalized value tagged with
  // its source kind; do NOT fabricate fields the data does not carry.
  const allInterests: Array<{ value: string; kind: 'product' | 'need' }> = [
    ...(analysis.products ?? []).map((value) => ({
      value: typeof value === 'string' ? value : JSON.stringify(value),
      kind: 'product' as const,
    })),
    ...(analysis.specific_needs ?? []).map((value) => ({
      value: typeof value === 'string' ? value : JSON.stringify(value),
      kind: 'need' as const,
    })),
  ]

  // BI summary row: primary categories + counts from denormalized columns
  const hasBiSummary =
    analysis.primary_objection_category != null ||
    analysis.primary_pain_category != null ||
    analysis.objections_count != null

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

          {/* BI summary row — primary categories + counts */}
          {hasBiSummary && (
            <div className="pt-1 border-t border-line">
              <SectionLabel>BI Summary</SectionLabel>
              <div className="flex flex-wrap items-center gap-3 text-xs font-mono text-ink-3">
                {analysis.primary_objection_category && (
                  <span>
                    primary objection:{' '}
                    <span className="text-ink font-medium">
                      {resolveLabel(analysis.primary_objection_category, locale)}
                    </span>
                  </span>
                )}
                {analysis.primary_pain_category && (
                  <span>
                    primary pain:{' '}
                    <span className="text-ink font-medium">
                      {resolveLabel(analysis.primary_pain_category, locale)}
                    </span>
                  </span>
                )}
                {analysis.objections_count != null && (
                  <span>objections: <span className="text-ink">{analysis.objections_count}</span></span>
                )}
                {analysis.pain_points_count != null && (
                  <span>pain points: <span className="text-ink">{analysis.pain_points_count}</span></span>
                )}
                {analysis.service_issues_count != null && (
                  <span>service issues: <span className="text-ink">{analysis.service_issues_count}</span></span>
                )}
              </div>
            </div>
          )}
        </div>
      </Card>

      {/*
        ── Dimension Grid (masonry flow) ──
        Cards have very different heights (a 5-objection card vs an empty notes
        card). A rigid 2-col CSS grid leaves tall gaps and feels cramped, so we
        flow the cards through balanced CSS columns instead. Columns widen with
        the (now wider) analysis region: 1 col on small, 2 on lg, 3 on 2xl.
        `break-inside-avoid` keeps each card intact across the column break.
      */}
      <div
        data-testid="dimension-grid"
        className="columns-1 lg:columns-2 2xl:columns-3 gap-4 [column-fill:balance]"
      >
        {/* Objections — structured inspection */}
        <Card className="mb-4 break-inside-avoid">
          <SectionLabel>Objections</SectionLabel>
          <ObjectionsCardFull objections={analysis.objections} />
        </Card>

        {/* Pain Points — structured inspection */}
        <Card className="mb-4 break-inside-avoid">
          <SectionLabel>Pain Points</SectionLabel>
          <PainPointsCard painPoints={analysis.pain_points} />
        </Card>

        {/* Service Issues */}
        <Card className="mb-4 break-inside-avoid">
          <SectionLabel>Service Issues</SectionLabel>
          <ServiceIssuesCard serviceIssues={analysis.service_issues} />
        </Card>

        {/* Detected Interests — normalized value + source kind (honest) */}
        <Card className="mb-4 break-inside-avoid">
          <SectionLabel>Detected Interests</SectionLabel>
          {allInterests.length === 0 ? (
            <EmptyState label="No interests detected" />
          ) : (
            <ul className="space-y-1.5">
              {allInterests.map((item, idx) => (
                <li
                  key={idx}
                  className="flex items-center gap-2 rounded-md border border-line bg-pearl px-3 py-1.5"
                >
                  <span
                    data-testid="interest-value"
                    className="text-sm text-ink font-mono flex-1 min-w-0 break-words"
                  >
                    {item.value}
                  </span>
                  <span className="text-[10px] font-mono uppercase tracking-wide text-ink-3 shrink-0">
                    {item.kind}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Commitment Signals */}
        <Card className="mb-4 break-inside-avoid">
          <SectionLabel>Commitment Signals</SectionLabel>
          <CommitmentsCard commitments={analysis.commitment_signals} />
        </Card>

        {/* Profile Facts */}
        <Card className="mb-4 break-inside-avoid">
          <SectionLabel>Profile Facts</SectionLabel>
          <ProfileFactsCard profileFacts={analysis.profile_facts} />
        </Card>

        {/* Misc Notes */}
        <Card className="mb-4 break-inside-avoid">
          <SectionLabel>Notes</SectionLabel>
          <MiscNotesCard miscNotes={analysis.misc_notes} />
        </Card>

        {/* Data Corrections — light inline rows + section-level CRM parity */}
        <Card className="mb-4 break-inside-avoid">
          <div className="flex items-start justify-between gap-2 mb-1.5">
            <p className="text-xs text-ink-3 uppercase tracking-wider">
              Data Corrections
            </p>
            {analysis.data_corrections && analysis.data_corrections.length > 0 && (
              <CorrectionsStatusBadges corrections={analysis.data_corrections} />
            )}
          </div>
          <DataCorrectionsCard corrections={analysis.data_corrections} />
        </Card>
      </div>

      {/* ── Audit Section ── */}
      <AuditSection analysis={analysis} />
    </div>
  )
}
