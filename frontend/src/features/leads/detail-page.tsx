/**
 * LeadDetailPage — Phase A: Enriched Lead Intelligence View (UI Clarity Update)
 *
 * Operator/debug inspection view showing exactly what Qora stores and what
 * the agent will receive on the next call. Data-faithful, not decorative.
 *
 * Layout: Two-column on md+ screens (responsive, single column on narrow)
 *   Left column (main):  Lead Record · Quote Readiness Fields · Qora Memory · Client CRM/Airtable
 *   Right column (side): Call History · Next-Call Context Preview
 *
 * Sections:
 *   A) Lead record — base stored fields
 *   B) Quote readiness fields — required fields for quoting + separate CRM-provided context
 *   C) Qora memory — profile facts (parsed, structured) + interest history
 *   D) Call history — sessions with per-call analysis (right column)
 *   E) CRM / Airtable mapping — external IDs and field mapping metadata
 *   F) Next-call context preview — literal blocks the agent will receive (right column)
 */

import { useState } from 'react'
import { useParams, useNavigate } from 'react-router'
import { useLead, useCallSessions, useLeadContextPreview, useIntegrations, useLeadDimensionRollups } from '@/api/hooks'
import { Badge } from '@/design/components/badge'
import type { LeadStatus, QuoteField, LeadContextPreview, DetectedInterestRollup, ServiceIssueRollup } from '@/api/types'
import { resolveLabel } from '@/config/dimension-labels'
import { CallHistoryList } from './call-history-list'

// ──────────────────────────────────────────────────────────────────────────────
// Pure helpers
// ──────────────────────────────────────────────────────────────────────────────

