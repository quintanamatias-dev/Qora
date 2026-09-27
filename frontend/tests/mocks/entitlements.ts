/**
 * Entitlements fixtures — default is the unrestricted "pilot" plan so existing
 * tests keep seeing every feature unless they opt into a restricted plan.
 */

import type { ClientEntitlements, FeatureKey, LimitKey, PlanCatalog } from '../../src/api/types'

const ALL_FEATURES: Record<FeatureKey, boolean> = {
  outbound_calls: true,
  auto_dialer: true,
  crm_integration: true,
  analytics: true,
  live_monitor: true,
}

const NO_LIMITS: Record<LimitKey, number | null> = {
  max_agents: null,
  max_concurrent_calls: null,
  max_monthly_calls: null,
  max_monthly_minutes: null,
}

type EntitlementsOverrides = Partial<Omit<ClientEntitlements, 'features' | 'limits'>> & {
  features?: Partial<Record<FeatureKey, boolean>>
  limits?: Partial<Record<LimitKey, number | null>>
}

export function makeEntitlements(overrides: EntitlementsOverrides = {}): ClientEntitlements {
  const { features, limits, ...rest } = overrides
  return {
    client_id: 'acme-motors',
    plan: 'pilot',
    overrides: {},
    usage: {
      period_start: '2026-09-01T03:00:00Z',
      monthly_calls: 12,
      monthly_minutes: 34,
      concurrent_calls: 0,
      active_agents: 1,
    },
    ...rest,
    features: { ...ALL_FEATURES, ...features },
    limits: { ...NO_LIMITS, ...limits },
  }
}

export const planCatalogFixture: PlanCatalog = {
  features: Object.keys(ALL_FEATURES) as FeatureKey[],
  limits: Object.keys(NO_LIMITS) as LimitKey[],
  plans: [
    { name: 'pilot', label: 'Pilot', features: ALL_FEATURES, limits: NO_LIMITS },
    {
      name: 'starter',
      label: 'Starter',
      features: { ...ALL_FEATURES, auto_dialer: false, crm_integration: false, live_monitor: false },
      limits: { max_agents: 1, max_concurrent_calls: 1, max_monthly_calls: null, max_monthly_minutes: 200 },
    },
    {
      name: 'pro',
      label: 'Pro',
      features: ALL_FEATURES,
      limits: { max_agents: 3, max_concurrent_calls: 3, max_monthly_calls: null, max_monthly_minutes: 1000 },
    },
  ],
}
