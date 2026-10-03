/**
 * ConfigFieldProvenance — wraps one agent config field with its inheritance
 * provenance badge ("Qora standard" / "Client" / "Agent") and, for an
 * agent-overridden overridable field, a "Reset to inherited" action.
 *
 * Shared by agents-section.tsx (live) and agents-panel.tsx (legacy twin).
 *
 * A locked field renders with NO editable control at all (not merely a
 * disabled one, per design.md D10 — no panel can ever write a locked field) —
 * `children` (the actual Input/Textarea/etc.) is never mounted in that case.
 */

import type { ReactNode } from 'react'
import { Badge, Button } from '@/design/components'
import type { BadgeStatus } from '@/design/components'
import type { EffectiveConfig } from '@/api/types'

const PROVENANCE_LABEL: Record<string, string> = {
  standard: 'Qora standard',
  client: 'Client',
  agent: 'Agent',
}

const PROVENANCE_BADGE_STATUS: Record<string, BadgeStatus> = {
  standard: 'neutral',
  client: 'active',
  agent: 'success',
}

export interface ConfigFieldProvenanceProps {
  fieldName: string
  label: string
  effectiveConfig: EffectiveConfig | undefined
  onReset?: (fieldName: string) => void
  children: ReactNode
}

export function ConfigFieldProvenance({
  fieldName,
  label,
  effectiveConfig,
  onReset,
  children,
}: ConfigFieldProvenanceProps) {
  const field = effectiveConfig?.fields[fieldName]

  if (!field) {
    return <>{children}</>
  }

  const isLocked = field.policy === 'locked'
  const canReset = field.policy === 'overridable' && field.provenance === 'agent' && Boolean(onReset)

  return (
    <div>
      {isLocked ? (
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-widest text-ink-3">{label}</span>
          <div className="text-sm text-ink px-3 py-2 rounded-md border border-line-2 bg-mist/50">
            {field.value === null || field.value === undefined ? '—' : String(field.value)}
          </div>
          <p className="text-xs text-ink-3">Locked by Qora standard — cannot be overridden.</p>
        </div>
      ) : (
        children
      )}
      <div className="flex items-center gap-2 mt-1">
        <Badge status={PROVENANCE_BADGE_STATUS[field.provenance]}>
          {PROVENANCE_LABEL[field.provenance]}
        </Badge>
        {canReset && (
          <Button
            type="button"
            variant="tertiary"
            size="sm"
            onClick={() => onReset?.(fieldName)}
          >
            Reset to inherited
          </Button>
        )}
      </div>
    </div>
  )
}
