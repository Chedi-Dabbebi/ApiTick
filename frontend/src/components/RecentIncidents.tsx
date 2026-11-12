import { Link } from 'react-router-dom'
import type { RecentIncident } from '../api/types'
import { formatDateTime, formatDuration } from '../lib/time'

interface Props {
  incidents: RecentIncident[]
  /** Wall clock captured with the data, so open durations stay stable between polls. */
  now: number
}

/** Cross-monitor incident feed under the dashboard table. */
export function RecentIncidents({ incidents, now }: Props) {
  return (
    <section className="panel incidents-panel" aria-label="Recent incidents">
      <h2>Recent incidents</h2>
      <p className="muted panel-sub">
        Open incidents first, then the most recently resolved across all monitors.
      </p>

      {incidents.length === 0 ? (
        <p className="muted">No incidents recorded.</p>
      ) : (
        <ul className="incidents">
          {incidents.map((incident) => {
            const ongoing = incident.resolved_at === null
            const duration = (incident.resolved_at ?? now) - incident.started_at

            return (
              <li key={incident.id} className="incident">
                <div className="incident-main">
                  <span className={`badge ${ongoing ? 'badge-down' : 'badge-unknown'}`}>
                    {ongoing ? 'Ongoing' : 'Resolved'}
                  </span>
                  <Link className="incident-monitor" to={`/monitors/${incident.monitor_id}`}>
                    {incident.monitor_name}
                  </Link>
                  <span className="incident-reason">
                    {incident.reason ?? 'Unspecified failure'}
                  </span>
                </div>
                <div className="muted incident-meta">
                  {formatDateTime(incident.started_at)} ·{' '}
                  {ongoing ? 'ongoing ' : 'lasted '}
                  {formatDuration(duration)}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
