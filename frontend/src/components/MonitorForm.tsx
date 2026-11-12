import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { MonitorInput } from '../api/types'

interface Props {
  /** Existing values when editing, null when creating. */
  initial: MonitorInput | null
  onClose: () => void
  /** Should reject with an Error when the server refuses the input. */
  onSubmit: (input: MonitorInput) => Promise<void>
}

export function MonitorForm({ initial, onClose, onSubmit }: Props) {
  const [name, setName] = useState(initial?.name ?? '')
  const [url, setUrl] = useState(initial?.url ?? 'https://')
  const [intervalSeconds, setIntervalSeconds] = useState(
    String(initial?.check_interval_seconds ?? 60),
  )
  const [bodyContains, setBodyContains] = useState(initial?.expected_body_contains ?? '')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      await onSubmit({
        name: name.trim(),
        url: url.trim(),
        check_interval_seconds: Number(intervalSeconds),
        expected_body_contains: bodyContains.trim() || null,
      })
      // On success the parent unmounts this form.
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the monitor')
      setSubmitting(false)
    }
  }

  return (
    <div
      className="overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <form className="dialog" onSubmit={handleSubmit}>
        <h2>{initial ? 'Edit monitor' : 'Add monitor'}</h2>
        <p className="muted dialog-sub">
          The worker checks this URL from this machine at the chosen interval.
        </p>

        {error ? <div className="error">{error}</div> : null}

        <div className="field">
          <label htmlFor="monitor-name">Name</label>
          <input
            id="monitor-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Payments API"
            maxLength={120}
            required
            autoFocus
          />
        </div>

        <div className="field">
          <label htmlFor="monitor-url">URL</label>
          <input
            id="monitor-url"
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://api.example.com/health"
            required
          />
          <span className="hint">
            Public http(s) URLs only — private and local addresses are blocked.
          </span>
        </div>

        <div className="field">
          <label htmlFor="monitor-body">Response must contain (optional)</label>
          <input
            id="monitor-body"
            value={bodyContains}
            onChange={(event) => setBodyContains(event.target.value)}
            placeholder={'"status":"ok"'}
            maxLength={500}
          />
          <span className="hint">
            Fails the check when this text is missing from the first 64 kB of the
            response body. Leave empty to check the status code only.
          </span>
        </div>

        <div className="field">
          <label htmlFor="monitor-interval">Check every (seconds)</label>
          <input
            id="monitor-interval"
            type="number"
            min={10}
            max={86400}
            value={intervalSeconds}
            onChange={(event) => setIntervalSeconds(event.target.value)}
            required
          />
        </div>

        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? 'Saving…' : initial ? 'Save changes' : 'Add monitor'}
          </button>
        </div>
      </form>
    </div>
  )
}
