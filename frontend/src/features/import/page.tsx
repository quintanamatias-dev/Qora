/**
 * ImportPage — "Importar" (bulk lead import from CSV + CRM sync)
 *
 * Design: qora-presentacion/project/dashboard/screens-leads.jsx (Import component).
 * Ported classes come from src/design/dashboard.css (.page/.ph/.grid-2/.card/.steps/.drop/.tbl/...).
 * PageContainer already renders <main className="page"> around the route Outlet —
 * this component renders its content directly, without an extra `.page` wrapper.
 *
 * Real vs design mock data:
 * - File name, row/column counts, mapping examples, import counts and CRM
 *   integration details are all read from the parsed file / real API responses.
 * - "email" is intentionally NOT offered as a mapping target: the lead-creation
 *   API (POST /api/v1/leads, backend/app/leads/router.py CreateLeadRequest) has
 *   no email field, so email columns can only be mapped to "notes" or skipped.
 * - Creating/importing leads does not trigger outbound calls: ScheduledCall rows
 *   (which the auto-dialer reads) are only created after a completed call
 *   (app/analysis summarizer → auto_schedule) or via manual scheduling —
 *   never from lead creation or CRM import. The result copy reflects that.
 */

import { useCallback, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { useIntegrations } from '@/api/hooks'
import { createLead } from '@/api/leads'
import { ApiError } from '@/api/client'
import { Icon } from '@/design/components'
import type { CreateLeadPayload, IntegrationConfig } from '@/api/types'
import { parseCsv } from './csv-parser'
import { guessColumnMapping, SKIP_FIELD_KEY, type TargetField } from './mapping'
import { buildImportRows, type ImportRow, type RowInvalidReason } from './validation'
import { triggerCrmImport, type CrmImportResult } from './crm-import'
import { FeatureGate } from '@/features/entitlements/feature-gate'
import { useToast, Toast } from './toast'

const MAX_ROWS = 5000
const IMPORT_CONCURRENCY = 3

const BASE_TARGET_FIELDS: TargetField[] = [
  { key: 'name', label: 'Nombre' },
  { key: 'phone', label: 'Teléfono' },
  { key: 'notes', label: 'Notas' },
]

const REASON_LABEL: Record<RowInvalidReason, string> = {
  missing_name: 'sin nombre',
  missing_phone: 'sin teléfono',
  invalid_phone: 'con teléfono inválido',
}

// ──────────────────────────────────────────────────────────────────────────────
// Small local concurrency-bounded runner
// ──────────────────────────────────────────────────────────────────────────────

async function runWithConcurrency<T, R>(
  items: T[],
  limit: number,
  worker: (item: T, index: number) => Promise<R>,
  onSettled?: () => void
): Promise<R[]> {
  const results: R[] = new Array(items.length)
  let cursor = 0

  async function runNext(): Promise<void> {
    const current = cursor
    cursor += 1
    if (current >= items.length) return
    results[current] = await worker(items[current], current)
    onSettled?.()
    await runNext()
  }

  const workers = Array.from({ length: Math.min(limit, items.length) }, () => runNext())
  await Promise.all(workers)
  return results
}

// ──────────────────────────────────────────────────────────────────────────────
// ImportPage
// ──────────────────────────────────────────────────────────────────────────────

type BulkOutcome = { row: ImportRow; success: true } | { row: ImportRow; success: false; error: string }

interface BulkResult {
  attempted: number
  createdCount: number
  failures: { row: ImportRow; error: string }[]
}

export function ImportPage() {
  const { clientId } = useParams<{ clientId: string }>()
  const activeClientId = clientId ?? ''
  const queryClient = useQueryClient()
  const { toastMessage, showToast } = useToast()

  const integrations = useIntegrations(activeClientId)
  const integration: IntegrationConfig | undefined = integrations.data?.[0]

  const targetFields = useMemo<TargetField[]>(() => {
    const customFields = (integration?.field_definitions ?? []).map((field) => ({
      key: field.field_key,
      label: field.label,
    }))
    return [...BASE_TARGET_FIELDS, ...customFields]
  }, [integration])

  const [step, setStep] = useState<0 | 1 | 2>(0)
  const [over, setOver] = useState(false)
  const [fileName, setFileName] = useState('')
  const [headers, setHeaders] = useState<string[]>([])
  const [dataRows, setDataRows] = useState<string[][]>([])
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [parseError, setParseError] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  const [importProgress, setImportProgress] = useState(0)
  const [bulkResult, setBulkResult] = useState<BulkResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const importRows = useMemo<ImportRow[]>(() => {
    if (headers.length === 0) return []
    return buildImportRows(headers, dataRows, mapping)
  }, [headers, dataRows, mapping])

  const validRows = useMemo(() => importRows.filter((r) => r.valid), [importRows])
  const omittedCount = importRows.length - validRows.length

  function resetToStep0() {
    setStep(0)
    setFileName('')
    setHeaders([])
    setDataRows([])
    setMapping({})
    setParseError(null)
    setBulkResult(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleFile = useCallback(
    (file: File) => {
      setParseError(null)
      const reader = new FileReader()
      reader.onload = () => {
        const text = String(reader.result ?? '')
        const parsed = parseCsv(text)
        if (parsed.headers.length === 0) {
          setParseError('No pudimos leer columnas en este archivo. Verificá que sea un CSV válido.')
          return
        }
        const rows = parsed.rows.slice(0, MAX_ROWS)
        setFileName(file.name)
        setHeaders(parsed.headers)
        setDataRows(rows)
        setMapping(guessColumnMapping(parsed.headers, targetFields))
        setStep(1)
      }
      reader.onerror = () => {
        setParseError('No pudimos leer el archivo. Probá de nuevo.')
      }
      reader.readAsText(file)
    },
    [targetFields]
  )

  function onFilePicked(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) handleFile(file)
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) handleFile(file)
  }

  async function handleImport() {
    if (validRows.length === 0) return
    setImporting(true)
    setImportProgress(0)

    const outcomes = await runWithConcurrency<ImportRow, BulkOutcome>(
      validRows,
      IMPORT_CONCURRENCY,
      async (row) => {
        try {
          const payload: CreateLeadPayload = {
            name: row.name,
            phone: row.phone,
            notes: row.notes,
            ...(Object.keys(row.custom_fields).length > 0 ? { custom_fields: row.custom_fields } : {}),
          }
          await createLead(activeClientId, payload)
          return { row, success: true }
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Error desconocido al crear el lead'
          return { row, success: false, error: message }
        }
      },
      () => setImportProgress((p) => p + 1)
    )

    const failures = outcomes
      .filter((o): o is Extract<BulkOutcome, { success: false }> => !o.success)
      .map((o) => ({ row: o.row, error: o.error }))
    const createdCount = outcomes.length - failures.length

    setBulkResult({ attempted: outcomes.length, createdCount, failures })
    setImporting(false)
    setStep(2)

    queryClient.invalidateQueries({ queryKey: ['leads', activeClientId] })
    showToast(`${createdCount} lead${createdCount === 1 ? '' : 's'} importado${createdCount === 1 ? '' : 's'}`)
  }

  return (
    <div>
      <div className="ph">
        <div>
          <h1>Importar</h1>
          <p>Traé leads desde tu CRM o desde un archivo. Qora los llama con los datos que ya tenés.</p>
        </div>
      </div>

      <div className="grid-2">
        <section className="card">
          <div className="card-h">
            <div>
              <h3>Subir archivo</h3>
              <p>CSV, hasta {MAX_ROWS.toLocaleString('es-AR')} filas</p>
            </div>
          </div>
          <div className="card-b" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <StepHeader step={step} />

            {parseError && step === 0 && (
              <p className="muted" style={{ color: 'var(--qd-coral)', fontSize: 13 }}>
                {parseError}
              </p>
            )}

            {step === 0 && (
              <div
                className={'drop' + (over ? ' over' : '')}
                onDragOver={(e) => {
                  e.preventDefault()
                  setOver(true)
                }}
                onDragLeave={() => setOver(false)}
                onDrop={onDrop}
              >
                <span
                  className="avatar"
                  style={{ width: 44, height: 44, borderRadius: 12, background: 'var(--qd-surface)' }}
                >
                  <Icon name="upload" size={20} />
                </span>
                <div>
                  <b style={{ fontWeight: 500 }}>Arrastrá tu archivo acá</b>
                  <div className="muted" style={{ fontSize: 13 }}>
                    o elegilo desde tu computadora
                  </div>
                </div>
                <button type="button" className="btn primary" onClick={() => fileInputRef.current?.click()}>
                  Elegir archivo
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,text/csv"
                  style={{ display: 'none' }}
                  onChange={onFilePicked}
                />
                <span className="mono muted" style={{ fontSize: 11 }}>
                  .csv únicamente por ahora
                </span>
              </div>
            )}

            {step === 1 && (
              <MappingStep
                fileName={fileName}
                headers={headers}
                dataRows={dataRows}
                mapping={mapping}
                setMapping={setMapping}
                targetFields={targetFields}
                omittedCount={omittedCount}
                validCount={validRows.length}
                importRows={importRows}
                importing={importing}
                importProgress={importProgress}
                onBack={resetToStep0}
                onImport={handleImport}
              />
            )}

            {step === 2 && bulkResult && (
              <ResultStep result={bulkResult} onUploadAnother={resetToStep0} />
            )}
          </div>
        </section>

        <div className="stack">
          <FeatureGate clientId={activeClientId} feature="crm_integration">
            <CrmIntegrationCard
              clientId={activeClientId}
              integration={integration}
              loading={integrations.isLoading}
              onSyncDone={(result) => {
                queryClient.invalidateQueries({ queryKey: ['leads', activeClientId] })
                const parts = [`${result.created} creados`, `${result.updated} actualizados`]
                if (result.skipped > 0) parts.push(`${result.skipped} omitidos`)
                showToast(`Airtable sincronizado · ${parts.join(' · ')}`)
              }}
            />
          </FeatureGate>
        </div>
      </div>

      {toastMessage && <Toast message={toastMessage} />}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// StepHeader
// ──────────────────────────────────────────────────────────────────────────────

function StepHeader({ step }: { step: 0 | 1 | 2 }) {
  const labels = ['Subir archivo', 'Mapear columnas', 'Listo']
  return (
    <div className="steps">
      {labels.map((label, i) => (
        <ScStep key={label} label={label} i={i} step={step} isLast={i === labels.length - 1} />
      ))}
    </div>
  )
}

function ScStep({ label, i, step, isLast }: { label: string; i: number; step: number; isLast: boolean }) {
  return (
    <>
      {i > 0 && <i className="sep" />}
      <span className={step === i ? 'on' : step > i ? 'done' : ''}>
        <i>{step > i ? <Icon name="check" size={12} strokeWidth={2.2} /> : i + 1}</i>
        {label}
      </span>
      {isLast ? null : null}
    </>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// MappingStep
// ──────────────────────────────────────────────────────────────────────────────

interface MappingStepProps {
  fileName: string
  headers: string[]
  dataRows: string[][]
  mapping: Record<string, string>
  setMapping: React.Dispatch<React.SetStateAction<Record<string, string>>>
  targetFields: TargetField[]
  omittedCount: number
  validCount: number
  importRows: ImportRow[]
  importing: boolean
  importProgress: number
  onBack: () => void
  onImport: () => void
}

function MappingStep({
  fileName,
  headers,
  dataRows,
  mapping,
  setMapping,
  targetFields,
  omittedCount,
  validCount,
  importRows,
  importing,
  importProgress,
  onBack,
  onImport,
}: MappingStepProps) {
  const reasonCounts = useMemo(() => {
    const counts: Partial<Record<RowInvalidReason, number>> = {}
    for (const row of importRows) {
      if (row.reason) counts[row.reason] = (counts[row.reason] ?? 0) + 1
    }
    return counts
  }, [importRows])

  const omittedSummary = (Object.entries(reasonCounts) as [RowInvalidReason, number][])
    .map(([reason, count]) => `${count} ${REASON_LABEL[reason]}`)
    .join(', ')

  return (
    <>
      <div
        className="row"
        style={{ padding: '12px 14px', border: '1px solid var(--qd-line)', borderRadius: 10 }}
      >
        <Icon name="file" size={20} style={{ color: 'var(--qd-ink-3)' }} />
        <div className="t">
          <b>{fileName}</b>
          <span>
            {dataRows.length} fila{dataRows.length === 1 ? '' : 's'} · {headers.length} columna
            {headers.length === 1 ? '' : 's'}
          </span>
        </div>
        <button type="button" className="ib" title="Quitar" onClick={onBack}>
          <Icon name="x" size={16} />
        </button>
      </div>

      <div style={{ border: '1px solid var(--qd-line)', borderRadius: 12, overflow: 'hidden' }}>
        <table className="tbl">
          <thead>
            <tr>
              <th>Columna del archivo</th>
              <th>Ejemplo</th>
              <th>Campo en Qora</th>
            </tr>
          </thead>
          <tbody>
            {headers.map((header, colIndex) => {
              const example = dataRows[0]?.[colIndex] ?? ''
              return (
                <tr key={header}>
                  <td style={{ fontWeight: 500 }}>{header}</td>
                  <td className="muted" style={{ fontSize: 13 }}>
                    {example}
                  </td>
                  <td style={{ width: 190 }}>
                    <select
                      className="select"
                      style={{ width: '100%', borderRadius: 9 }}
                      value={mapping[header] ?? SKIP_FIELD_KEY}
                      onChange={(e) => setMapping((prev) => ({ ...prev, [header]: e.target.value }))}
                    >
                      {targetFields.map((field) => (
                        <option key={field.key} value={field.key}>
                          {field.label}
                        </option>
                      ))}
                      <option value={SKIP_FIELD_KEY}>No importar</option>
                    </select>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 12.5 }}>
          {omittedCount > 0
            ? `${omittedCount} fila${omittedCount === 1 ? '' : 's'} ${omittedSummary} se van a omitir.`
            : 'Todas las filas están listas para importar.'}
        </span>
        {importing && (
          <span className="mono muted" style={{ fontSize: 12 }}>
            Importando {importProgress}/{validCount}…
          </span>
        )}
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button type="button" className="btn" onClick={onBack} disabled={importing}>
            Atrás
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={onImport}
            disabled={importing || validCount === 0}
          >
            {importing ? 'Importando…' : `Importar ${validCount} lead${validCount === 1 ? '' : 's'}`}
          </button>
        </span>
      </div>
    </>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// ResultStep
// ──────────────────────────────────────────────────────────────────────────────

function ResultStep({ result, onUploadAnother }: { result: BulkResult; onUploadAnother: () => void }) {
  const { createdCount, failures } = result

  return (
    <>
      <div
        className="drop"
        style={{ borderStyle: 'solid', borderColor: 'var(--qd-teal-line)', background: 'var(--qd-teal-faint)' }}
      >
        <span className="avatar" style={{ width: 44, height: 44, background: 'var(--qd-teal)', color: 'var(--qd-teal-ink)' }}>
          <Icon name="check" size={20} strokeWidth={2} />
        </span>
        <div>
          <b style={{ fontWeight: 500 }}>
            {`${createdCount} lead${createdCount === 1 ? '' : 's'} importado${createdCount === 1 ? '' : 's'}`}
          </b>
          <div className="muted" style={{ fontSize: 13 }}>
            {createdCount > 0
              ? 'Los leads quedaron disponibles en tu lista. Iniciá las llamadas desde Leads cuando quieras.'
              : 'No se pudo crear ningún lead. Revisá los errores abajo.'}
          </div>
        </div>
        <button type="button" className="btn" onClick={onUploadAnother}>
          Subir otro archivo
        </button>
      </div>

      {failures.length > 0 && (
        <div style={{ border: '1px solid var(--qd-line)', borderRadius: 12, overflow: 'hidden' }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Fila</th>
                <th>Nombre</th>
                <th>Teléfono</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {failures.map(({ row, error }) => (
                <tr key={row.index}>
                  <td className="mono num">{row.index + 1}</td>
                  <td>{row.name}</td>
                  <td className="mono">{row.phone}</td>
                  <td className="muted" style={{ fontSize: 13 }}>
                    {error}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// CrmIntegrationCard
// ──────────────────────────────────────────────────────────────────────────────

function CrmIntegrationCard({
  clientId,
  integration,
  loading,
  onSyncDone,
}: {
  clientId: string
  integration: IntegrationConfig | undefined
  loading: boolean
  onSyncDone: (result: CrmImportResult) => void
}) {
  const [syncing, setSyncing] = useState(false)
  const [lastSyncLabel, setLastSyncLabel] = useState<string | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)

  async function doSync() {
    setSyncing(true)
    setSyncError(null)
    try {
      const result = await triggerCrmImport(clientId)
      setLastSyncLabel('Hace un momento')
      onSyncDone(result)
    } catch (err) {
      setSyncError(err instanceof ApiError ? err.message : 'No pudimos sincronizar. Probá de nuevo.')
    } finally {
      setSyncing(false)
    }
  }

  if (loading) {
    return (
      <section className="card">
        <div className="card-h">
          <div>
            <h3>Integración de CRM</h3>
          </div>
        </div>
        <div className="card-b">
          <div className="empty">Cargando integraciones…</div>
        </div>
      </section>
    )
  }

  if (!integration) {
    return (
      <section className="card">
        <div className="card-h">
          <div>
            <h3>Integración de CRM</h3>
            <p>Sin CRM conectado</p>
          </div>
        </div>
        <div className="card-b">
          <div className="empty">
            Este cliente todavía no tiene un CRM configurado. Conectá uno desde Ajustes para sincronizar leads
            automáticamente.
          </div>
        </div>
      </section>
    )
  }

  const providerLabel = integration.provider.charAt(0).toUpperCase() + integration.provider.slice(1)
  const providerInitials = integration.provider.slice(0, 2).toUpperCase()
  const mappedCount = integration.field_mappings?.length ?? integration.field_count
  const requiredCount = integration.field_mappings?.filter((m) => m.required).length ?? 0

  return (
    <section className="card">
      <div className="card-h">
        <span className="avatar" style={{ borderRadius: 8, font: '600 11px/1 var(--qd-M)' }}>
          {providerInitials}
        </span>
        <div>
          <h3>{providerLabel}</h3>
          <p>CRM del cliente</p>
        </div>
        <span className="r tag teal">{integration.connected ? 'Conectado' : 'Desconectado'}</span>
      </div>
      <div className="card-b" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="kv" style={{ gridTemplateColumns: '110px minmax(0,1fr)' }}>
          <div className="k">Tabla</div>
          <div className="mono" style={{ fontSize: 12.5 }}>
            {integration.table_id}
          </div>
          <div className="k">Campos</div>
          <div>
            {mappedCount} mapeado{mappedCount === 1 ? '' : 's'}
            {requiredCount > 0 ? ` · ${requiredCount} obligatorio${requiredCount === 1 ? '' : 's'}` : ''}
          </div>
          <div className="k">Última sinc.</div>
          <div>{lastSyncLabel ? <span>{lastSyncLabel}</span> : <span className="muted">Sin registro</span>}</div>
        </div>
        {syncError && (
          <p className="muted" style={{ color: 'var(--qd-coral)', fontSize: 13 }}>
            {syncError}
          </p>
        )}
        <button type="button" className="btn primary" onClick={doSync} disabled={syncing || !integration.connected}>
          <span
            style={
              syncing
                ? { display: 'inline-flex', animation: 'qora-import-spin 1s linear infinite' }
                : { display: 'inline-flex' }
            }
          >
            <Icon name="sync" size={15} />
          </span>
          {syncing ? 'Sincronizando…' : 'Sincronizar ahora'}
        </button>
        {!integration.connected && (
          <p className="muted" style={{ fontSize: 12 }}>
            La credencial de este CRM no está configurada — no se puede sincronizar todavía.
          </p>
        )}
      </div>
      <style>{'@keyframes qora-import-spin{to{transform:rotate(360deg)}}'}</style>
    </section>
  )
}
