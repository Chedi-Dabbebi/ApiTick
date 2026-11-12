export interface StatCardProps {
  label: string
  value: string | number
  hint?: string
  tone?: 'up' | 'down'
}

/** Shared metric tile used by the dashboard and the detail page. */
export function StatCard({ label, value, hint, tone }: StatCardProps) {
  return (
    <div className={`card${tone ? ` card-${tone}` : ''}`}>
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
      {hint ? <div className="card-hint">{hint}</div> : null}
    </div>
  )
}
