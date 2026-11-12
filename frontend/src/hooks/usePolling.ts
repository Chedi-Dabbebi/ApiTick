import { useCallback, useEffect, useRef, useState } from 'react'

export interface PollingResult<T> {
  data: T | null
  error: string | null
  loading: boolean
  /** Force an immediate refetch (used after mutations). */
  refresh: () => void
}

/**
 * Fetch on mount, then every `intervalMs`. Cancels in-flight requests on
 * unmount and never shows an error caused by our own abort.
 *
 * `restartKey` forces an immediate refetch when it changes (e.g. switching the
 * detail page between 24h and 7d) without changing the polling interval.
 */
export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs = 10_000,
  restartKey?: unknown,
): PollingResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  // Keep the latest fetcher without restarting the interval on every render.
  // Assigned in an effect (not during render) so React's ref rules hold; this
  // effect is declared first, so it runs before the polling effect on mount.
  const fetcherRef = useRef(fetcher)

  useEffect(() => {
    fetcherRef.current = fetcher
  })

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    async function tick(isInitial: boolean) {
      try {
        const result = await fetcherRef.current(controller.signal)
        if (cancelled) return
        setData(result)
        setError(null)
      } catch (cause) {
        if (cancelled || controller.signal.aborted) return
        setError(cause instanceof Error ? cause.message : 'Unknown error')
      } finally {
        if (!cancelled && isInitial) setLoading(false)
      }
    }

    void tick(true)
    const timer = window.setInterval(() => void tick(false), intervalMs)

    return () => {
      cancelled = true
      controller.abort()
      window.clearInterval(timer)
    }
  }, [intervalMs, nonce, restartKey])

  const refresh = useCallback(() => setNonce((value) => value + 1), [])

  return { data, error, loading, refresh }
}
