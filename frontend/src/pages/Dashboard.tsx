import { useState } from 'react'
import { api } from '../api/client'
import type { DashboardSummary, MonitorInput, MonitorSummary, RecentIncident } from '../api/types'
import { MonitorForm } from '../components/MonitorForm'
import { MonitorTable } from '../components/MonitorTable'
import { RecentIncidents } from '../components/RecentIncidents'
import { SummaryCards } from '../components/SummaryCards'
import { usePolling } from '../hooks/usePolling'

type FormState =
  | { mode: 'closed' }
  | { mode: 'create' }
  | { mode: 'edit'; monitor: MonitorSummary }

interface DashboardData {
  summary: DashboardSummary
  incidents: RecentIncident[]
  /** Captured with the data so open-incident durations don't drift on re-render. */
  now: number
}

export function Dashboard() {
  const { data, error, loading, refresh } = usePolling<DashboardData>(async (signal) => {
    const [summary, incidents] = await Promise.all([
      api.summary(24, signal),
      api.recentIncidents(8, signal),
    ])
    return { summary, incidents, now: Date.now() }
  }, 10_000)

  const [form, setForm] = useState<FormState>({ mode: 'closed' })
  const [busyId, setBusyId] = useState<number | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  async function runAction(action: () => Promise<unknown>) {
    setActionError(null)
    try {
      await action()
      refresh()
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : 'Action failed')
    }
  }

  async function handleSubmit(input: MonitorInput) {
    if (form.mode === 'edit') {
      await api.updateMonitor(form.monitor.id, input)
    } else {
      await api.createMonitor(input)
    }
    setForm({ mode: 'closed' })
    refresh()
  }

  function handlePause(monitor: MonitorSummary) {
    setBusyId(monitor.id)
    void runAction(() => api.pauseMonitor(monitor.id)).finally(() => setBusyId(null))
  }

  function handleResume(monitor: MonitorSummary) {
    setBusyId(monitor.id)
    void runAction(() => api.resumeMonitor(monitor.id)).finally(() => setBusyId(null))
  }

  function handleDelete(monitor: MonitorSummary) {
    const confirmed = window.confirm(
      `Delete "${monitor.name}" and all of its history? This cannot be undone.`,
    )
    if (!confirmed) return

    setBusyId(monitor.id)
    void runAction(() => api.deleteMonitor(monitor.id)).finally(() => setBusyId(null))
  }

  const monitors = data?.summary.monitors ?? []

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Monitors</h1>
          <p className="muted">Endpoints checked from this machine on a fixed interval.</p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setForm({ mode: 'create' })}
        >
          Add monitor
        </button>
      </div>

      {error ? <div className="error">Could not load the dashboard: {error}</div> : null}
      {actionError ? <div className="error">{actionError}</div> : null}

      <SummaryCards summary={data?.summary ?? null} />

      {loading && !data ? (
        <div className="panel muted">Loading…</div>
      ) : monitors.length === 0 ? (
        <div className="panel empty">
          <h2>No monitors yet</h2>
          <p className="muted">
            Add a public URL and it will be checked within a few seconds.
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setForm({ mode: 'create' })}
          >
            Add your first monitor
          </button>
        </div>
      ) : (
        <>
          <MonitorTable
            monitors={monitors}
            busyId={busyId}
            onPause={handlePause}
            onResume={handleResume}
            onEdit={(monitor) => setForm({ mode: 'edit', monitor })}
            onDelete={handleDelete}
          />
          {data ? <RecentIncidents incidents={data.incidents} now={data.now} /> : null}
        </>
      )}

      {form.mode !== 'closed' ? (
        <MonitorForm
          initial={
            form.mode === 'edit'
              ? {
                  name: form.monitor.name,
                  url: form.monitor.url,
                  check_interval_seconds: form.monitor.check_interval_seconds,
                  expected_body_contains: form.monitor.expected_body_contains,
                }
              : null
          }
          onClose={() => setForm({ mode: 'closed' })}
          onSubmit={handleSubmit}
        />
      ) : null}
    </>
  )
}
