/**
 * ServiceIssuesSection — Ranked list of service issues
 *
 * Shows: issue name, count, rank badge
 * Design: presentational, receives data as props.
 */

import type { AnalyticsServiceIssuesResponse } from '@/api/types'

interface ServiceIssuesSectionProps {
  data: AnalyticsServiceIssuesResponse
}

export function ServiceIssuesSection({ data }: ServiceIssuesSectionProps) {
  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-on-surface">Service Issues</h2>
      {data.issues.length === 0 ? (
        <p className="text-sm text-on-surface-variant">No service issues recorded.</p>
      ) : (
        <ul className="space-y-2">
          {data.issues.map((item) => (
            <li
              key={item.issue}
              className="flex items-center justify-between bg-surface-container rounded-lg px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <span className="text-xs font-bold text-on-surface-variant w-5 text-right">
                  #{item.rank}
                </span>
                <span className="text-sm text-on-surface font-medium">{item.issue}</span>
              </div>
              <span className="text-sm font-bold text-primary">{item.count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
