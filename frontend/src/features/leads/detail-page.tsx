/**
 * LeadDetailPage — Placeholder
 * Phase 4 feature: lead detail with call history and transcript
 */

import { useParams } from 'react-router'

export function LeadDetailPage() {
  const { clientId, leadId } = useParams<{ clientId: string; leadId: string }>()

  return (
    <div>
      <h1 className="font-display text-2xl font-bold text-on-surface">
        Lead Detail
      </h1>
      {clientId && leadId && (
        <p className="text-sm text-on-surface-variant mt-1">
          Client: <span className="text-primary font-medium">{clientId}</span>
          {' · '}
          Lead ID: <span className="text-secondary font-medium">{leadId}</span>
        </p>
      )}
      <p className="text-on-surface-variant mt-4">
        Lead detail coming in Phase 4.
      </p>
    </div>
  )
}
