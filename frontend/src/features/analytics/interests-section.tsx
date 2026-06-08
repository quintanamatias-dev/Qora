/**
 * InterestsSection — Top interests with trend indicators
 *
 * Shows: interest name, count, trend indicator (↑ / → / ↓)
 * Design: presentational, receives data as props.
 */

import type { AnalyticsInterestsResponse } from '@/api/types'

interface InterestsSectionProps {
  data: AnalyticsInterestsResponse
}

const TREND_ICON: Record<string, string> = {
  up: '↑',
  down: '↓',
  stable: '→',
}

const TREND_CLASS: Record<string, string> = {
  up: 'text-green-600',
  down: 'text-red-500',
  stable: 'text-yellow-500',
}

export function InterestsSection({ data }: InterestsSectionProps) {
  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-ink">Top Interests</h2>
      {data.interests.length === 0 ? (
        <p className="text-sm text-ink-3">No interests recorded.</p>
      ) : (
        <ul className="space-y-2">
          {data.interests.map((item) => (
            <li
              key={item.interest}
              className="flex items-center justify-between bg-paper border border-line rounded-lg px-4 py-3"
            >
              <span className="text-sm text-ink font-medium">{item.interest}</span>
              <div className="flex items-center gap-3">
                <span className="text-sm font-bold text-teal">{item.count}</span>
                <span
                  className={`text-lg font-bold ${TREND_CLASS[item.trend] ?? 'text-ink-3'}`}
                  title={`Trend: ${item.trend} (prev: ${item.previous_count})`}
                >
                  {TREND_ICON[item.trend] ?? '?'}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
