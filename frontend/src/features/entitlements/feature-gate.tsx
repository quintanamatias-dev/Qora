/**
 * FeatureGate — render children only when the client's plan includes a feature.
 *
 * The backend is the enforcement point (403 feature_not_in_plan); this only
 * keeps the panel from showing, or polling, things the plan excludes.
 *
 * - loading  → nothing (avoids firing requests that would 403)
 * - disabled → a plan notice (or nothing when notice={false})
 * - enabled or failed to load → children
 */

import type { ReactNode } from 'react'
import { useEntitlements } from '../../api/hooks'
import type { FeatureKey } from '../../api/types'

export const FEATURE_LABELS: Record<FeatureKey, string> = {
  outbound_calls: 'Llamadas salientes',
  auto_dialer: 'Rellamado automático',
  crm_integration: 'Integración de CRM',
  analytics: 'Analítica',
  live_monitor: 'Monitor en vivo',
}

interface FeatureGateProps {
  clientId: string
  feature: FeatureKey
  children: ReactNode
  /** Show a notice when the feature is off (default) or render nothing. */
  notice?: boolean
}

export function FeatureGate({ clientId, feature, children, notice = true }: FeatureGateProps) {
  const { data, isLoading } = useEntitlements(clientId)

  if (isLoading) return null
  if (data && !data.features[feature]) {
    return notice ? <PlanNotice feature={feature} /> : null
  }
  return <>{children}</>
}

function PlanNotice({ feature }: { feature: FeatureKey }) {
  return (
    <div role="status" className="card" style={{ padding: 32, textAlign: 'center' }}>
      <p style={{ fontWeight: 500 }}>Tu plan no incluye {FEATURE_LABELS[feature]}</p>
      <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>
        Escribinos para habilitarlo en tu cuenta.
      </p>
    </div>
  )
}
