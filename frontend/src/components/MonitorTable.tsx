import { Link } from 'react-router-dom'
import type { MonitorSummary } from '../api/types'
import { formatMs, formatPercent, relativeTime } from '../lib/time'
import { StatusBadge } from './StatusBadge'

interface Props {
  monitors: MonitorSummary[]
  busyId: number | null
  onPause: (monitor: MonitorSummary) => void
  onResume: (monitor: MonitorSummary) => void
  onEdit: (monitor: MonitorSummary) => void
  onDelete: (monitor: MonitorSummary) => void
}

export function MonitorTable({
  monitors,
  busyId,
  onPause,
  onResume,
  onEdit,
  onDelete,
}: Props) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Monitor</th>
            <th>Status</th>
            <th>Uptime</th>
            <th>Response</th>
            <th className="hide-sm">p95</th>
            <th className="hide-sm">Last check</th>
            <th>
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {monitors.map((monitor) => {
            const busy = busyId === monitor.id

            return (
              <tr key={monitor.id}>
                <td>
                  <Link className="row-link" to={`/monitors/${monitor.id}`}>
                    <div className="monitor-name">{monitor.name}</div>
                    <div className="monitor-url">{monitor.url}</div>
                  </Link>
                </td>
                <td>
                  <StatusBadge status={monitor.current_status} />
                </td>
                <td className="num">{formatPercent(monitor.availability)}</td>
                <td className="num">{formatMs(monitor.last_response_time_ms)}</td>
                <td className="num hide-sm muted">{formatMs(monitor.p95_ms)}</td>
                <td className="hide-sm muted">{relativeTime(monitor.last_checked_at)}</td>
                <td>
                  <div className="actions">
                    {monitor.is_active ? (
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={busy}
                        onClick={() => onPause(monitor)}
                      >
                        Pause
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={busy}
                        onClick={() => onResume(monitor)}
                      >
                        Resume
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn-ghost"
                      disabled={busy}
                      onClick={() => onEdit(monitor)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-danger"
                      disabled={busy}
                      onClick={() => onDelete(monitor)}
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
