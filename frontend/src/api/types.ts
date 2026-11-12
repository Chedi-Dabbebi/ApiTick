/** Types mirroring the FastAPI response models in backend/app/schemas.py. */

export type MonitorStatus = 'unknown' | 'up' | 'down' | 'paused'

export interface Monitor {
  id: number
  name: string
  url: string
  expected_body_contains: string | null
  check_interval_seconds: number
  is_active: boolean
  current_status: MonitorStatus
  last_checked_at: number | null
  next_check_at: number
  last_response_time_ms: number | null
  last_status_code: number | null
  created_at: number
}

/** One row of GET /api/dashboard/summary (aggregates over the window). */
export interface MonitorSummary {
  id: number
  name: string
  url: string
  expected_body_contains: string | null
  check_interval_seconds: number
  current_status: MonitorStatus
  is_active: boolean
  last_checked_at: number | null
  last_response_time_ms: number | null
  availability: number | null
  p50_ms: number | null
  p95_ms: number | null
  open_incident_since: number | null
}

export interface DashboardSummary {
  total: number
  up: number
  down: number
  paused: number
  unknown: number
  availability: number | null
  window_hours: number
  monitors: MonitorSummary[]
}

export interface MonitorInput {
  name: string
  url: string
  check_interval_seconds: number
  expected_body_contains: string | null
}

export interface Check {
  id: number
  checked_at: number
  is_success: boolean
  status_code: number | null
  response_time_ms: number
  error_message: string | null
}

export interface Incident {
  id: number
  monitor_id: number
  started_at: number
  resolved_at: number | null
  reason: string | null
}

/** GET /api/dashboard/incidents — cross-monitor feed for the dashboard. */
export interface RecentIncident extends Incident {
  monitor_name: string
}

/** GET /api/monitors/{id}/stats?window_hours= */
export interface MonitorStats {
  window_hours: number
  total_checks: number
  successes: number
  availability: number | null
  p50_ms: number | null
  p95_ms: number | null
}

/**
 * GET /api/monitors/{id}/series?window_hours=&max_points=
 * One point per check, or one per bucket when the window is dense.
 */
export interface SeriesPoint {
  t: number
  avg_ms: number
  checks: number
  failures: number
}
