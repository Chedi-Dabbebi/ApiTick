import type { DashboardSummary } from '../api/types'
import { formatPercent } from '../lib/time'
import { StatCard } from './StatCard'

export function SummaryCards({ summary }: { summary: DashboardSummary | null }) {
  const windowHours = summary?.window_hours ?? 24

  return (
    <section className="cards" aria-label="Overview">
      <StatCard
        label="Monitors"
        value={summary ? summary.total : '—'}
        hint={
          summary && summary.paused > 0
            ? `${summary.paused} paused`
            : summary && summary.unknown > 0
              ? `${summary.unknown} pending`
              : undefined
        }
      />
      <StatCard label="Up" value={summary ? summary.up : '—'} tone="up" />
      <StatCard label="Down" value={summary ? summary.down : '—'} tone="down" />
      <StatCard
        label={`Availability · ${windowHours}h`}
        value={formatPercent(summary?.availability ?? null)}
        hint="based on recorded checks"
      />
    </section>
  )
}
