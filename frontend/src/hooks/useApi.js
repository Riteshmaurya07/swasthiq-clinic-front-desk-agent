import { useCallback, useEffect, useRef, useState } from "react"

/**
 * Minimal fetch hook: { data, error, loading, refetch }.
 * Guards against setState-after-unmount; no polling by design.
 */
export function useAsync(fetcher, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const alive = useRef(true)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  useEffect(() => {
    alive.current = true
    setState((prev) => ({ ...prev, loading: true, error: null }))
    fetcherRef.current()
      .then((data) => {
        if (alive.current) setState({ data, error: null, loading: false })
      })
      .catch((error) => {
        if (alive.current) setState({ data: null, error, loading: false })
      })
    return () => {
      alive.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  const refetch = useCallback(() => {
    setState((prev) => ({ ...prev, loading: true, error: null }))
    return fetcherRef.current()
      .then((data) => {
        if (alive.current) setState({ data, error: null, loading: false })
        return data
      })
      .catch((error) => {
        if (alive.current) setState({ data: null, error, loading: false })
        throw error
      })
  }, [])

  return { ...state, refetch }
}
