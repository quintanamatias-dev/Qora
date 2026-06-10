/**
 * LeadTable — Presentational component
 *
 * Spec: sdd/qora-basic-crm/spec — Requirement: Lead Table Renders Correctly
 * Spec: sdd/qora-crm-next-action/spec — Requirement: Column Replacement in CRM Table
 * Design: Pure presentational — receives leads array + onSelectLead callback.
 *   Columns: Name, Phone, Status (Badge), Call Count, Last Called, Next Action (Badge)
 *   null last_called_at → "Never"
 *   Row click → onSelectLead(lead.id)
 */

import type { Lead, LeadStatus } from '@/api/types'
import { Badge } from '@/design/components/badge'
import { deriveNextAction } from './next-action'

// ──────────────────────────────────────────────────────────────────────────────
// Props
// ──────────────────────────────────────────────────────────────────────────────

interface LeadTableProps {
  leads: Lead[]
  onSelectLead: (leadId: string) => void
}

// ──────────────────────────────────────────────────────────────────────────────
// Pure helpers
// ──────────────────────────────────────────────────────────────────────────────

export function formatLastCalled(isoOrNull: string | null): string {
  if (!isoOrNull) return 'Never'
  try {
    return new Date(isoOrNull).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return 'Never'
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// NextActionCell — pure presentational cell for the Next Action column
// ──────────────────────────────────────────────────────────────────────────────

function NextActionCell({ lead }: { lead: Lead }) {
  const { label, badge } = deriveNextAction(lead)
  return <Badge status={badge}>{label}</Badge>
}

function formatCustomFieldsSummary(customFields: Lead['custom_fields']): string {
  const entries = Object.entries(customFields ?? {}).filter(([, value]) => value)
  if (entries.length === 0) return '—'

  const preview = entries
    .slice(0, 2)
    .map(([key, value]) => `${key.replace(/[_-]+/g, ' ')}: ${value}`)
    .join(', ')

  return entries.length > 2 ? `${preview} +${entries.length - 2}` : preview
}

// ──────────────────────────────────────────────────────────────────────────────
// LeadTable
// ──────────────────────────────────────────────────────────────────────────────

export function LeadTable({ leads, onSelectLead }: LeadTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-ink-3 text-xs uppercase tracking-wider">
            <th className="py-3 px-4 text-left font-medium">Name</th>
            <th className="py-3 px-4 text-left font-medium">Phone</th>
            <th className="py-3 px-4 text-left font-medium">Status</th>
            <th className="py-3 px-4 text-right font-medium">Calls</th>
            <th className="py-3 px-4 text-left font-medium">Last Called</th>
            <th className="py-3 px-4 text-left font-medium">Fields</th>
            <th className="py-3 px-4 text-left font-medium">Next Action</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => (
            <tr
              key={lead.id}
              role="row"
              onClick={() => onSelectLead(lead.id)}
              className="border-b border-line/50 hover:bg-pearl/50 cursor-pointer transition-colors"
            >
              <td className="py-3 px-4 font-medium text-ink">
                {lead.name}
              </td>
              <td className="py-3 px-4 text-ink-3">
                {lead.phone}
              </td>
              <td className="py-3 px-4">
                <Badge status={lead.status as LeadStatus}>
                  {lead.status.replace('_', ' ')}
                </Badge>
              </td>
              <td className="py-3 px-4 text-right text-ink-3">
                {lead.call_count}
              </td>
              <td className="py-3 px-4 text-ink-3">
                {formatLastCalled(lead.last_called_at)}
              </td>
              <td className="py-3 px-4 text-ink-3 max-w-[220px] truncate">
                {formatCustomFieldsSummary(lead.custom_fields)}
              </td>
              <td className="py-3 px-4">
                <NextActionCell lead={lead} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
