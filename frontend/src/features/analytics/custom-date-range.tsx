/**
 * CustomDateRange — start/end date inputs for the "Personalizado" period.
 *
 * Rendered only when period === 'custom'. Values are plain calendar dates
 * (YYYY-MM-DD) matching the AnalyticsParams.startDate/endDate contract.
 */

interface CustomDateRangeProps {
  startDate: string
  endDate: string
  onChange: (range: { startDate: string; endDate: string }) => void
}

export function CustomDateRange({ startDate, endDate, onChange }: CustomDateRangeProps) {
  return (
    <div className="ph-r" style={{ gap: 8 }}>
      <input
        type="date"
        className="select"
        aria-label="Fecha de inicio"
        value={startDate}
        max={endDate || undefined}
        onChange={(e) => onChange({ startDate: e.target.value, endDate })}
      />
      <input
        type="date"
        className="select"
        aria-label="Fecha de fin"
        value={endDate}
        min={startDate || undefined}
        onChange={(e) => onChange({ startDate, endDate: e.target.value })}
      />
    </div>
  )
}
