/**
 * ClientDetailPage — Per-client admin detail view
 *
 * Reads :clientId from route params.
 * Layout:
 *  - Header: client name, ID (mono), status badge, back link
 *  - Stacked collapsible sections: Agents, Integrations
 *
 * Uses the Disclosure pattern for each section (expand/collapse).
 * Sections start expanded by default.
 */

import { useState } from 'react'
import { useParams, Link } from 'react-router'
import { Badge } from '@/design/components'
import { useClient } from '@/api/hooks'
import { AgentsSection } from './agents-section'
import { IntegrationsSection } from './integrations-section'

// ──────────────────────────────────────────────────────────────────────────────
// Disclosure — collapsible section wrapper
// ──────────────────────────────────────────────────────────────────────────────

interface DisclosureProps {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}

function Disclosure({ title, defaultOpen = true, children }: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border border-line rounded-lg bg-paper overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-6 py-4 hover:bg-pearl/50 transition-colors"
        aria-expanded={open}
      >
        <span className="font-display text-base font-semibold text-ink">{title}</span>
        <span
          className={`text-ink-3 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          aria-hidden="true"
        >
          ▾
        </span>
      </button>
      {open && (
        <div className="px-6 pb-6">
          {children}
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// ClientDetailPage — container
// ──────────────────────────────────────────────────────────────────────────────

export function ClientDetailPage() {
  const { clientId } = useParams<{ clientId: string }>()
  const { data: client, isLoading } = useClient(clientId ?? '')

  if (!clientId) {
    return (
      <div className="py-16 text-center">
        <p className="text-ink-3">No client ID provided.</p>
      </div>
    )
  }

  return (
    <div data-testid="client-detail-page" className="space-y-6">
      {/* Back navigation */}
      <div>
        <Link
          to="/admin"
          className="inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink transition-colors"
        >
          ← Back to clients
        </Link>
      </div>

      {/* Client header */}
      <div className="bg-paper border border-line rounded-lg px-6 py-5">
        {isLoading ? (
          <div className="space-y-2">
            <div className="h-7 w-48 bg-mist rounded-md animate-pulse" />
            <div className="h-4 w-32 bg-mist rounded-md animate-pulse" />
          </div>
        ) : (
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="font-display text-2xl font-semibold text-ink">
                {client?.name ?? clientId}
              </h1>
              <code className="font-mono text-xs text-teal mt-1 block">{clientId}</code>
            </div>
            <Badge status={client?.is_active ? 'active' : 'neutral'}>
              {client?.is_active ? 'Active' : 'Inactive'}
            </Badge>
          </div>
        )}
      </div>

      {/* Stacked sections */}
      <Disclosure title="Agents">
        <AgentsSection clientId={clientId} />
      </Disclosure>

      <Disclosure title="Integrations">
        <IntegrationsSection clientId={clientId} />
      </Disclosure>
    </div>
  )
}
