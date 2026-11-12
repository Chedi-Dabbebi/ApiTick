import type {
  Check,
  DashboardSummary,
  Incident,
  Monitor,
  MonitorInput,
  MonitorStats,
  RecentIncident,
  SeriesPoint,
} from './types'

const BASE = '/api'

interface RequestOptions {
  method?: string
  body?: unknown
  signal?: AbortSignal
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }

  const response = await fetch(`${BASE}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  if (response.status === 204) {
    return undefined as unknown as T
  }

  return (await response.json()) as T
}

/** Turn FastAPI's {detail: string | [{msg}]} error body into one readable line. */
async function readError(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail
      if (typeof detail === 'string') {
        return detail
      }
      if (Array.isArray(detail)) {
        const messages = detail
          .map((item) =>
            item && typeof item === 'object' && 'msg' in item
              ? String((item as { msg: unknown }).msg)
              : null,
          )
          .filter((message): message is string => message !== null)
        if (messages.length > 0) {
          return messages.join('; ')
        }
      }
    }
  } catch {
    // Not JSON — fall through to the generic message.
  }
  return `Request failed with status ${response.status}`
}

export const api = {
  summary: (windowHours: number, signal?: AbortSignal) =>
    request<DashboardSummary>(`/dashboard/summary?window_hours=${windowHours}`, { signal }),

  recentIncidents: (limit = 8, signal?: AbortSignal) =>
    request<RecentIncident[]>(`/dashboard/incidents?limit=${limit}`, { signal }),

  listMonitors: (signal?: AbortSignal) => request<Monitor[]>('/monitors', { signal }),

  getMonitor: (id: number, signal?: AbortSignal) =>
    request<Monitor>(`/monitors/${id}`, { signal }),

  createMonitor: (input: MonitorInput) =>
    request<Monitor>('/monitors', { method: 'POST', body: input }),

  updateMonitor: (id: number, input: Partial<MonitorInput>) =>
    request<Monitor>(`/monitors/${id}`, { method: 'PATCH', body: input }),

  deleteMonitor: (id: number) => request<void>(`/monitors/${id}`, { method: 'DELETE' }),

  pauseMonitor: (id: number) =>
    request<Monitor>(`/monitors/${id}/pause`, { method: 'POST' }),

  resumeMonitor: (id: number) =>
    request<Monitor>(`/monitors/${id}/resume`, { method: 'POST' }),

  listChecks: (
    id: number,
    options: { limit?: number; since?: number; signal?: AbortSignal } = {},
  ) => {
    const params = new URLSearchParams({ limit: String(options.limit ?? 200) })
    if (options.since !== undefined) params.set('since', String(options.since))
    return request<Check[]>(`/monitors/${id}/checks?${params}`, { signal: options.signal })
  },

  listIncidents: (id: number, signal?: AbortSignal) =>
    request<Incident[]>(`/monitors/${id}/incidents`, { signal }),

  stats: (id: number, windowHours: number, signal?: AbortSignal) =>
    request<MonitorStats>(`/monitors/${id}/stats?window_hours=${windowHours}`, { signal }),

  series: (id: number, windowHours: number, maxPoints = 300, signal?: AbortSignal) =>
    request<SeriesPoint[]>(
      `/monitors/${id}/series?window_hours=${windowHours}&max_points=${maxPoints}`,
      { signal },
    ),
}
