/**
 * CallNowCell — Stateful control managing the real outbound call lifecycle.
 *
 * Used both in the leads table ("Llamar" button per row) and in the lead
 * detail header ("Llamar ahora" CTA) — same component, different label/size.
 *
 * Spec: call-now-feedback — Requirement: Polling Lifecycle After Trigger
 *   After POST /call returns call_session_id, polls GET /calls/{id}/status every 3s.
 * Spec: call-now-feedback — Requirement: Real State Badges
 *   Badge text/color map to real telephony_status from the polling endpoint.
 * Spec: call-now-feedback — Requirement: Honest Timeout
 *   After 180s with no terminal state, shows a timeout message.
 * Spec: call-now-feedback — Requirement: Graceful 409 Display
 *   409 shows active_session_id when available. No polling started on 409.
 *
 * do_not_call guard: when the lead is flagged do_not_call, the trigger is
 * replaced by a static "No llamar" tag — this is an additive client-side
 * guard on top of the existing backend guards (403/409/422/429), never a
 * replacement for them.
 */

import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import type { Lead, CallTriggerResponse, TelephonyStatus } from '@/api/types'
import { triggerCall } from '@/api/leads'
import { ApiError } from '@/api/client'
import { useCallPolling } from './use-call-polling'

// ──────────────────────────────────────────────────────────────────────────────
// Per-row call state
// ──────────────────────────────────────────────────────────────────────────────

type CallRowState =
  | { phase: 'idle' }
  | { phase: 'confirming' }
  | { phase: 'loading' }
  | { phase: 'calling'; callSessionId: string }
  | { phase: 'error'; message: string }

// ──────────────────────────────────────────────────────────────────────────────
// Badge configuration — maps telephony_status to a Spanish label + tag class
// ──────────────────────────────────────────────────────────────────────────────

interface BadgeConfig {
  label: string
  className: string
}

const TELEPHONY_BADGE_MAP: Record<TelephonyStatus, BadgeConfig> = {
  queued:          { label: 'En cola',        className: 'tag ghost' },
  dialing:         { label: 'Marcando…',      className: 'tag ghost' },
  ringing:         { label: 'Sonando…',       className: 'tag' },
  connected:       { label: 'Conectada',      className: 'tag teal' },
  voicemail:       { label: 'Buzón de voz',   className: 'tag' },
  completed:       { label: 'Completada',     className: 'tag teal' },
  no_answer:       { label: 'No atendió',     className: 'tag ghost' },
  failed:          { label: 'Llamada fallida', className: 'tag coral' },
  recurrent_error: { label: 'Llamada fallida', className: 'tag coral' },
  stale_in_call:   { label: 'Llamada fallida', className: 'tag coral' },
}

function TelephonyBadge({ status }: { status: TelephonyStatus }) {
  const config = TELEPHONY_BADGE_MAP[status] ?? { label: status, className: 'tag' }
  return <span className={config.className}>{config.label}</span>
}

// ──────────────────────────────────────────────────────────────────────────────
// Error message mapping (Spanish, spec-compliant)
// ──────────────────────────────────────────────────────────────────────────────

function resolveErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) {
      const body = err.body as Record<string, unknown> | undefined
      const activeSessionId =
        body && typeof body === 'object' && 'active_session_id' in body
          ? (body as { active_session_id?: string }).active_session_id
          : undefined
      if (activeSessionId) {
        return `(409) Ya hay una llamada activa para este lead (sesión: ${activeSessionId}).`
      }
      return '(409) Ya hay una llamada activa o en curso para este lead.'
    }

    if (err.body && typeof err.body === 'object' && 'detail' in err.body) {
      const detail = (err.body as { detail: unknown }).detail
      if (typeof detail === 'string' && detail.length > 0) {
        return `(${err.status}) ${detail}`
      }
    }

    switch (err.status) {
      case 403:
        return '(403) Las llamadas salientes no están habilitadas. Activá ENABLE_OUTBOUND_CALLS=true.'
      case 422:
        return '(422) El teléfono del lead no es un E.164 válido. Actualizalo y reintentá.'
      case 429:
        return '(429) Muy pronto después del último intento. Esperá unos segundos y reintentá.'
      default:
        return `Error ${err.status}: ${err.message}`
    }
  }
  if (err instanceof Error) return err.message
  return 'Ocurrió un error inesperado.'
}

function resolveTriggerFailureMessage(result: CallTriggerResponse): string {
  if (result.error && result.error.length > 0) {
    return result.error
  }
  switch (result.status) {
    case 'recurrent_error':
      return 'No se pudo realizar la llamada después de un reintento. Probá de nuevo en un momento.'
    case 'failed':
    default:
      return 'No se pudo realizar la llamada. Intentá de nuevo.'
  }
}

const TIMEOUT_MESSAGE = 'Se agotó el tiempo de espera — revisá el historial de llamadas.'

// ──────────────────────────────────────────────────────────────────────────────
// ConfirmCallDialog — Radix Dialog wrapping the confirmation step
// ──────────────────────────────────────────────────────────────────────────────

interface ConfirmCallDialogProps {
  open: boolean
  leadName: string
  isLoading: boolean
  onConfirm: () => void
  onCancel: () => void
}