function formatDate(isoOrNull: string | null | undefined): string {
  if (!isoOrNull) return '—'
  try {
    return new Date(isoOrNull).toLocaleString('en-US', {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return isoOrNull
  }
}

function formatCustomFieldKey(key: string): string {
  return key.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/**
 * Attempt to parse a profile fact value as a structured JSON object.
 * Backend stores: {"category": "...", "fact": "...", "evidence": "...", "confidence": "..."}
 * Returns null on any parse failure — callers fall back to raw string display.
 */
function parseProfileFact(raw: string): {
  category: string
  fact: string
  evidence: string
  confidence: string
} | null {
  if (!raw || typeof raw !== 'string') return null
  const trimmed = raw.trim()
  if (!trimmed.startsWith('{')) return null
  try {
    const parsed = JSON.parse(trimmed)
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      typeof parsed.fact === 'string'
    ) {
      return {
        category: String(parsed.category ?? ''),
        fact: String(parsed.fact ?? ''),
        evidence: String(parsed.evidence ?? ''),
        confidence: String(parsed.confidence ?? ''),
      }
    }
    return null
  } catch {
    return null
  }
}

/**
 * Location-like heuristic: returns true when a profile fact value looks like
 * a specific neighbourhood, city, or barrio reference.
 *
 * Heuristic: matches known Argentine location keywords or short proper-noun
 * phrases that end with common barrio-style suffixes. Deliberately conservative
 * — false negatives are safe; false positives only show a soft warning.
 */
const LOCATION_LIKE_PATTERNS = [
  /\b(barrio|zona|partido|localidad|municipio|provincia|ciudad|capital|gran buenos aires|caba|gba)\b/i,
  /\b(villa|palermo|belgrano|caballito|flores|almagro|recoleta|san telmo|bernal|quilmes|tigre|san isidro|olivos|vicente l[oó]pez|mart[ií]nez|nu[ñn]ez|colegiales|urquiza|devoto|boedo)\b/i,
]

function looksLikeLocation(text: string): boolean {
  return LOCATION_LIKE_PATTERNS.some((re) => re.test(text))
}

// ──────────────────────────────────────────────────────────────────────────────
// Section wrapper — collapsible
// ──────────────────────────────────────────────────────────────────────────────

interface SectionProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string
  subtitle?: string
  defaultOpen?: boolean
  badge?: React.ReactNode
  children: React.ReactNode
}

function Section({ title, subtitle, defaultOpen = true, badge, children, className, ...rest }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div
      className={['bg-paper border border-line rounded-lg overflow-hidden', className].filter(Boolean).join(' ')}
      {...rest}
    >
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-pearl/60 transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm text-ink">{title}</span>
              {badge}
            </div>
            {subtitle && (
              <p className="text-xs text-ink-3 mt-0.5 truncate">{subtitle}</p>
            )}
          </div>
        </div>
        <span className="text-ink-4 text-xs ml-4 shrink-0">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="border-t border-line px-5 py-4">
          {children}
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Field grid row — label + value
// ──────────────────────────────────────────────────────────────────────────────

function FieldRow({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline gap-3 py-1.5 border-b border-line last:border-0">
      <dt className="text-xs text-ink-3 w-36 shrink-0 uppercase tracking-wide">{label}</dt>
      <dd className={['text-sm text-ink flex-1 min-w-0', mono ? 'font-mono' : ''].filter(Boolean).join(' ')}>
        {value ?? <span className="text-ink-4">—</span>}
      </dd>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Empty state
// ──────────────────────────────────────────────────────────────────────────────

function Empty({ message }: { message: string }) {
  return (
    <p className="text-sm text-ink-3 py-2 px-1">{message}</p>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Section A: Base lead record
// ──────────────────────────────────────────────────────────────────────────────

function LeadRecordSection({ lead }: { lead: ReturnType<typeof useLead>['data'] & object }) {
  return (
    <Section title="Lead Record" subtitle="Stored base fields">
      <dl className="divide-y divide-line">
        <FieldRow label="ID" value={lead.id} mono />
        <FieldRow label="Name" value={lead.name} />
        <FieldRow label="Phone" value={lead.phone} mono />
        <FieldRow label="Email" value={lead.email ?? <span className="text-ink-4">not stored</span>} />
        <FieldRow label="Status" value={<Badge status={lead.status as LeadStatus}>{lead.status.replace('_', ' ')}</Badge>} />
        <FieldRow label="Call count" value={lead.call_count} />
        <FieldRow label="Last called" value={formatDate(lead.last_called_at)} />
        <FieldRow label="Next action" value={lead.next_action ?? <span className="text-ink-4">none</span>} />
        <FieldRow label="Next action at" value={formatDate(lead.next_action_at)} />
        <FieldRow label="Do not call" value={
          lead.do_not_call
            ? <span className="text-coral font-medium text-xs uppercase tracking-wide">Yes</span>
            : <span className="text-ink-4">No</span>
        } />
        <FieldRow label="Notes" value={lead.notes ?? <span className="text-ink-4">none</span>} />
        <FieldRow label="Interest level" value={lead.interest_level != null ? `${lead.interest_level}%` : null} />
        <FieldRow label="Created" value={formatDate(lead.created_at)} />
        <FieldRow label="Updated" value={formatDate(lead.updated_at)} />
      </dl>
    </Section>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Section B: Quote Readiness Fields
//
// Design intent:
//   - "Quote Readiness Fields" = only what the Qora agent can/should complete.
//     Required fields appear here with fill status.
//   - "Additional CRM-provided data" = context that arrives FROM the CRM and
//     is NEVER something the agent should collect or send back (e.g. current_insurance).
//     These are known context, not targets.
// ──────────────────────────────────────────────────────────────────────────────

function QuoteReadinessSection({ lead }: { lead: NonNullable<ReturnType<typeof useLead>['data']> }) {
  const quoteFields = lead.quote_fields ?? []
  const customFields = lead.custom_fields ?? {}

  // Readiness source of truth = crm.yaml quote_ready_fields, surfaced per-field as
  // in_quote_ready_fields. These are the only fields that count toward quoting.
  // Everything else is additional CRM-provided context the agent must NOT collect.
  const quoteReadyFields = quoteFields.filter(f => f.in_quote_ready_fields)
  const crmProvidedFields = quoteFields.filter(f => !f.in_quote_ready_fields)

  const hasMetadata = quoteFields.length > 0
  const filledReady = quoteReadyFields.filter(f => f.filled).length
  const totalReady = quoteReadyFields.length

  const rawOnly = !hasMetadata && Object.keys(customFields).length > 0

  const statusBadge = hasMetadata && totalReady > 0
    ? filledReady === totalReady
      ? <span className="text-[10px] font-mono text-teal bg-teal-faint border border-teal-line px-2 py-0.5 rounded-full">
          {filledReady}/{totalReady} required
        </span>
      : <span className="text-[10px] font-mono text-coral bg-coral-faint border border-coral-line px-2 py-0.5 rounded-full">
          {filledReady}/{totalReady} required
        </span>
    : undefined

  return (
    <Section
      title="Quote Readiness Fields"
      subtitle={
        hasMetadata
          ? "Fields the agent can complete for quoting"
          : rawOnly
          ? "Custom fields (no CRM metadata available)"
          : "No custom fields captured yet"
      }
      badge={statusBadge}
      data-testid="quote-readiness-section"
    >
      {hasMetadata ? (
        <div className="space-y-4">
          {/* Quote-ready fields — the agent's targets (from quote_ready_fields) */}
          {quoteReadyFields.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-widest text-ink-3 mb-2">
                Fields for Quoting
              </p>
              <div className="space-y-1.5">
                {quoteReadyFields.map((field: QuoteField) => (
                  <QuoteFieldRow key={field.field_key} field={field} />
                ))}
              </div>
            </div>
          )}

          {/* CRM-provided optional fields — known context, not targets */}
          {crmProvidedFields.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <p className="text-[10px] font-mono uppercase tracking-widest text-ink-3">
                  Additional CRM-provided data
                </p>
                <span
                  data-testid="crm-provided-tooltip"
                  className="text-[10px] text-ink-4 border border-dashed border-line-2 px-1.5 py-0.5 rounded"
                  title="This data arrives from the CRM as known context. The Qora agent receives it but should not attempt to collect or send it back."
                >
                  context only — agent does not collect these
                </span>
              </div>
              <div className="space-y-1.5">
                {crmProvidedFields.map((field: QuoteField) => (
                  <QuoteFieldRow key={field.field_key} field={field} isCrmProvided />
                ))}
              </div>
            </div>
          )}
        </div>
      ) : rawOnly ? (
        <dl className="divide-y divide-line">
          {Object.entries(customFields).map(([key, value]) => (
            <FieldRow key={key} label={formatCustomFieldKey(key)} value={value || <span className="text-ink-4">empty</span>} mono />
          ))}
        </dl>
      ) : (
        <Empty message="No custom fields captured yet." />
      )}
    </Section>
  )
}

function QuoteFieldRow({ field, isCrmProvided = false }: { field: QuoteField; isCrmProvided?: boolean }) {
  // Inside "Fields for Quoting", readiness (in_quote_ready_fields) drives the
  // missing-field emphasis — not the legacy write-validation `required` flag.
  const isQuoteReady = field.in_quote_ready_fields
  return (
    <div
      className={[
        'flex items-center gap-3 rounded-md px-3 py-2 border',
        isCrmProvided
          ? 'border-line bg-mist'
          : field.filled
          ? 'border-line bg-paper'
          : isQuoteReady
          ? 'border-coral-line bg-coral-faint'
          : 'border-line bg-mist',
      ].join(' ')}
    >
      {/* Fill indicator */}
      <div className={[
        'w-1.5 h-1.5 rounded-full shrink-0',
        isCrmProvided ? 'bg-ink-3' : field.filled ? 'bg-teal' : isQuoteReady ? 'bg-coral' : 'bg-ink-4',
      ].join(' ')} />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-ink">{field.label}</span>
          {!isCrmProvided && isQuoteReady && (
            <span className="text-[10px] font-mono text-ink-3 uppercase tracking-wide">required</span>
          )}
          {isCrmProvided && (
            <span className="text-[10px] font-mono text-ink-4 uppercase tracking-wide">crm-provided</span>
          )}
          <span className="text-[10px] font-mono text-ink-4">{field.field_type}</span>
        </div>
        <div className="text-xs font-mono text-ink-3 mt-0.5">{field.field_key}</div>
      </div>

      <div className="text-sm font-mono text-ink min-w-[100px] text-right">
        {field.current_value !== null && field.current_value !== undefined
          ? field.current_value
          : <span className="text-ink-4 text-xs">not set</span>
        }
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Section C: Qora memory — profile facts (structured parsing) + interest history
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Detect mismatch: a lifestyle/profile fact looks like a location but the
 * structured `zona` quote field is not set. This is a soft heuristic — only
 * show when we can be reasonably confident. Don't autocorrect.
 */
function ZonaMismatchWarning({
  profileFacts,
  quoteFields,
}: {
  profileFacts: Record<string, string[]>
  quoteFields: QuoteField[]
}) {
  const zonaField = quoteFields.find(f => f.field_key === 'zona')
  // Only meaningful when this client actually configures a `zona` quote field.
  // If there's no zona field, there's nothing to be "not set" — no warning.
  if (!zonaField) return null
  if (zonaField.filled) return null // zona already set — no mismatch

  // Look for location-like facts in profile namespace
  let locationFact: string | null = null
  for (const [namespace, facts] of Object.entries(profileFacts)) {
    if (namespace.toLowerCase().includes('profile') || namespace.toLowerCase().includes('lifestyle')) {
      for (const rawFact of facts) {
        const parsed = parseProfileFact(rawFact)
        const textToCheck = parsed ? `${parsed.fact} ${parsed.category}` : rawFact
        if (looksLikeLocation(textToCheck)) {
          locationFact = parsed ? parsed.fact : rawFact
          break
        }
      }
    }
    if (locationFact) break
  }

  if (!locationFact) return null

  return (
    <div
      data-testid="zona-mismatch-warning"
      className="flex items-start gap-2.5 rounded-md border border-amber-200/70 bg-amber-50/60 px-3 py-2.5 text-xs mt-3"
    >
      <span className="text-amber-500 shrink-0 mt-0.5">⚠</span>
      <div>
        <p className="text-ink font-medium">Data consistency: location in memory, zona not structured</p>
        <p className="text-ink-3 mt-0.5">
          Profile memory contains "{locationFact}" which looks like a location, but the{' '}
          <span className="font-mono">zona</span> structured field has no value.
          This is a data-capture gap — the correct fix is to update the lead's structured data
          via post-call corrections, not an agent behavior issue.
        </p>
      </div>
    </div>
  )
}

/**
 * Render a single profile fact row — structured if parseable, raw string fallback.
 * Source labeling is at group header level (MemorySection), not per item.
 */
function ProfileFactItem({ raw }: { raw: string }) {
  const parsed = parseProfileFact(raw)

  if (!parsed) {
    // Raw string fallback
    return (
      <div
        data-testid="profile-fact-item"
        className="rounded-md border border-line bg-pearl px-3 py-2.5 space-y-1.5"
      >
        <p className="text-xs text-ink font-mono break-words">{raw}</p>
      </div>
    )
  }

  const confidenceColor =
    parsed.confidence === 'high' ? 'text-teal' :
    parsed.confidence === 'medium' ? 'text-ink-2' :
    'text-ink-4'

  return (
    <div
      data-testid="profile-fact-item"
      className="rounded-md border border-line bg-pearl px-3 py-2.5 space-y-1.5"
    >
      {/* Row 1: category + confidence (no per-item source badge — source is at group header) */}
      <div className="flex items-center gap-2 flex-wrap">
        {parsed.category && (
          <span
            data-testid="fact-category"
            className="text-[10px] font-mono text-ink-2 px-1.5 py-0.5 rounded bg-mist border border-line uppercase tracking-wide"
          >
            {parsed.category}
          </span>
        )}
        {parsed.confidence && (
          <span
            data-testid="fact-confidence"
            className={['text-[10px] font-mono uppercase tracking-wide', confidenceColor].join(' ')}
          >
            {parsed.confidence} confidence
          </span>
        )}
      </div>

      {/* Row 2: Fact text */}
      <p data-testid="fact-text" className="text-sm text-ink">{parsed.fact}</p>

      {/* Row 3: Evidence (quote from transcript) */}
      {parsed.evidence && (
        <p
          data-testid="fact-evidence"
          className="text-xs text-ink-3 italic border-l-2 border-line-2 pl-2 break-words"
        >
          "{parsed.evidence}"
        </p>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// DetectedInterestsRanking — table: interest, #, category
// Spec: cubora-accumulated-dimension-rankings
// ──────────────────────────────────────────────────────────────────────────────

export function DetectedInterestsRanking({ interests }: { interests: DetectedInterestRollup[] }) {
  if (interests.length === 0) {
    return <Empty message="No detected interests across calls yet." />
  }

  return (
    <div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-ink-3 uppercase tracking-wide border-b border-line">
            <th className="text-left pb-1.5 font-medium">Interest</th>
            <th className="text-right pb-1.5 font-medium w-10">#</th>
            <th className="text-left pb-1.5 font-medium pl-3">Category</th>
          </tr>
        </thead>
        <tbody>
          {interests.map((row) => (
            <tr
              key={row.interest}
              data-testid="interest-ranking-row"
              className="border-b border-line last:border-0"
            >
              <td className="py-1.5 font-mono text-ink-2">{resolveLabel(row.interest, 'es')}</td>
              <td className="py-1.5 text-right font-mono font-medium text-ink">{row.count}</td>
              <td className="py-1.5 pl-3">
                <span className="text-[10px] font-mono uppercase tracking-wide text-ink-3 px-1.5 py-0.5 rounded bg-mist border border-line">
                  {row.category}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// ServiceIssuesRanking — table: issue, #, strength
// Spec: cubora-accumulated-dimension-rankings
// ──────────────────────────────────────────────────────────────────────────────

const STRENGTH_STYLES: Record<string, string> = {
  high: 'text-coral bg-coral-faint border-coral-line',
  medium: 'text-amber-600 bg-amber-50 border-amber-200',
  low: 'text-ink-3 bg-mist border-line',
}

export function ServiceIssuesRanking({ issues }: { issues: ServiceIssueRollup[] }) {
  if (issues.length === 0) {
    return <Empty message="No service issues recorded across calls yet." />
  }

  return (
    <div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-ink-3 uppercase tracking-wide border-b border-line">
            <th className="text-left pb-1.5 font-medium">Issue</th>
            <th className="text-right pb-1.5 font-medium w-10">#</th>
            <th className="text-left pb-1.5 font-medium pl-3">Strength</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((row) => (
            <tr
              key={row.issue}
              data-testid="issue-ranking-row"
              className="border-b border-line last:border-0"
            >
              <td className="py-1.5 font-mono text-ink-2">{resolveLabel(row.issue, 'es')}</td>
              <td className="py-1.5 text-right font-mono font-medium text-ink">{row.count}</td>
              <td className="py-1.5 pl-3">
                <span
                  className={[
                    'text-[10px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded border',
                    STRENGTH_STYLES[row.strength] ?? STRENGTH_STYLES.low,
                  ].join(' ')}
                >
                  {row.strength}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MemorySection({
  lead,
  clientId,
}: {
  lead: NonNullable<ReturnType<typeof useLead>['data']>
  clientId: string
}) {
  const profileFacts = lead.profile_facts ?? {}
  const interestHistory = lead.interest_history ?? []
  const quoteFields = lead.quote_fields ?? []
  const hasProfile = Object.keys(profileFacts).length > 0
  const hasInterest = interestHistory.length > 0
  const hasSummary = Boolean(lead.summary_last_call)

  const { data: rollups } = useLeadDimensionRollups(clientId, lead.id)

  return (
    <Section
      title="Accumulated Facts"
      subtitle="Profile, interests, service issues, and history from calls"
      defaultOpen={hasProfile || hasInterest || hasSummary}
    >
      {/* Mismatch warning */}
      <ZonaMismatchWarning profileFacts={profileFacts} quoteFields={quoteFields} />

      {/* Sub-section: Profile — profile facts by namespace (structured rendering)
          Source is stated once at group header, not repeated per item. */}
      <div className="mt-3">
        <div className="flex items-center gap-2 mb-1">
          <p className="text-xs text-ink-3 uppercase tracking-wide">Profile</p>
          {/* Single group-level source label — not repeated per item */}
          <span
            data-testid="fact-dimension-source"
            className="text-[10px] text-ink-4 font-mono"
            title="All facts below come from the post-call analysis pipeline, stored under profile_facts"
          >
            source: post-call analysis · profile_facts
          </span>
        </div>
        {hasProfile ? (
          <div className="space-y-3">
            {Object.entries(profileFacts).map(([namespace, facts]) => (
              <div key={namespace}>
                <p className="text-[10px] font-mono uppercase tracking-widest text-ink-3 mb-1.5">
                  {namespace}
                </p>
                <div className="space-y-1.5">
                  {(Array.isArray(facts) ? facts : [facts]).map((fact: unknown, i: number) => (
                    <ProfileFactItem key={i} raw={String(fact)} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty message="No profile facts stored yet." />
        )}
      </div>

      {/* Sub-section: Detected Interests Ranking */}
      <div className="mt-4">
        <p className="text-xs text-ink-3 uppercase tracking-wide mb-2">Detected Interests</p>
        <DetectedInterestsRanking interests={rollups?.detected_interests ?? []} />
      </div>

      {/* Sub-section: Service Issues Ranking */}
      <div className="mt-4">
        <p className="text-xs text-ink-3 uppercase tracking-wide mb-2">Service Issues</p>
        <ServiceIssuesRanking issues={rollups?.service_issues ?? []} />
      </div>

      {/* Sub-section: Objections Rollup (from call_analyses, not extracted_facts) */}
      {rollups && rollups.objections.length > 0 && (
        <div className="mt-4">
          <p className="text-xs text-ink-3 uppercase tracking-wide mb-2">Objections by Category</p>
          <div className="space-y-1">
            {rollups.objections.map(({ category, count }) => (
              <div
                key={category}
                data-testid="objection-rollup-row"
                className="flex items-center gap-3 rounded-md border border-line bg-pearl px-3 py-2"
              >
                <span className="text-xs font-mono text-ink-2 flex-1">{resolveLabel(category, 'es')}</span>
                <span className="text-xs font-mono text-ink font-medium w-8 text-right">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sub-section: Pain Points Rollup (from call_analyses, not extracted_facts) */}
      {rollups && rollups.pain_points.length > 0 && (
        <div className="mt-4">
          <p className="text-xs text-ink-3 uppercase tracking-wide mb-2">Pain Points by Category</p>
          <div className="space-y-1">
            {rollups.pain_points.map(({ category, count }) => (
              <div
                key={category}
                data-testid="pain-rollup-row"
                className="flex items-center gap-3 rounded-md border border-line bg-pearl px-3 py-2"
              >
                <span className="text-xs font-mono text-ink-2 flex-1">{resolveLabel(category, 'es')}</span>
                <span className="text-xs font-mono text-ink font-medium w-8 text-right">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sub-section: Interest history */}
      {hasInterest && (
        <div className="mt-4">
          <p className="text-xs text-ink-3 uppercase tracking-wide mb-2">Interest History</p>
          <div className="flex items-center gap-1.5 flex-wrap">
            {[...interestHistory].reverse().map((entry: { interest_level: number; recorded_at: string | null }, i: number) => (
              <div
                key={i}
                className="flex flex-col items-center"
                title={entry.recorded_at ? new Date(entry.recorded_at).toLocaleString() : ''}
              >
                <div
                  className="w-8 h-8 rounded-full border-2 border-line flex items-center justify-center text-[10px] font-mono font-medium"
                  style={{
                    background: `hsl(${entry.interest_level * 1.6}, 60%, ${90 - entry.interest_level * 0.3}%)`,
                    color: entry.interest_level > 50 ? '#0E4E45' : '#767880',
                    borderColor: entry.interest_level > 70 ? 'rgba(26,139,122,0.28)' : 'rgba(14,18,23,0.08)',
                  }}
                >
                  {entry.interest_level}
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-ink-4 mt-1.5">Earliest → latest</p>
        </div>
      )}

      {/* Last call summary */}
      {lead.summary_last_call && (
        <div className="mt-4 rounded-md border border-line bg-pearl px-3 py-2.5">
          <p className="text-[10px] font-mono uppercase tracking-widest text-ink-3 mb-1">Last call summary</p>
          <p className="text-sm text-ink">{lead.summary_last_call}</p>
        </div>
      )}
    </Section>
  )
}

// DimensionRollupsSection and buildCategoryRollup removed.
// Rollup data is now sourced from call_analyses via useLeadDimensionRollups hook
// and embedded inside MemorySection (Accumulated Facts).
// See: cubora-accumulated-dimension-rankings

// ──────────────────────────────────────────────────────────────────────────────
// Section D: Call history (right column)
// ──────────────────────────────────────────────────────────────────────────────

function CallHistorySection({
  sessions,
  loading,
  error,
  expandedSessionId,
  onToggle,
}: {
  sessions: ReturnType<typeof useCallSessions>['data']
  loading: boolean
  error: boolean
  expandedSessionId: string | null
  onToggle: (id: string) => void
}) {
  const count = sessions?.length ?? 0
  const badge = count > 0
    ? <span className="text-[10px] font-mono text-ink-3 bg-mist border border-line px-2 py-0.5 rounded-full">{count}</span>
    : undefined

  return (
    <Section title="Call History" subtitle="Sessions with analysis" badge={badge}>
      {loading ? (
        <div className="py-4 text-center">
          <span className="text-ink-3 text-sm animate-pulse">Loading calls…</span>
        </div>
      ) : error ? (
        <p className="text-sm text-coral py-2">Unable to load call history. Please try again.</p>
      ) : (
        <CallHistoryList
          sessions={sessions ?? []}
          expandedSessionId={expandedSessionId}
          onToggleSession={onToggle}
        />
      )}
    </Section>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Section E: CRM / Airtable mapping (left column)
// ──────────────────────────────────────────────────────────────────────────────

function CRMSection({
  lead,
  clientId,
}: {
  lead: NonNullable<ReturnType<typeof useLead>['data']>
  clientId: string
}) {
  const { data: integrations } = useIntegrations(clientId)
  const integration = integrations?.[0]

  const hasExternalLink = Boolean(lead.external_crm_id || lead.external_lead_id)

  return (
    <Section
      title="Client CRM / Airtable"
      subtitle="External IDs and field mapping"
      defaultOpen={hasExternalLink}
    >
      {/* External IDs */}
      <div className="mb-4">
        <p className="text-xs text-ink-3 uppercase tracking-wide mb-2">External Identifiers</p>
        <dl className="divide-y divide-line rounded-md border border-line overflow-hidden">
          <FieldRow
            label="External CRM ID"
            value={
              lead.external_crm_id
                ? <span className="font-mono">{lead.external_crm_id}</span>
                : <span className="text-ink-4 text-xs">not synced</span>
            }
          />
          <FieldRow
            label="External Lead ID"
            value={
              lead.external_lead_id != null
                ? <span className="font-mono">{lead.external_lead_id}</span>
                : <span className="text-ink-4 text-xs">not set</span>
            }
          />
        </dl>
        {/* Honest sync copy — no fake sync button */}
        <p className="text-xs text-ink-4 mt-1.5">
          No last-sync timestamp stored — only external IDs are available.
        </p>
      </div>

      {/* Field mappings from integration config */}
      {integration ? (
        <div>
          <p className="text-xs text-ink-3 uppercase tracking-wide mb-2">
            Field Mappings — {integration.provider} ({integration.table_id})
          </p>
          {integration.field_mappings && integration.field_mappings.length > 0 ? (
            <div className="space-y-1">
              {integration.field_mappings.map((mapping) => (
                <div
                  key={mapping.source}
                  className="flex items-center gap-2 text-xs rounded-md border border-line bg-pearl px-3 py-2"
                >
                  <span className="font-mono text-ink-2 w-32 shrink-0">{mapping.source}</span>
                  <span className="text-ink-4 shrink-0">→</span>
                  <span className="font-mono text-ink flex-1">{mapping.target}</span>
                  <span className="text-ink-4 font-mono shrink-0">{mapping.type}</span>
                  {mapping.required && (
                    <span className="text-[10px] text-coral uppercase tracking-wide shrink-0">required</span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <Empty message="No field mappings configured." />
          )}
        </div>
      ) : (
        <p className="text-xs text-ink-4 mt-2">No CRM integration configured for this client.</p>
      )}
    </Section>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Section F: Next-call context preview (right column)
// ──────────────────────────────────────────────────────────────────────────────

function ContextBlock({ label, content }: { label: string; content: string }) {
  return (
    <div className="rounded-md border border-line overflow-hidden">
      <div className="px-3 py-1.5 bg-pearl border-b border-line">
        <span className="text-[10px] font-mono uppercase tracking-widest text-ink-3">{label}</span>
      </div>
      <pre className="px-3 py-2.5 text-xs font-mono text-ink whitespace-pre-wrap break-words bg-paper leading-relaxed max-h-48 overflow-y-auto">
        {content || <span className="text-ink-4">(empty)</span>}
      </pre>
    </div>
  )
}

function ContextPreviewSection({
  clientId,
  leadId,
}: {
  clientId: string
  leadId: string
}) {
  const [loaded, setLoaded] = useState(false)
  const { data, isLoading, isError } = useLeadContextPreview(clientId, leadId, loaded)

  if (!loaded) {
    return (
      <Section title="Next-Call Context Preview" subtitle="Literal context blocks the agent will receive" defaultOpen={false}>
        <button
          type="button"
          onClick={() => setLoaded(true)}
          className="text-sm text-teal hover:underline"
        >
          Load context preview →
        </button>
      </Section>
    )
  }

  const preview = data as LeadContextPreview | undefined

  return (
    <Section
      title="Next-Call Context Preview"
      subtitle="Literal context blocks the agent will receive"
      defaultOpen
    >
      {isLoading && (
        <span className="text-sm text-ink-3 animate-pulse">Assembling context…</span>
      )}

      {isError && (
        <p className="text-sm text-coral">Failed to load context preview. Check that an agent exists for this client.</p>
      )}

      {preview && (
        <div className="space-y-3">
          {/* System prompt indicator */}
          <div className="flex items-center gap-3 rounded-md border border-line px-3 py-2.5 bg-pearl">
            <div className={['w-2 h-2 rounded-full shrink-0', preview.system_prompt_present ? 'bg-teal' : 'bg-ink-4'].join(' ')} />
            <span className="text-xs font-mono text-ink">
              System prompt:{' '}
              <span className={preview.system_prompt_present ? 'text-teal' : 'text-ink-4'}>
                {preview.system_prompt_present ? 'present, not shown' : 'not configured'}
              </span>
            </span>
          </div>

          {/* Agent / call metadata */}
          <div className="flex items-center gap-4 text-xs text-ink-3 font-mono">
            <span>Call #{preview.call_number}</span>
            <span>·</span>
            <span>{preview.is_returning_caller ? 'Returning caller' : 'First call'}</span>
          </div>

          {preview.error && (
            <div className="rounded-md border border-coral-line bg-coral-faint px-3 py-2 text-xs text-coral font-mono">
              {preview.error}
            </div>
          )}

          {/* Context blocks */}
          {preview.lead_profile
            ? <ContextBlock label="Lead Profile" content={preview.lead_profile} />
            : <div className="rounded-md border border-line px-3 py-2 text-xs text-ink-4 font-mono">Lead profile: empty (name/car data missing)</div>
          }

          {preview.call_history
            ? <ContextBlock label="Call History" content={preview.call_history} />
            : <div className="rounded-md border border-line px-3 py-2 text-xs text-ink-4 font-mono">Call history: none stored</div>
          }

          {preview.misc_notes
            ? <ContextBlock label="Misc Notes" content={preview.misc_notes} />
            : <div className="rounded-md border border-line px-3 py-2 text-xs text-ink-4 font-mono">Misc notes: none</div>
          }

          {preview.skills_index
            ? <ContextBlock label="Skills Index" content={preview.skills_index} />
            : <div className="rounded-md border border-line px-3 py-2 text-xs text-ink-4 font-mono">Skills index: no registry configured</div>
          }

          {preview.tools && preview.tools.length > 0 && (
            <div className="rounded-md border border-line px-3 py-2">
              <p className="text-[10px] font-mono uppercase tracking-widest text-ink-3 mb-2">Enabled Tools</p>
              <div className="flex flex-wrap gap-1.5">
                {preview.tools.map(tool => (
                  <span key={tool} className="text-xs font-mono px-2 py-0.5 rounded-full bg-mist border border-line text-ink-2">
                    {tool}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Section>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// LeadDetailPage — two-column layout
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

  if (leadLoading) {
    return (
      <div data-testid="lead-loading" className="space-y-4">
        <div className="h-8 bg-mist rounded-md animate-pulse w-1/3" />
        <div className="h-32 bg-mist rounded-md animate-pulse" />
      </div>
    )
  }

  if (leadError || !lead) {
    return (
      <div data-testid="lead-error" role="alert" className="p-8 text-center space-y-4">
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
    <div className="space-y-3">
      {/* Back navigation */}
      <button
        type="button"
        onClick={() => navigate(`/app/${clientId}/leads`)}
        className="text-sm text-ink-3 hover:text-ink transition-colors"
      >
        ← Leads
      </button>

      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-1">
        <div>
          <h1 className="font-display text-2xl font-medium text-ink">{lead.name}</h1>
          <p className="text-ink-3 text-sm mt-0.5 font-mono">{lead.phone}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {lead.do_not_call && <Badge status="error">Do Not Call</Badge>}
          <Badge status={lead.status as LeadStatus}>{lead.status.replace('_', ' ')}</Badge>
        </div>
      </div>

      {/* Two-column grid: left=main info, right=call context (sticky on xl+)
          Right column gets ≥560px at xl so badges have room to breathe. */}
      <div
        data-testid="detail-two-column"
        className="grid grid-cols-1 xl:grid-cols-[1fr_minmax(0,560px)] gap-4 items-start"
      >
        {/* ── Left column: Lead record + fields + memory + CRM ── */}
        <div className="space-y-3 min-w-0">
          {/* Section A: Lead record */}
          <LeadRecordSection lead={lead} />

          {/* Section B: Quote readiness fields */}
          <QuoteReadinessSection lead={lead} />

          {/* Section C: Accumulated Facts (profile, rankings, rollups) */}
          <MemorySection lead={lead} clientId={clientId ?? ''} />

          {/* Section E: CRM / Airtable */}
          <CRMSection lead={lead} clientId={clientId ?? ''} />
        </div>

        {/* ── Right column: Call history + context preview (sticky sidebar) ── */}
        <div className="space-y-3 min-w-0 xl:sticky xl:top-24">
          {/* Section D: Call history */}
          <CallHistorySection
            sessions={sessions}
            loading={sessionsLoading}
            error={sessionsError}
            expandedSessionId={expandedSessionId}
            onToggle={handleToggleSession}
          />

          {/* Section F: Next-call context preview */}
          <ContextPreviewSection clientId={clientId ?? ''} leadId={leadId ?? ''} />
        </div>
      </div>
    </div>
  )
}
