/**
 * LeadDetailPage (design: screens-lead.jsx `Lead`)
 *
 * Header (avatar, name, status, phone, can-call, updated) + "Copiar link" +
 * "Llamar ahora" (real trigger, same CallNowCell as the table) + KPI strip +
 * tabs (Memoria / Cotización / Registro / CRM / Próxima llamada) + right rail
 * call timeline that opens the real CallDrawer.
 *
 * Every capability of the previous 1116-line page is preserved — mapped here:
 *   Lead record            → Registro tab
 *   Quote readiness fields  → Cotización tab
 *   Qora memory / rollups   → Memoria tab
 *   CRM / Airtable mapping  → CRM tab
 *   Call history            → right rail timeline + CallDrawer
 *   Next-call context prev. → Próxima llamada tab
 */

import { useState } from 'react'
import { useParams, useNavigate } from 'react-router'
import {
  useLead,
  useCallSessions,
  useLeadContextPreview,
  useIntegrations,
  useLeadDimensionRollups,
  useFeature,
} from '@/api/hooks'
import type {
  LeadStatus,
  QuoteField,
  LeadContextPreview,
  DetectedInterestRollup,
  ServiceIssueRollup,
  CallSession,
} from '@/api/types'
import { resolveLabel } from '@/config/dimension-labels'
import { parseUTC } from '@/lib/parse-utc'
import { Icon } from '@/design/components'
import { CallHistoryList } from './call-history-list'
import { CallDrawer } from './call-drawer'
import { CallNowCell, PLAN_EXCLUDES_OUTBOUND } from './call-now-cell'
import { LeadStatusTag, initials } from './lead-table'

const REALTIME_INTERVAL_MS = 15_000

// ──────────────────────────────────────────────────────────────────────────────
// Pure helpers
// ──────────────────────────────────────────────────────────────────────────────

