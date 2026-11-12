import { useCallback, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'
import type { Check, Incident, Monitor, MonitorStats, SeriesPoint } from '../api/types'
import { StatCard } from '../components/StatCard'
import { StatusBadge } from '../components/StatusBadge'
import { usePolling } from '../hooks/usePolling'
import {
  countdown,
  formatAxisTime,
  formatDateTime,
  formatDuration,
  formatMs,
  formatPercent,
  relativeTime,
} from '../lib/time'

const POLL_MS = 15_000
/** The API buckets the series server-side; this is the point budget. */
const MAX_CHART_POINTS = 300
const TABLE_ROWS = 100

interface ChartPoint {
  t: number
  ms: number
  /** Non-null only for buckets containing failures, so red dots stand out. */
  failMs: number | null
  checks: number
  failures: number
}

interface DetailData {
  /** The window the data belongs to — the labels follow the data, not the toggle. */
  windowHours: number
  /** Wall clock captured at fetch time, so render stays pure. */
  now: number
  monitor: Monitor
  stats24: MonitorStats
  stats7d: MonitorStats
  checks: Check[]
  series: SeriesPoint[]
  incidents: Incident[]
}

export function MonitorDetail() {
  const { id } = useParams()
  const monitorId = Number(id)
  const validId = Number.isInteger(monitorId) && monitorId > 0
  const [windowHours, setWindowHours] = useState<24 | 168>(24)

  const fetcher = useCallback(
    async (signal: AbortSignal): Promise<DetailData> => {
      if (!validId) throw new Error('Monitor not found')

      // Fetch the monitor first: if it is gone, don't fire more doomed
      // requests for its history.
      const monitor = await api.getMonitor(monitorId, signal)
      const since = Date.now() - windowHours * 3_600_000
      const [stats24, stats7d, checks, series, incidents] = await Promise.all([
        api.stats(monitorId, 24, signal),
        api.stats(monitorId, 168, signal),
        api.listChecks(monitorId, { limit: TABLE_ROWS, since, signal }),
        api.series(monitorId, windowHours, MAX_CHART_POINTS, signal),
        api.listIncidents(monitorId, signal),
      ])
      return {
        windowHours,
        now: Date.now(),
        monitor,
        stats24,
        stats7d,
        checks,
        series,
        incidents,
      }
    },
    [validId, monitorId, windowHours],
  )

  const { data, error, refresh } = usePolling(fetcher, POLL_MS, windowHours)

  const checks = data?.checks ?? []
  const chartData = useMemo<ChartPoint[]>(
    () =>
      (data?.series ?? []).map((point) => ({
        t: point.t,
        ms: point.avg_ms,
        failMs: point.failures > 0 ? point.avg_ms : null,
        checks: point.checks,
        failures: point.failures,
      })),
    [data],
  )

  if (error && !data) {
    const missing = error === 'Monitor not found'
    return (
      <div className="panel">
        <Link className="back-link" to="/">
          ← Back to dashboard
        </Link>
        <h1>{missing ? 'Monitor not found' : 'Could not load this monitor'}</h1>
        <p className="muted">
          {missing ? 'It may have been deleted.' : error}
        </p>
      </div>
    )
  }

  if (!data) {
    return <div className="panel muted">Loading…</div>
  }

  const { monitor, stats24, stats7d, incidents } = data
  const shownWindow = data.windowHours
  const stats = shownWindow === 24 ? stats24 : stats7d
  const windowLabel = shownWindow === 24 ? '24h' : '7d'
  const openIncident = incidents.find((incident) => incident.resolved_at === null)

  return (
    <>
      <Link className="back-link" to="/">
        ← Back to dashboard
      </Link>

      <div className="page-head">
        <div>
          <div className="detail-title">
            <h1>{monitor.name}</h1>
            <StatusBadge status={monitor.current_status} />
          </div>
          <p className="detail-url">{monitor.url}</p>
          {monitor.expected_body_contains ? (
            <p className="muted detail-meta">
              Response must contain <code>{monitor.expected_body_contains}</code>
            </p>
          ) : null}
          <p className="muted detail-meta">
            Every {monitor.check_interval_seconds}s
            {monitor.is_active
              ? ` · next check ${countdown(monitor.next_check_at)}`
              : ' · paused'}
            {` · last check ${relativeTime(monitor.last_checked_at)}`}
          </p>
        </div>
        <button type="button" className="btn" onClick={refresh}>
          Refresh
        </button>
      </div>

      {openIncident ? (
        <div className="error">
          Incident ongoing for {formatDuration(data.now - openIncident.started_at)}
          {openIncident.reason ? ` — ${openIncident.reason}` : ''}
        </div>
      ) : null}

      <section className="cards" aria-label="Availability">
        <StatCard
          label="Availability · 24h"
          value={formatPercent(stats24.availability)}
          hint={sampleHint(stats24)}
        />
        <StatCard
          label="Availability · 7d"
          value={formatPercent(stats7d.availability)}
          hint={sampleHint(stats7d)}
        />
        <StatCard label={`p50 · ${windowLabel}`} value={formatMs(stats.p50_ms)} />
        <StatCard label={`p95 · ${windowLabel}`} value={formatMs(stats.p95_ms)} />
      </section>

      <div className="detail-grid">
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Latency</h2>
              <p className="muted panel-sub">
                Average response time per interval. Red dots mark intervals with failed
                checks.
              </p>
            </div>
            <div className="actions window-toggle" role="group" aria-label="Window">
              <button
                type="button"
                className={`btn${shownWindow === 24 ? ' btn-primary' : ''}`}
                onClick={() => setWindowHours(24)}
              >
                24h
              </button>
              <button
                type="button"
                className={`btn${shownWindow === 168 ? ' btn-primary' : ''}`}
                onClick={() => setWindowHours(168)}
              >
                7d
              </button>
            </div>
          </div>

          {chartData.length === 0 ? (
            <p className="muted">No checks recorded in this window yet.</p>
          ) : (
            <div className="chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid
                    stroke="var(--border)"
                    strokeDasharray="3 3"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="t"
                    type="number"
                    domain={['dataMin', 'dataMax']}
                    tickFormatter={(value) => formatAxisTime(Number(value), shownWindow)}
                    stroke="var(--muted)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={{ stroke: 'var(--border)' }}
                    minTickGap={44}
                  />
                  <YAxis
                    stroke="var(--muted)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                    width={56}
                    domain={[0, (dataMax: number) => Math.round(dataMax * 1.2)]}
                    tickFormatter={(value) => `${Number(value)}ms`}
                  />
                  <Tooltip
                    content={<ChartTooltip />}
                    cursor={{ stroke: 'var(--border)' }}
                  />
                  <Line
                    type="linear"
                    dataKey="ms"
                    stroke="var(--accent)"
                    strokeWidth={2}
                    dot={false}
                    activeDot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    type="linear"
                    dataKey="failMs"
                    stroke="none"
                    dot={{ r: 3.5, fill: 'var(--down)', strokeWidth: 0 }}
                    activeDot={false}
                    isAnimationActive={false}
                    connectNulls={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section className="panel">
          <h2>Recent checks</h2>
          <p className="muted panel-sub">
            Newest first, up to {TABLE_ROWS} rows in the {windowLabel} window.
          </p>

          {checks.length === 0 ? (
            <p className="muted">No checks in this window yet.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Result</th>
                    <th>Code</th>
                    <th>Latency</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {checks.map((check) => (
                    <tr key={check.id}>
                      <td className="muted">{formatDateTime(check.checked_at)}</td>
                      <td>
                        {check.is_success ? (
                          <span className="ok">OK</span>
                        ) : (
                          <span className="fail">Failed</span>
                        )}
                      </td>
                      <td className="num">{check.status_code ?? '—'}</td>
                      <td className="num">{formatMs(check.response_time_ms)}</td>
                      <td className="muted error-cell">{check.error_message ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel">
          <h2>Incidents</h2>
          <p className="muted panel-sub">Open incidents first, then the most recent resolved.</p>

          {incidents.length === 0 ? (
            <p className="muted">No incidents recorded.</p>
          ) : (
            <ul className="incidents">
              {incidents.map((incident) => {
                const ongoing = incident.resolved_at === null
                const duration = (incident.resolved_at ?? data.now) - incident.started_at

                return (
                  <li key={incident.id} className="incident">
                    <div className="incident-main">
                      <span className={`badge ${ongoing ? 'badge-down' : 'badge-unknown'}`}>
                        {ongoing ? 'Ongoing' : 'Resolved'}
                      </span>
                      <span className="incident-reason">
                        {incident.reason ?? 'Unspecified failure'}
                      </span>
                    </div>
                    <div className="muted incident-meta">
                      {formatDateTime(incident.started_at)} · lasted {formatDuration(duration)}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>
    </>
  )
}

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ payload?: ChartPoint }>
}) {
  const point = active ? payload?.[0]?.payload : undefined
  if (!point) return null

  return (
    <div className="chart-tooltip">
      <div className="muted">{formatDateTime(point.t)}</div>
      <div className="chart-tooltip-value">{formatMs(point.ms)} avg</div>
      <div className="muted">
        {point.checks} check{point.checks === 1 ? '' : 's'}
        {point.failures > 0 ? ` · ${point.failures} failed` : ''}
      </div>
    </div>
  )
}

function sampleHint(stats: MonitorStats): string {
  if (stats.total_checks === 0) return 'no checks yet'
  return `${stats.successes} of ${stats.total_checks} checks ok`
}
