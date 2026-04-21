/**
 * DashboardPage — Placeholder
 * Phase 4 feature: dashboard metrics and voice call analytics
 */

import { useParams } from 'react-router'

export function DashboardPage() {
  const { clientId } = useParams<{ clientId: string }>()

  return (
    <div>
      <h1 className="font-display text-2xl font-bold text-on-surface">
        Dashboard
      </h1>
      {clientId && (
        <p className="text-sm text-on-surface-variant mt-1">
          Client: <span className="text-primary font-medium">{clientId}</span>
        </p>
      )}
      <p className="text-on-surface-variant mt-4">
        Dashboard content coming in Phase 4.
      </p>
    </div>
  )
}
