/**
 * LeadsPage — Placeholder
 * Phase 4 feature: leads list with filtering and status management
 */

import { useParams } from 'react-router'

export function LeadsPage() {
  const { clientId } = useParams<{ clientId: string }>()

  return (
    <div>
      <h1 className="font-display text-2xl font-bold text-on-surface">
        Leads
      </h1>
      {clientId && (
        <p className="text-sm text-on-surface-variant mt-1">
          Client: <span className="text-primary font-medium">{clientId}</span>
        </p>
      )}
      <p className="text-on-surface-variant mt-4">
        Leads list coming in Phase 4.
      </p>
    </div>
  )
}
