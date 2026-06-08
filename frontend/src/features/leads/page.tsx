/**
 * LeadsPage — Container component for lead list
 *
 * Spec: sdd/qora-basic-crm/spec — Capability: lead-list-view
 * Design: Container-presentational pattern (mirrors DashboardPage).
 *   - Reads clientId from URL params
 *   - Calls useLeads hook
 *   - Routes to loading / error / empty / data UI branches
 *   - Delegates rendering to LeadTable (presentational)
 */

import { useParams, useNavigate } from 'react-router'
import { useLeads } from '@/api/hooks'
import { LeadTable } from './lead-table'

// ──────────────────────────────────────────────────────────────────────────────
// LeadsPage
// ──────────────────────────────────────────────────────────────────────────────

export function LeadsPage() {
  const { clientId } = useParams<{ clientId: string }>()
  const navigate = useNavigate()
  const { data, isLoading, isError } = useLeads(clientId ?? '')

  function handleSelectLead(leadId: string) {
    navigate(`/app/${clientId}/leads/${leadId}`)
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="font-display text-2xl font-medium text-ink">
          Leads
        </h1>
        {clientId && (
          <p className="text-sm text-ink-2 mt-1">
            Client: <span className="text-teal font-medium">{clientId}</span>
          </p>
        )}
      </div>

      {/* Leads area — routes to loading / error / empty / data */}
      <LeadsArea
        loading={isLoading}
        error={isError}
        leads={data ?? null}
        onSelectLead={handleSelectLead}
      />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// LeadsArea — UI branch routing
// ──────────────────────────────────────────────────────────────────────────────

import type { Lead } from '@/api/types'

interface LeadsAreaProps {
  loading: boolean
  error: boolean
  leads: Lead[] | null
  onSelectLead: (leadId: string) => void
}

function LeadsArea({ loading, error, leads, onSelectLead }: LeadsAreaProps) {
  // Loading — show skeleton
  if (loading) {
    return (
      <div data-testid="leads-loading" className="space-y-2">
        {[...Array(5)].map((_, i) => (
          <div
            key={i}
            className="h-12 bg-mist rounded-md animate-pulse"
          />
        ))}
      </div>
    )
  }

  // Error
  if (error) {
    return (
      <div
        data-testid="leads-error"
        role="alert"
        className="bg-paper border border-line rounded-lg p-8 text-center"
      >
        <p className="text-ink font-medium">
          Unable to load leads. Please try again.
        </p>
      </div>
    )
  }

  // Empty state
  if (leads && leads.length === 0) {
    return (
      <div
        data-testid="leads-empty"
        className="bg-paper border border-line rounded-lg p-8 text-center"
      >
        <p className="text-ink font-medium">No leads found</p>
        <p className="text-ink-3 text-sm mt-2">
          Import leads to start calling.
        </p>
      </div>
    )
  }

  // Data — render lead table
  if (leads) {
    return <LeadTable leads={leads} onSelectLead={onSelectLead} />
  }

  return null
}