function ConfirmCallDialog({ open, leadName, isLoading, onConfirm, onCancel }: ConfirmCallDialogProps) {
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { if (!o) onCancel() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" onClick={stop} />
        <Dialog.Content
          onClick={stop}
          className="card"
          style={{
            position: 'fixed',
            left: '50%',
            top: '50%',
            transform: 'translate(-50%, -50%)',
            zIndex: 50,
            width: 'min(440px, 90vw)',
            padding: 20,
          }}
        >
          <Dialog.Title style={{ font: '500 18px/1.3 var(--qd-F)', marginBottom: 4 }}>
            Confirmar llamada real
          </Dialog.Title>

          <Dialog.Description asChild>
            <div className="muted" style={{ fontSize: 13.5, margin: '10px 0 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <p style={{ margin: 0 }}>
                Estás por hacer una <strong style={{ color: 'var(--qd-ink)' }}>llamada real</strong> a{' '}
                <span style={{ color: 'var(--qd-teal)', fontWeight: 500 }}>{leadName}</span>.
              </p>
              <p className="alert" style={{ margin: 0, alignItems: 'flex-start' }}>
                <span aria-hidden>⚠️</span>
                <span>
                  Esto se conecta vía ElevenLabs + Telnyx y genera costos de telefonía reales
                  (~$0.21/min). La llamada comienza apenas confirmes.
                </span>
              </p>
            </div>
          </Dialog.Description>

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button
              type="button"
              className="btn"
              onClick={(e) => { e.stopPropagation(); onCancel() }}
              disabled={isLoading}
            >
              Cancelar
            </button>
            <button
              type="button"
              className="btn primary"
              onClick={(e) => { e.stopPropagation(); onConfirm() }}
              disabled={isLoading}
              style={{ minWidth: 96 }}
            >
              {isLoading ? 'Llamando…' : 'Confirmar'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// CallNowCell
// ──────────────────────────────────────────────────────────────────────────────

export interface CallNowCellProps {
  clientId: string
  lead: Lead
  /** Trigger label — "Llamar" in the table, "Llamar ahora" in the detail header. */
  label?: string
  /** "sm" for table rows (default), "md" for the detail header CTA. */
  size?: 'sm' | 'md'
}

export function CallNowCell({ clientId, lead, label = 'Llamar', size = 'sm' }: CallNowCellProps) {
  const [state, setState] = useState<CallRowState>({ phase: 'idle' })

  const activeSessionId = state.phase === 'calling' ? state.callSessionId : null
  const pollingState = useCallPolling(activeSessionId)

  function handleButtonClick(e: React.MouseEvent) {
    e.stopPropagation()
    setState({ phase: 'confirming' })
  }

  function handleCancel() {
    setState({ phase: 'idle' })
  }

  async function handleConfirm() {
    setState({ phase: 'loading' })
    try {
      const result = await triggerCall(clientId, lead.id)
      if (result.status === 'dialing' && result.call_session_id) {
        setState({ phase: 'calling', callSessionId: result.call_session_id })
      } else {
        setState({ phase: 'error', message: resolveTriggerFailureMessage(result) })
      }
    } catch (err) {
      setState({ phase: 'error', message: resolveErrorMessage(err) })
    }
  }

  // ── do_not_call guard — additive, on top of the backend guards ──
  if (lead.do_not_call && (state.phase === 'idle' || state.phase === 'error')) {
    return <span className="tag coral" title="Este lead está marcado como No llamar">No llamar</span>
  }

  // ── polling phase — real state badges from the polling endpoint ──
  if (state.phase === 'calling' && pollingState !== null) {
    if (pollingState.status === 'timedOut') {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 200 }}>
          <span role="alert" className="muted" style={{ fontSize: 12 }}>{TIMEOUT_MESSAGE}</span>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setState({ phase: 'idle' }) }}
            className="btn sm quiet"
            style={{ alignSelf: 'flex-start' }}
          >
            Descartar
          </button>
        </div>
      )
    }

    if (pollingState.status === 'polling') {
      return <TelephonyBadge status={pollingState.telephonyStatus} />
    }

    if (pollingState.status === 'terminal') {
      const isFailure = ['failed', 'recurrent_error', 'stale_in_call', 'no_answer'].includes(pollingState.telephonyStatus)
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 200 }}>
          <TelephonyBadge status={pollingState.telephonyStatus} />
          {isFailure && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setState({ phase: 'idle' }) }}
              className="btn sm quiet"
              style={{ alignSelf: 'flex-start' }}
            >
              Reintentar
            </button>
          )}
        </div>
      )
    }

    if (pollingState.status === 'error') {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 200 }}>
          <span role="alert" style={{ fontSize: 12, color: 'var(--qd-coral)' }}>{pollingState.message}</span>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setState({ phase: 'idle' }) }}
            className="btn sm quiet"
            style={{ alignSelf: 'flex-start' }}
          >
            Descartar
          </button>
        </div>
      )
    }
  }

  // ── 'calling' phase but polling hasn't returned yet (first tick) ──
  if (state.phase === 'calling') {
    return <span className="tag ghost">Marcando…</span>
  }

  // ── error phase ──
  if (state.phase === 'error') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 200 }}>
        <span role="alert" style={{ fontSize: 12, color: 'var(--qd-coral)' }} title={state.message}>
          {state.message}
        </span>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setState({ phase: 'idle' }) }}
          className="btn sm quiet"
          style={{ alignSelf: 'flex-start' }}
          aria-label="Llamar"
        >
          Llamar
        </button>
      </div>
    )
  }

  // ── idle / confirming / loading phase ──
  return (
    <>
      <button
        type="button"
        className={size === 'sm' ? 'btn sm primary' : 'btn primary'}
        onClick={handleButtonClick}
        disabled={state.phase === 'loading'}
        style={{ whiteSpace: 'nowrap' }}
      >
        {label}
      </button>

      <ConfirmCallDialog
        open={state.phase === 'confirming' || state.phase === 'loading'}
        leadName={lead.name}
        isLoading={state.phase === 'loading'}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </>
  )
}
