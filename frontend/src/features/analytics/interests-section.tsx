/**
 * InterestsSection — "Temas e intereses principales" list with trend indicators
 *
 * Design: qora-presentacion/project/dashboard/screens-overview.jsx Analytics
 * Trend direction (up/down/stable) comes from the real interests API field.
 */

import type { AnalyticsInterestsResponse, InterestItem } from '@/api/types'
import { Icon } from '@/design/components'

interface InterestsSectionProps {
  data: AnalyticsInterestsResponse
}

const TREND_TAG_CLASS: Record<InterestItem['trend'], string> = {
  up: 'tag teal num',
  down: 'tag coral num',
  stable: 'tag ghost num',
}

const TREND_ROTATION: Record<InterestItem['trend'], number> = {
  up: 0,
  down: 180,
  stable: 90,
}

export function InterestsSection({ data }: InterestsSectionProps) {
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <h3>Temas e intereses principales</h3>
          <p>Lo que más se repite en las llamadas</p>
        </div>
      </div>
      {data.interests.length === 0 ? (
        <div className="empty">Sin temas ni intereses en este período.</div>
      ) : (
        <div className="rows">
          {data.interests.map((item, i) => (
            <div key={item.interest} className="row">
              <span className="mono muted" style={{ fontSize: 11, width: 22 }}>
                {String(i + 1).padStart(2, '0')}
              </span>
              <div className="t">
                <b style={{ fontWeight: 400, whiteSpace: 'normal' }}>{item.interest}</b>
              </div>
              <span
                className={TREND_TAG_CLASS[item.trend]}
                data-testid={`interest-trend-${item.trend}`}
                title={`Tendencia: ${item.trend} (anterior: ${item.previous_count})`}
              >
                <span style={{ display: 'inline-flex', transform: `rotate(${TREND_ROTATION[item.trend]}deg)` }}>
                  <Icon name="arrowUp" size={12} strokeWidth={2} />
                </span>
                {item.count}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