const DATE_FMT = new Intl.DateTimeFormat('es-AR', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

function formatDate(isoOrNull: string | null | undefined): string {
  if (!isoOrNull) return '—'
  try {
    return DATE_FMT.format(parseUTC(isoOrNull))
  } catch {
    return isoOrNull
  }
}

function formatCustomFieldKey(key: string): string {
  return key.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function parseProfileFact(raw: string): { category: string; fact: string; evidence: string; confidence: string } | null {
  if (!raw || typeof raw !== 'string') return null
  const trimmed = raw.trim()
  if (!trimmed.startsWith('{')) return null
  try {
    const parsed = JSON.parse(trimmed)
    if (typeof parsed === 'object' && parsed !== null && typeof parsed.fact === 'string') {
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

const LOCATION_LIKE_PATTERNS = [
  /\b(barrio|zona|partido|localidad|municipio|provincia|ciudad|capital|gran buenos aires|caba|gba)\b/i,
  /\b(villa|palermo|belgrano|caballito|flores|almagro|recoleta|san telmo|bernal|quilmes|tigre|san isidro|olivos|vicente l[oó]pez|mart[ií]nez|nu[ñn]ez|colegiales|urquiza|devoto|boedo)\b/i,
]

function looksLikeLocation(text: string): boolean {
  return LOCATION_LIKE_PATTERNS.some((re) => re.test(text))
}

const CONF_LEVEL: Record<string, number> = { low: 1, medium: 2, high: 3 }

function Spark({ values }: { values: number[] }) {
  if (values.length < 2) return null
  const w = 84
  const h = 26
  const max = Math.max(50, ...values)
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (w - 6) + 3, h - 3 - (v / max) * (h - 6)])
  return (
    <svg width={w} height={h} style={{ overflow: 'visible' }}>
      <polyline points={pts.map((p) => p.join(',')).join(' ')} fill="none" stroke="var(--qd-ink-4)" strokeWidth={1.5} strokeLinejoin="round" />
      {pts.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r={2.6} fill={i === pts.length - 1 ? 'var(--qd-ink)' : 'var(--qd-surface)'} stroke="var(--qd-ink-3)" strokeWidth={1.2} />
      ))}
    </svg>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Field grid row (Registro tab)
// ──────────────────────────────────────────────────────────────────────────────

function FieldRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <>
      <div className="k">{label}</div>
      <div>{value ?? <span className="muted">—</span>}</div>
    </>
  )
}

function Empty({ message }: { message: string }) {
  return <p className="muted" style={{ fontSize: 13 }}>{message}</p>
}

// ──────────────────────────────────────────────────────────────────────────────
// Registro tab — base lead record
// ──────────────────────────────────────────────────────────────────────────────

function RegistroTab({ lead }: { lead: NonNullable<ReturnType<typeof useLead>['data']> }) {
  return (
    <section className="card">
      <div className="card-h"><div><h3>Registro</h3><p>Campos base guardados en Qora</p></div></div>
      <div className="card-b kv">
        <FieldRow label="ID" value={<span className="mono" style={{ fontSize: 12.5, wordBreak: 'break-all' }}>{lead.id}</span>} />
        <FieldRow label="Nombre" value={lead.name} />
        <FieldRow label="Teléfono" value={<span className="mono">{lead.phone}</span>} />
        <FieldRow label="Email" value={lead.email ?? undefined} />
        <FieldRow label="Estado" value={<LeadStatusTag status={lead.status as LeadStatus} />} />
        <FieldRow label="Llamadas" value={<span className="num">{lead.call_count}</span>} />
        <FieldRow label="Última llamada" value={lead.last_called_at ? formatDate(lead.last_called_at) : 'Nunca'} />
        <FieldRow label="Próxima acción" value={lead.next_action ?? undefined} />
        <FieldRow label="Fecha próx. acción" value={lead.next_action_at ? formatDate(lead.next_action_at) : undefined} />
        <FieldRow label="No llamar" value={lead.do_not_call ? 'Sí' : 'No'} />
        <FieldRow label="Notas" value={lead.notes ?? undefined} />
        <FieldRow label="Nivel de interés" value={lead.interest_level != null ? `${lead.interest_level}%` : undefined} />
        <FieldRow label="Creado" value={formatDate(lead.created_at)} />
        <FieldRow label="Actualizado" value={formatDate(lead.updated_at)} />
      </div>
    </section>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Cotización tab — Quote Readiness Fields (real quote_fields, no fake save)
// ──────────────────────────────────────────────────────────────────────────────

function QuoteFieldRow({ field, isCrmProvided = false }: { field: QuoteField; isCrmProvided?: boolean }) {
  const isQuoteReady = field.in_quote_ready_fields
  return (
    <div className="field">
      <div className="n">
        <i className={'dot' + (field.filled ? ' live' : isCrmProvided ? '' : ' coral')} style={{ boxShadow: 'none' }} />
        <b>{field.label}</b>
        <code>{field.field_key} · {field.field_type}</code>
        {!isCrmProvided && isQuoteReady && <span className="tag mono">Obligatorio</span>}
        {isCrmProvided && <span className="tag ghost mono">Del CRM</span>}
      </div>
      <div className="mono" style={{ textAlign: 'right', fontSize: 13.5 }}>
        {field.current_value ?? <span className="muted" style={{ fontSize: 12.5 }}>Sin completar</span>}
      </div>
    </div>
  )
}

function CotizacionTab({ lead }: { lead: NonNullable<ReturnType<typeof useLead>['data']> }) {
  const quoteFields = lead.quote_fields ?? []
  const customFields = lead.custom_fields ?? {}
  const quoteReadyFields = quoteFields.filter((f) => f.in_quote_ready_fields)
  const crmProvidedFields = quoteFields.filter((f) => !f.in_quote_ready_fields)
  const hasMetadata = quoteFields.length > 0
  const filled = quoteReadyFields.filter((f) => f.filled).length
  const total = quoteReadyFields.length
  const rawOnly = !hasMetadata && Object.keys(customFields).length > 0

  return (
    <section className="card" data-testid="quote-readiness-section">
      <div className="card-h">
        <div>
          <h3>Datos para cotizar</h3>
          <p>El agente intenta completarlos en cada llamada. Datos de solo lectura — no hay endpoint de edición.</p>
        </div>
        {total > 0 && <div className="r mono num" style={{ fontSize: 12 }}>{filled}/{total}</div>}
      </div>
      {hasMetadata ? (
        <div>
          {quoteReadyFields.map((f) => <QuoteFieldRow key={f.field_key} field={f} />)}
          {crmProvidedFields.length > 0 && (
            <div style={{ borderTop: '1px solid var(--qd-line)', padding: '16px 20px 4px' }}>
              <div className="sec-l" data-testid="crm-provided-tooltip" title="Contexto del CRM — el agente no lo pregunta ni lo envía de vuelta">
                Del CRM · solo contexto, el agente no lo pregunta
              </div>
            </div>
          )}
          {crmProvidedFields.map((f) => <QuoteFieldRow key={f.field_key} field={f} isCrmProvided />)}
        </div>
      ) : rawOnly ? (
        <div className="card-b kv">
          {Object.entries(customFields).map(([key, value]) => (
            <FieldRow key={key} label={formatCustomFieldKey(key)} value={value || <span className="muted">vacío</span>} />
          ))}
        </div>
      ) : (
        <div className="card-b"><Empty message="Todavía no hay campos personalizados." /></div>
      )}
    </section>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Memoria tab — profile facts + rollups (from useLeadDimensionRollups)
// ──────────────────────────────────────────────────────────────────────────────

function ZonaMismatchWarning({ profileFacts, quoteFields }: { profileFacts: Record<string, string[]>; quoteFields: QuoteField[] }) {
  const zonaField = quoteFields.find((f) => f.field_key === 'zona')
  if (!zonaField) return null
  if (zonaField.filled) return null

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
    <div data-testid="zona-mismatch-warning" className="alert">
      <Icon name="alert" size={18} />
      <div style={{ flex: 1 }}>
        <b>La zona está en la memoria pero no en los datos</b>
        <p>
          La memoria dice "{locationFact}", pero el campo estructurado <span className="mono">zona</span> está vacío.
          Es un hueco de captura de datos — corregilo con correcciones post-llamada, no es un error del agente.
        </p>
      </div>
    </div>
  )
}

function ProfileFactItem({ raw }: { raw: string }) {
  const parsed = parseProfileFact(raw)

  if (!parsed) {
    return (
      <div data-testid="profile-fact-item" className="row" style={{ alignItems: 'flex-start' }}>
        <p className="mono" style={{ fontSize: 12.5 }}>{raw}</p>
      </div>
    )
  }

  return (
    <div data-testid="profile-fact-item" className="row" style={{ alignItems: 'flex-start', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {parsed.category && <span data-testid="fact-category" className="tag mono">{parsed.category}</span>}
        {parsed.confidence && (
          <span data-testid="fact-confidence" className="conf" title={`Confianza ${parsed.confidence}`}>
            {[1, 2, 3].map((i) => (
              <i key={i} className={i <= (CONF_LEVEL[parsed.confidence] ?? 0) ? 'on' : ''} />
            ))}
          </span>
        )}
      </div>
      <div data-testid="fact-text">{parsed.fact}</div>
      {parsed.evidence && <div className="quote">"{parsed.evidence}"</div>}
    </div>
  )
}

export function DetectedInterestsRanking({ interests }: { interests: DetectedInterestRollup[] }) {
  if (interests.length === 0) return <Empty message="No detected interests across calls yet." />
  return (
    <table className="tbl">
      <thead><tr><th>Interest</th><th className="r">#</th><th>Category</th></tr></thead>
      <tbody>
        {interests.map((row) => (
          <tr key={row.interest} data-testid="interest-ranking-row">
            <td>{resolveLabel(row.interest, 'es')}</td>
            <td className="r num">{row.count}</td>
            <td><span className="tag mono">{row.category}</span></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function ServiceIssuesRanking({ issues }: { issues: ServiceIssueRollup[] }) {
  if (issues.length === 0) return <Empty message="No service issues recorded across calls yet." />
  return (
    <table className="tbl">
      <thead><tr><th>Issue</th><th className="r">#</th><th>Strength</th></tr></thead>
      <tbody>
        {issues.map((row) => (
          <tr key={row.issue} data-testid="issue-ranking-row">
            <td>{resolveLabel(row.issue, 'es')}</td>
            <td className="r num">{row.count}</td>
            <td><span className="tag mono">{row.strength}</span></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function MemoriaTab({ lead, clientId }: { lead: NonNullable<ReturnType<typeof useLead>['data']>; clientId: string }) {
  const profileFacts = lead.profile_facts ?? {}
  const interestHistory = lead.interest_history ?? []
  const quoteFields = lead.quote_fields ?? []
  const hasProfile = Object.keys(profileFacts).length > 0

  const {
    data: rollups,
    isError: rollupsError,
    isSuccess: rollupsSuccess,
    isPending: rollupsPending,
    isFetching: rollupsFetching,
  } = useLeadDimensionRollups(clientId, lead.id, { refetchInterval: REALTIME_INTERVAL_MS })
  const rollupsLoading = !rollupsSuccess && !rollupsError && (rollupsPending || rollupsFetching)

  return (
    <div className="stack">
      <ZonaMismatchWarning profileFacts={profileFacts} quoteFields={quoteFields} />

      {!lead.summary_last_call && (
        <section className="card"><div className="empty">Qora todavía no habló con {lead.name.split(' ')[0]}. La memoria se arma después de la primera llamada.</div></section>
      )}
      {lead.summary_last_call && (
        <section className="card card-b">
          <span className="eyebrow">Último resumen</span>
          <p style={{ margin: '12px 0 0', fontSize: 15, lineHeight: 1.6 }}>{lead.summary_last_call}</p>
        </section>
      )}

      <section className="card">
        <div className="card-h"><div><h3>Perfil</h3><p>Lo que Qora aprendió del lead · análisis post-llamada</p></div></div>
        <div className="card-b">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span
              data-testid="fact-dimension-source"
              className="muted mono"
              style={{ fontSize: 11 }}
              title="Todos los hechos vienen del pipeline de análisis post-llamada, guardados en profile_facts"
            >
              source: post-call analysis · profile_facts
            </span>
          </div>
          {hasProfile ? (
            <div className="stack" style={{ gap: 12 }}>
              {Object.entries(profileFacts).map(([namespace, facts]) => (
                <div key={namespace}>
                  <div className="sec-l">{namespace}</div>
                  <div className="rows">
                    {(Array.isArray(facts) ? facts : [facts]).map((fact, i) => <ProfileFactItem key={i} raw={String(fact)} />)}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty message="No profile facts stored yet." />
          )}
        </div>
      </section>

      {rollupsError ? (
        <section className="card card-b"><p data-testid="rollups-error" style={{ color: 'var(--qd-coral)', margin: 0 }}>No pudimos cargar los rankings acumulados.</p></section>
      ) : rollupsLoading ? (
        <section className="card card-b"><p data-testid="rollups-loading" className="muted" style={{ margin: 0 }}>Cargando rankings acumulados…</p></section>
      ) : (
        <>
          <section className="card">
            <div className="card-h"><div><h3>Intereses detectados</h3></div></div>
            <div className="card-b">
              <DetectedInterestsRanking interests={rollups?.detected_interests ?? []} />
            </div>
          </section>
          <section className="card">
            <div className="card-h"><div><h3>Problemas de servicio</h3></div></div>
            <div className="card-b">
              <ServiceIssuesRanking issues={rollups?.service_issues ?? []} />
            </div>
          </section>
        </>
      )}

      {!rollupsError && rollups && rollups.objections.length > 0 && (
        <section className="card">
          <div className="card-h"><div><h3>Objeciones por categoría</h3></div></div>
          <div className="card-b chips">
            {rollups.objections.map(({ category, count }) => (
              <span key={category} data-testid="objection-rollup-row" className="chip">{resolveLabel(category, 'es')}<b>{count}</b></span>
            ))}
          </div>
        </section>
      )}
      {!rollupsError && rollups && rollups.pain_points.length > 0 && (
        <section className="card">
          <div className="card-h"><div><h3>Dolores por categoría</h3></div></div>
          <div className="card-b chips">
            {rollups.pain_points.map(({ category, count }) => (
              <span key={category} data-testid="pain-rollup-row" className="chip">{resolveLabel(category, 'es')}<b>{count}</b></span>
            ))}
          </div>
        </section>
      )}

      {interestHistory.length > 0 && (
        <section className="card card-b">
          <div className="sec-l">Historial de interés</div>
          <Spark values={interestHistory.map((e) => e.interest_level)} />
        </section>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// CRM tab
// ──────────────────────────────────────────────────────────────────────────────

function CRMTab({ lead, clientId }: { lead: NonNullable<ReturnType<typeof useLead>['data']>; clientId: string }) {
  const { data: integrations } = useIntegrations(clientId)
  const integration = integrations?.[0]

  return (
    <section className="card">
      <div className="card-h">
        {integration ? <span className="avatar" style={{ borderRadius: 8, font: '600 11px/1 var(--qd-M)' }}>{integration.provider.slice(0, 2).toUpperCase()}</span> : null}
        <div><h3>{integration ? integration.provider.charAt(0).toUpperCase() + integration.provider.slice(1) : 'CRM'}</h3><p>IDs externos y mapeo de campos</p></div>
        <span className="r tag teal">{integration ? 'Conectado' : 'Sin integración'}</span>
      </div>
      <div className="card-b" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div className="kv">
          <FieldRow label="ID externo CRM" value={lead.external_crm_id ? <span className="mono">{lead.external_crm_id}</span> : undefined} />
          <FieldRow label="ID externo lead" value={lead.external_lead_id != null ? <span className="mono">{lead.external_lead_id}</span> : undefined} />
        </div>
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>No hay fecha de última sincronización guardada; solo están disponibles los IDs externos.</p>

        {integration ? (
          <div>
            <div className="sec-l">Mapeo de campos · {integration.table_id}</div>
            {integration.field_mappings && integration.field_mappings.length > 0 ? (
              <div className="tbl-wrap">
                <table className="tbl">
                  <thead><tr><th>Qora</th><th></th><th>{integration.provider}</th><th>Tipo</th><th></th></tr></thead>
                  <tbody>
                    {integration.field_mappings.map((m) => (
                      <tr key={m.source}>
                        <td className="mono">{m.source}</td>
                        <td className="muted"><Icon name="arrowR" size={14} /></td>
                        <td className="mono">{m.target}</td>
                        <td className="muted mono">{m.type}</td>
                        <td className="r">{m.required && <span className="tag mono">Obligatorio</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty message="No hay mapeos de campos configurados." />
            )}
          </div>
        ) : (
          <p className="muted" style={{ fontSize: 12.5 }}>No hay integración CRM configurada para este cliente.</p>
        )}
      </div>
    </section>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Próxima llamada tab — context preview
// ──────────────────────────────────────────────────────────────────────────────

function ContextBlock({ label, content }: { label: string; content: string }) {
  return (
    <div className="ctx">
      <b>{label}</b>
      {content || <span className="muted">(vacío)</span>}
    </div>
  )
}

function ProximaLlamadaTab({ clientId, leadId }: { clientId: string; leadId: string }) {
  const [loaded, setLoaded] = useState(false)
  const { data, isLoading, isError } = useLeadContextPreview(clientId, leadId, loaded)
  const preview = data as LeadContextPreview | undefined

  return (
    <section className="card">
      <div className="card-h"><div><h3>Contexto de la próxima llamada</h3><p>Bloques literales que va a recibir el agente</p></div></div>
      <div className="card-b" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {!loaded && (
          <button type="button" className="btn sm" onClick={() => setLoaded(true)}>Cargar vista previa de contexto →</button>
        )}
        {loaded && isLoading && <span className="muted">Ensamblando contexto…</span>}
        {loaded && isError && <p style={{ color: 'var(--qd-coral)' }}>Failed to load context preview. Check that an agent exists for this client.</p>}
        {loaded && preview && (
          <>
            <div className="row">
              <i className={'dot' + (preview.system_prompt_present ? ' live' : '')} />
              <span className="mono" style={{ fontSize: 12.5 }}>System prompt: {preview.system_prompt_present ? 'present, not shown' : 'not configured'}</span>
            </div>
            <div className="muted mono" style={{ fontSize: 12, display: 'flex', gap: 12 }}>
              <span>Call #{preview.call_number}</span>
              <span>{preview.is_returning_caller ? 'Returning caller' : 'First call'}</span>
            </div>
            {preview.error && <p style={{ color: 'var(--qd-coral)' }}>{preview.error}</p>}
            {preview.lead_profile ? <ContextBlock label="Lead Profile" content={preview.lead_profile} /> : <p className="muted mono" style={{ fontSize: 12 }}>Lead profile: empty (name/car data missing)</p>}
            {preview.call_history ? <ContextBlock label="Call History" content={preview.call_history} /> : <p className="muted mono" style={{ fontSize: 12 }}>Call history: none stored</p>}
            {preview.misc_notes ? <ContextBlock label="Misc Notes" content={preview.misc_notes} /> : <p className="muted mono" style={{ fontSize: 12 }}>Misc notes: none</p>}
            {preview.skills_index ? <ContextBlock label="Skills Index" content={preview.skills_index} /> : <p className="muted mono" style={{ fontSize: 12 }}>Skills index: no registry configured</p>}
            {preview.tools && preview.tools.length > 0 && (
              <div className="chips">
                {preview.tools.map((tool) => <span key={tool} className="chip">{tool}</span>)}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// LeadDetailPage
// ──────────────────────────────────────────────────────────────────────────────

type TabKey = 'memoria' | 'cotizacion' | 'registro' | 'crm' | 'context'

export function LeadDetailPage() {
  const { clientId, leadId } = useParams<{ clientId: string; leadId: string }>()
  const activeClientId = clientId ?? ''
  const canCall = useFeature(activeClientId, 'outbound_calls')
  const activeLeadId = leadId ?? ''
  const navigate = useNavigate()
  const [tab, setTab] = useState<TabKey>('memoria')
  const [openSession, setOpenSession] = useState<CallSession | null>(null)
  const [copyFeedback, setCopyFeedback] = useState(false)

  const { data: lead, isLoading: leadLoading, isError: leadError } = useLead(activeClientId, activeLeadId, { refetchInterval: REALTIME_INTERVAL_MS })
  const { data: sessions, isLoading: sessionsLoading, isError: sessionsError } = useCallSessions(activeClientId, activeLeadId, { refetchInterval: REALTIME_INTERVAL_MS })

  async function handleCopyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopyFeedback(true)
      setTimeout(() => setCopyFeedback(false), 2000)
    } catch {
      // clipboard may be unavailable in some environments — non-fatal
    }
  }

  if (leadLoading) {
    return (
      <div className="page" data-testid="lead-loading">
        <div className="empty">Cargando lead…</div>
      </div>
    )
  }

  if (leadError || !lead) {
    return (
      <div className="page" data-testid="lead-error" role="alert">
        <div className="empty">
          No pudimos encontrar el lead.
          <div style={{ marginTop: 12 }}>
            <button type="button" className="btn sm" onClick={() => navigate(`/app/${activeClientId}/leads`)}>← Leads</button>
          </div>
        </div>
      </div>
    )
  }

  const n = lead.quote_fields ? lead.quote_fields.filter((f) => f.in_quote_ready_fields && f.filled).length : 0
  const total = lead.quote_fields ? lead.quote_fields.filter((f) => f.in_quote_ready_fields).length : 0
  const interestHistoryValues = (lead.interest_history ?? []).map((e) => e.interest_level)
  const nextActionLabel = lead.next_action ?? (lead.call_count > 0 ? 'Sin agenda' : 'Pendiente')
  const nextActionFlagged = lead.do_not_call || (lead.next_scheduled_call_at != null && new Date(lead.next_scheduled_call_at) < new Date())

  const tabs: [TabKey, string, string | undefined][] = [
    ['memoria', 'Memoria', undefined],
    ['cotizacion', 'Cotización', total > 0 ? `${n}/${total}` : undefined],
    ['registro', 'Registro', undefined],
    ['crm', 'CRM', undefined],
    ['context', 'Próxima llamada', undefined],
  ]

  return (
    <div className="page">
      <div className="ph" style={{ alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, minWidth: 0 }}>
          <span className="avatar" style={{ width: 52, height: 52, font: '500 18px/1 var(--qd-F)' }}>{initials(lead.name)}</span>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <h1>{lead.name}</h1>
              <LeadStatusTag status={lead.status as LeadStatus} />
            </div>
            <p style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span className="mono">{lead.phone}</span>
              <span>·</span>
              <span>{lead.do_not_call ? 'No llamar' : 'Se puede llamar'}</span>
              <span>·</span>
              <span>Actualizado {formatDate(lead.updated_at)}</span>
            </p>
          </div>
        </div>
        <div className="ph-r">
          <button type="button" className="btn" onClick={handleCopyLink}>
            <Icon name="link" size={15} />
            {copyFeedback ? 'Copiado' : 'Copiar link'}
          </button>
          <CallNowCell
            clientId={activeClientId}
            lead={lead}
            label="Llamar ahora"
            size="md"
            disabledReason={canCall ? undefined : PLAN_EXCLUDES_OUTBOUND}
          />
        </div>
      </div>

      <div className="kpis">
        <div className="kpi">
          <span className="eyebrow">Interés</span>
          <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 8 }}>
            <span className="v">{lead.interest_level != null ? `${lead.interest_level}%` : '—'}</span>
            <Spark values={interestHistoryValues} />
          </div>
          <span className="s">{interestHistoryValues.length > 1 ? `Historial: ${interestHistoryValues.join(' → ')}` : 'Sin historial'}</span>
        </div>
        <div className="kpi">
          <span className="eyebrow">Datos para cotizar</span>
          <span className="v">{n}<small>/ {total || '—'}</small></span>
          <span className="s">{total > n ? `Faltan ${total - n}` : total > 0 ? 'Completo' : 'Sin campos configurados'}</span>
        </div>
        <div className="kpi">
          <span className="eyebrow">Llamadas</span>
          <span className="v">{lead.call_count}</span>
          <span className="s">{(sessions ?? []).length} sesiones · última {lead.last_called_at ? formatDate(lead.last_called_at) : 'nunca'}</span>
        </div>
        <div className="kpi">
          <span className="eyebrow">Próxima acción</span>
          <span style={{ font: '500 20px/1.2 var(--qd-F)', letterSpacing: '-.01em', display: 'flex', alignItems: 'center', gap: 9, minHeight: 34 }}>
            {nextActionFlagged && <i className="dot coral" />}
            {nextActionLabel}
          </span>
          <span className="s">{lead.next_action_at ? formatDate(lead.next_action_at) : '—'}</span>
        </div>
      </div>

      <div className="grid-2 wide">
        <div className="stack" style={{ gap: 20 }}>
          <div className="tabs">
            {tabs.map(([key, label, count]) => (
              <button key={key} type="button" className={tab === key ? 'on' : ''} onClick={() => setTab(key)}>
                <span>{label}</span>
                {count && <span className="n">{count}</span>}
              </button>
            ))}
          </div>

          {tab === 'memoria' && <MemoriaTab lead={lead} clientId={activeClientId} />}
          {tab === 'cotizacion' && <CotizacionTab lead={lead} />}
          {tab === 'registro' && <RegistroTab lead={lead} />}
          {tab === 'crm' && <CRMTab lead={lead} clientId={activeClientId} />}
          {tab === 'context' && <ProximaLlamadaTab clientId={activeClientId} leadId={activeLeadId} />}
        </div>

        <aside className="stack rail">
          <section className="card">
            <div className="card-h"><div><h3>Llamadas</h3><p>Sesiones con análisis</p></div><span className="r tag mono">{(sessions ?? []).length}</span></div>
            <div className="card-b" style={{ padding: sessionsLoading || sessionsError || (sessions ?? []).length === 0 ? undefined : 0 }}>
              {sessionsLoading && <div className="empty">Cargando llamadas…</div>}
              {sessionsError && <p style={{ color: 'var(--qd-coral)' }}>Unable to load call history. Please try again.</p>}
              {!sessionsLoading && !sessionsError && (
                <CallHistoryList sessions={sessions ?? []} onOpenSession={setOpenSession} />
              )}
            </div>
          </section>
        </aside>
      </div>

      {openSession && <CallDrawer session={openSession} lead={lead} onClose={() => setOpenSession(null)} />}
    </div>
  )
}
