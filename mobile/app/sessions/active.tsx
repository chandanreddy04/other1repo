/**
 * Active-session shim — the id-less entry point pushes, notification taps,
 * and the Live Activity deep link (`madeithome://sessions/active`) land on,
 * since they don't carry a session id. Redirects to the real resource at
 * /sessions/{id}:
 *   - store already holds a session → redirect IMMEDIATELY (the session
 *     screen renders the store copy at once) and refresh the store in the
 *     background;
 *   - store empty (cold start) → wait for `loadActiveSession()`, then
 *     redirect to it, or Home when there is no active session.
 *
 * Related: app/sessions/[id].tsx, store/useSessionStore.ts.
 */
import { useEffect, useState } from 'react'
import { Redirect } from 'expo-router'
import { useSessionStore } from '../../store/useSessionStore'

export default function ActiveSessionRedirect() {
  const activeSession = useSessionStore(state => state.activeSession)
  const loadActiveSession = useSessionStore(state => state.loadActiveSession)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    loadActiveSession()
      .catch(() => {
        // benign: the store reports; a failed load just falls through to
        // "no active session" and redirects Home
      })
      .finally(() => setLoaded(true))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (activeSession) return <Redirect href={`/sessions/${activeSession.id}`} />
  if (!loaded) return null
  return <Redirect href="/(tabs)" />
}
