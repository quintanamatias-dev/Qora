/**
 * next-action.ts — Pure helpers for CRM Next Action Column (Issue #27)
 *
 * Spec: sdd/qora-crm-next-action/spec — Requirement: Derive Next Action State
 *       + Relative Time Formatting
 * Design: Pure functions — testable without DOM, no side effects.
 *
 * Exports:
 *   - deriveNextAction(lead, now?) → { label, badge }
 *   - formatRelativeTime(isoDate, now?) → string
 */

import type { Lead } from '@/api/types'
import type { BadgeStatus } from '@/design/components/badge'

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

export interface NextActionResult {
  label: string
  badge: BadgeStatus
}

// ──────────────────────────────────────────────────────────────────────────────
// formatRelativeTime
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Format a future ISO date string into a human-readable Spanish relative label.
 *
 * Time bands:
 *   < 60 min     → "En Xm"
 *   same day     → "En Xh"
 *   next day     → "Mañana HH:MM"
 *   > 1 day      → "En X días"
 *
 * @param isoDate - ISO 8601 UTC date string (future)
 * @param now     - Reference Date for testability (defaults to new Date())
 */
export function formatRelativeTime(isoDate: string, now: Date = new Date()): string {
  const target = new Date(isoDate)
  const diffMs = target.getTime() - now.getTime()
  const diffMinutes = Math.round(diffMs / (1000 * 60))
  const diffHours = Math.round(diffMs / (1000 * 60 * 60))
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24))

  // < 60 minutes
  if (diffMinutes < 60) {
    return `En ${diffMinutes}m`
  }

  // Same calendar day: >= 60 min but < next calendar day
  const nowDate = new Date(now)
  const targetDate = new Date(target)

  // Check if it's the next calendar day (tomorrow)
  const nowMidnight = new Date(
    nowDate.getFullYear(),
    nowDate.getMonth(),
    nowDate.getDate() + 1
  )
  const dayAfterMidnight = new Date(
    nowDate.getFullYear(),
    nowDate.getMonth(),
    nowDate.getDate() + 2
  )

  if (targetDate >= nowMidnight && targetDate < dayAfterMidnight) {
    // Tomorrow — show "Mañana HH:MM" in local time
    const hh = String(target.getHours()).padStart(2, '0')
    const mm = String(target.getMinutes()).padStart(2, '0')
    return `Mañana ${hh}:${mm}`
  }

  // Same day (today)
  if (targetDate < nowMidnight) {
    return `En ${diffHours}h`
  }

  // > 1 day ahead
  return `En ${diffDays} días`
}

// ──────────────────────────────────────────────────────────────────────────────
// deriveNextAction
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Derive the Next Action state for a lead using the 4-state priority chain.
 *
 * Priority chain (highest wins):
 *   1. Closed   — do_not_call=true OR status='not_interested' → Cerrado / error
 *   2. Scheduled future — next_scheduled_call_at in the future → relative label / active
 *   3. Overdue  — next_scheduled_call_at in the past → Atrasado / warning
 *   4. Sin agenda — call_count > 0, no schedule → Sin agenda / warning
 *   5. Pendiente — default (new, never contacted) → Pendiente / neutral
 *
 * @param lead - Lead object (must include next_scheduled_call_at field)
 * @param now  - Reference Date for testability (defaults to new Date())
 */
export function deriveNextAction(lead: Lead, now: Date = new Date()): NextActionResult {
  // Priority 1: Closed
  if (lead.do_not_call || lead.status === 'not_interested') {
    return { label: 'Cerrado', badge: 'error' }
  }

  // Priority 2 & 3: Scheduled call
  if (lead.next_scheduled_call_at != null) {
    const scheduledAt = new Date(lead.next_scheduled_call_at)
    if (scheduledAt > now) {
      // Future — show relative time
      return {
        label: formatRelativeTime(lead.next_scheduled_call_at, now),
        badge: 'active',
      }
    } else {
      // Past — overdue
      return { label: 'Atrasado', badge: 'warning' }
    }
  }

  // Priority 4: Contacted but no scheduled call
  if (lead.call_count > 0) {
    return { label: 'Sin agenda', badge: 'warning' }
  }

  // Priority 5: Default — new lead, never contacted
  return { label: 'Pendiente', badge: 'neutral' }
}
