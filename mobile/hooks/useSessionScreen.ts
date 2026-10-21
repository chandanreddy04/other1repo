/**
 * Data source + live escalation poll for the merged session screen
 * (`app/sessions/[id].tsx`). The screen renders whatever `session` this
 * returns, in the `mode` its status maps to (utils/sessionMode.ts).
 *
 * Sources (see `pickSessionSource`): the by-id fetch (`GET /sessions/{id}`)
 * and the store's `activeSession` — the store copy wins only while it IS
 * this session and is live (so the screen agrees with Home and the Live
 * Activity); an ended fetched copy always wins (terminal is final). When the
 * store already holds this session the screen renders it immediately — no
 * spinner while the by-id fetch runs.
 *
 * Live escalation poll (docs/flow-review.md C1/3.4, domain-sessions-alerts
 * "Server truth for notified and acknowledged"): from T-2min, every 20s,
 * `GET /sessions/{id}` (it computes alert_acknowledged/circle_unreachable)
 * → the fetched copy, AND the store when the store holds this session, with
 * a Live Activity update only when status/acknowledged/unreachable changed.
 * Stops at alerted+acknowledged or once the session ended. Effect deps are
 * primitives (id, status, acknowledged, deadline) so a refresh that swaps
 * the session object can never re-trigger the effect into a request loop.
 *
 * Ending while open: when the store stops holding this session live (marked
 * safe, ended elsewhere), the screen re-fetches by id and flips to ended
 * mode in place — no bounce, no stale live view.
 *
 * Related: app/sessions/[id].tsx, utils/sessionMode.ts,
 *          store/useSessionStore.ts, app/(tabs)/index.tsx (Home's one-shot
 *          refreshes use the same store-write pattern).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import api from '../services/api'
import liveStatusService from '../services/liveStatus'
import { notify } from '../services/errorReporting'
import { useSessionStore } from '../store/useSessionStore'
import { getSessionDeadline } from '../utils/sessionTiming'
import {
  LIVE_POLL_INTERVAL_MS,
  type SessionScreenMode,
  isInPollWindow,
  liveStatusChanged,
  pickSessionSource,
  sessionScreenMode,
  shouldContinuePolling,
} from '../utils/sessionMode'
import type { Session } from '../types'

/** 'not-found': the server refused (4xx) — retrying can't help.
 *  'failed': network/5xx — a retry may. */
export type SessionLoadError = 'not-found' | 'failed'

export interface SessionScreenData {
  session: Session | null
  mode: SessionScreenMode | null
  /** True while a by-id fetch is in flight (render a spinner only when
   *  there's no `session` yet). */
  loading: boolean
  /** Set when the last by-id fetch failed; only meaningful without a
   *  `session` to render. */
  loadError: SessionLoadError | null
  /** Re-run the by-id fetch ("Try again"). */
  reload: () => Promise<void>
  /** Merge a server response (e.g. the retention adjust) into the
   *  fetched copy. */
  applySessionUpdate: (updated: Session) => void
}

function classifyLoadError(err: unknown): SessionLoadError {
  const status = (err as { statusCode?: number } | null)?.statusCode
  // Terminal vs retryable (domain rule): 4xx except 408/429 is a refusal.
  if (status && status >= 400 && status < 500 && status !== 408 && status !== 429) {
    return 'not-found'
  }
  return 'failed'
}

export function useSessionScreen(id: string | undefined): SessionScreenData {
  const activeSession = useSessionStore(state => state.activeSession)
  const loadActiveSession = useSessionStore(state => state.loadActiveSession)

  const [fetchedSession, setFetchedSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<SessionLoadError | null>(null)

  const load = useCallback(async () => {
    if (!id) {
      setLoading(false)
      setLoadError('not-found')
      return
    }
    setLoading(true)
    try {
      const s = await api.getSession(id)
      setFetchedSession(s)
      setLoadError(null)
    } catch (err) {
      notify(err, 'session.load')
      setLoadError(classifyLoadError(err))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const session = pickSessionSource(fetchedSession, activeSession, id)
  const mode = session ? sessionScreenMode(session.status) : null

  // The store holds THIS session, live. When that stops being true (marked
  // safe → store cleared, or ended elsewhere) re-fetch by id so the screen
  // flips to ended mode instead of rendering the stale mount-time copy.
  const storeHoldsLive =
    activeSession != null &&
    activeSession.id === id &&
    sessionScreenMode(activeSession.status) === 'live'
  const prevStoreHoldsLive = useRef(storeHoldsLive)
  useEffect(() => {
    if (prevStoreHoldsLive.current && !storeHoldsLive) void load()
    prevStoreHoldsLive.current = storeHoldsLive
  }, [storeHoldsLive, load])

  // One-time hand-off: a fetched session that turns out to be live but
  // isn't in the store yet (cold deep-link before the store's own load)
  // gets the store to pick it up — gather, tracking, reminders, Live
  // Activity all hang off the store. Once per id; never after the store
  // has held it (so marking safe can't trigger a pointless reload).
  const handedOff = useRef<string | null>(null)
  useEffect(() => {
    if (activeSession?.id && activeSession.id === id) {
      handedOff.current = id
      return
    }
    if (
      !fetchedSession ||
      sessionScreenMode(fetchedSession.status) !== 'live' ||
      handedOff.current === fetchedSession.id
    ) {
      return
    }
    handedOff.current = fetchedSession.id
    loadActiveSession().catch(err => notify(err, 'session.handoff-to-store'))
  }, [fetchedSession, activeSession?.id, id, loadActiveSession])

  // Escalation poll — primitive deps only (see header).
  const sessionId = session?.id ?? null
  const status = session?.status ?? null
  const acknowledged = session?.alert_acknowledged ?? false
  const deadlineMs = session
    ? (getSessionDeadline(session)?.getTime() ?? null)
    : null
  useEffect(() => {
    if (!sessionId || !status || !shouldContinuePolling(status, acknowledged)) {
      return
    }
    let cancelled = false

    const poll = async () => {
      if (cancelled || !isInPollWindow(deadlineMs, Date.now())) return
      try {
        const s = await api.getSession(sessionId)
        if (cancelled) return
        setFetchedSession(s)
        const store = useSessionStore.getState().activeSession
        if (store?.id !== sessionId) return
        if (sessionScreenMode(s.status) === 'live') {
          useSessionStore.setState({ activeSession: s })
          if (liveStatusChanged(store, s)) {
            liveStatusService
              .update(s)
              .catch(err => notify(err, 'session.poll-update-live-status'))
          }
        } else {
          // Ended server-side: the store's own load reconciles everything
          // hanging off it (clears activeSession, stops the Live Activity).
          loadActiveSession().catch(err =>
            notify(err, 'session.poll-reconcile-ended')
          )
        }
      } catch (err) {
        notify(err, 'session.poll-live-status')
      }
    }

    void poll()
    const interval = setInterval(() => void poll(), LIVE_POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [sessionId, status, acknowledged, deadlineMs, loadActiveSession])

  const applySessionUpdate = useCallback((updated: Session) => {
    setFetchedSession(prev => (prev ? { ...prev, ...updated } : updated))
  }, [])

  return {
    session,
    mode,
    loading,
    loadError,
    reload: load,
    applySessionUpdate,
  }
}
