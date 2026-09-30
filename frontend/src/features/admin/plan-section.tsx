/**
 * PlanSection — superadmin editor for a client's plan and per-client exceptions.
 *
 * The form holds the EFFECTIVE features/limits. On save, only the values that
 * differ from the selected plan's defaults are sent as overrides, so a client
 * on a plan with no exceptions stores `{}` and follows future plan changes.
 *
 * Backend: PUT /api/v1/clients/{id}/entitlements (superadmin only).
 */

import { useEffect, useState } from 'react'
import { Button, Checkbox, Input, Select } from '@/design/components'
import { useEntitlements, usePlanCatalog, useUpdateEntitlements } from '@/api/hooks'
import type { EntitlementOverrides, FeatureKey, LimitKey, PlanDefinition } from '@/api/types'

const FEATURE_LABELS: Record<FeatureKey, string> = {
  outbound_calls: 'Outbound calls',
  auto_dialer: 'Auto-dialer',
  crm_integration: 'CRM integration',
  analytics: 'Analytics',
  live_monitor: 'Live monitor',
}

const LIMIT_LABELS: Record<LimitKey, string> = {
  max_agents: 'Agents',
  max_concurrent_calls: 'Concurrent calls',
  max_monthly_calls: 'Monthly calls',
  max_monthly_minutes: 'Monthly minutes',
}

interface PlanForm {
  plan: string
  features: Record<FeatureKey, boolean>
  limits: Record<LimitKey, number | null>
}

/** Values that differ from the plan defaults; empty sections are omitted. */
export function diffOverrides(form: PlanForm, plan: PlanDefinition): EntitlementOverrides {
  const features: EntitlementOverrides['features'] = {}
  for (const key of Object.keys(form.features) as FeatureKey[]) {
    if (form.features[key] !== plan.features[key]) features[key] = form.features[key]
  }
  const limits: EntitlementOverrides['limits'] = {}
  for (const key of Object.keys(form.limits) as LimitKey[]) {
    if (form.limits[key] !== plan.limits[key]) limits[key] = form.limits[key]
  }
  return {
    ...(Object.keys(features).length > 0 ? { features } : {}),
    ...(Object.keys(limits).length > 0 ? { limits } : {}),
  }
}

function countOverrides(overrides: EntitlementOverrides): number {
  return Object.keys(overrides.features ?? {}).length + Object.keys(overrides.limits ?? {}).length
}

export function PlanSection({ clientId }: { clientId: string }) {
  const entitlements = useEntitlements(clientId)
  const catalog = usePlanCatalog()
  const save = useUpdateEntitlements(clientId)
  const [form, setForm] = useState<PlanForm | null>(null)

  useEffect(() => {
    if (entitlements.data) {
      const { plan, features, limits } = entitlements.data
      setForm({ plan, features: { ...features }, limits: { ...limits } })
    }
  }, [entitlements.data])

  if (entitlements.isLoading || catalog.isLoading || !form) {
    return <p className="text-sm text-ink-3">Loading plan…</p>
  }
  if (entitlements.isError || catalog.isError || !entitlements.data || !catalog.data) {
    return <p role="alert" className="text-sm text-coral">Could not load the plan for this client.</p>
  }

  const plans = catalog.data.plans
  const selectedPlan = plans.find((p) => p.name === form.plan)
  const usage = entitlements.data.usage
  const exceptions = countOverrides(entitlements.data.overrides)

  function selectPlan(name: string) {
    const plan = plans.find((p) => p.name === name)
    if (!plan) return
    // A new plan starts from its own defaults; exceptions are re-applied by hand.
    setForm({ plan: plan.name, features: { ...plan.features }, limits: { ...plan.limits } })
  }

  function setFeature(key: FeatureKey, value: boolean) {
    setForm((f) => (f ? { ...f, features: { ...f.features, [key]: value } } : f))
  }

  function setLimit(key: LimitKey, raw: string) {
    const value = raw.trim() === '' ? null : Math.max(0, Math.floor(Number(raw)))
    setForm((f) => (f ? { ...f, limits: { ...f.limits, [key]: value } } : f))
  }

  function handleSave() {
    if (!form || !selectedPlan) return
    save.mutate({ plan: form.plan, overrides: diffOverrides(form, selectedPlan) })
  }

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-4">
        <div className="w-56">
          <Select label="Plan" id="plan-select" value={form.plan} onChange={(e) => selectPlan(e.target.value)}>
            {plans.map((p) => (
              <option key={p.name} value={p.name}>
                {p.label}
              </option>
            ))}
          </Select>
        </div>
        <p data-testid="plan-usage" className="text-sm text-ink-3">
          This month: {usage.monthly_minutes} min · {usage.monthly_calls} calls · {usage.active_agents} active
          agents
        </p>
      </div>

      {exceptions > 0 && (
        <p className="text-xs text-ink-3">
          {exceptions} exception{exceptions === 1 ? '' : 's'} to the {entitlements.data.plan} plan.
        </p>
      )}

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium uppercase tracking-widest text-ink-3 mb-2">Features</legend>
        {(Object.keys(FEATURE_LABELS) as FeatureKey[]).map((key) => (
          <Checkbox
            key={key}
            id={`feature-${key}`}
            label={FEATURE_LABELS[key]}
            checked={form.features[key]}
            onChange={(e) => setFeature(key, e.target.checked)}
          />
        ))}
      </fieldset>

      <fieldset>
        <legend className="text-xs font-medium uppercase tracking-widest text-ink-3 mb-2">
          Limits (empty = unlimited)
        </legend>
        <div className="grid grid-cols-2 gap-4">
          {(Object.keys(LIMIT_LABELS) as LimitKey[]).map((key) => (
            <Input
              key={key}
              id={`limit-${key}`}
              label={LIMIT_LABELS[key]}
              type="number"
              min={0}
              value={form.limits[key] ?? ''}
              placeholder="Unlimited"
              onChange={(e) => setLimit(key, e.target.value)}
            />
          ))}
        </div>
      </fieldset>

      <div className="flex items-center gap-3">
        <Button onClick={handleSave} disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save plan'}
        </Button>
        {save.isSuccess && <span className="text-sm text-teal">Saved</span>}
        {save.isError && (
          <span role="alert" className="text-sm text-coral">
            {save.error.message}
          </span>
        )}
      </div>
    </div>
  )
}
