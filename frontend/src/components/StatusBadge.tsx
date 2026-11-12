import type { MonitorStatus } from '../api/types'

const LABELS: Record<MonitorStatus, string> = {
  up: 'Up',
  down: 'Down',
  paused: 'Paused',
  unknown: 'Pending',
}

export function StatusBadge({ status }: { status: MonitorStatus }) {
  return (
    <span className={`badge badge-${status}`}>
      <span className="dot" aria-hidden="true" />
      {LABELS[status]}
    </span>
  )
}
