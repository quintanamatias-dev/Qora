/**
 * LeadTable — Presentational component
 *
 * Spec: sdd/qora-basic-crm/spec — Requirement: Lead Table Renders Correctly
 * Design: Pure presentational — receives leads array + onSelectLead callback.
 *   Columns: Name, Phone, Status (Badge), Call Count, Last Called, Interest Level
 *   null interest_level → "—"
 *   null last_called_at → "Never"
 *   Row click → onSelectLead(lead.id)
 */

import type { Lead, LeadStatus } from '@/api/types'
import { Badge } from '@/design/components/badge'

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

export function formatInterestLevel(level: number | null): string {
  if (level === null || level === undefined) return '—'
  return `${level}%`
}

// ──────────────────────────────────────────────────────────────────────────────
// LeadTable
// ──────────────────────────────────────────────────────────────────────────────

export function LeadTable({ leads, onSelectLead }: LeadTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-outline/20 text-on-surface-variant text-xs uppercase tracking-wider">
            <th className="py-3 px-4 text-left font-medium">Name</th>
            <th className="py-3 px-4 text-left font-medium">Phone</th>
            <th className="py-3 px-4 text-left font-medium">Status</th>
            <th className="py-3 px-4 text-right font-medium">Calls</th>
            <th className="py-3 px-4 text-left font-medium">Last Called</th>
            <th className="py-3 px-4 text-right font-medium">Interest</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => (
            <tr
              key={lead.id}
              role="row"
              onClick={() => onSelectLead(lead.id)}
              className="border-b border-outline/10 hover:bg-surface-container-low cursor-pointer transition-colors"
            >
              <td className="py-3 px-4 font-medium text-on-surface">
                {lead.name}
              </td>
              <td className="py-3 px-4 text-on-surface-variant">
                {lead.phone}
              </td>
              <td className="py-3 px-4">
                <Badge status={lead.status as LeadStatus}>
                  {lead.status.replace('_', ' ')}
                </Badge>
              </td>
              <td className="py-3 px-4 text-right text-on-surface-variant">
                {lead.call_count}
              </td>
              <td className="py-3 px-4 text-on-surface-variant">
                {formatLastCalled(lead.last_called_at)}
              </td>
              <td className="py-3 px-4 text-right text-on-surface-variant">
                {formatInterestLevel(lead.interest_level)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
