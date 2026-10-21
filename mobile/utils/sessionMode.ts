/**
 * Pure helpers for the merged session screen (`app/sessions/[id].tsx`, via
 * `hooks/useSessionScreen.ts`): which MODE a status renders in, which copy
 * of the session (fetched-by-id vs the store's activeSession) is the source
 * of truth, and when the live escalation poll runs. The live session and
 * the past session are the SAME resource in different states (owner
 * decision, Commit 12) — this is the one place that decides which state a
 * status is.
 *
 * 'live': the session is still running or actively escalating — the screen
 * renders the countdown/overdue chrome (formerly a dedicated live-check-in
 * screen).
 * 'ended': the session reached a terminal state — the screen renders the
 * outcome + retention chrome (formerly a dedicated past-session screen).
 *
 * Purge/"data held" is a SEPARATE axis from mode (an ended session can still
 * hold its data) — that stays with `utils/retention.ts` (`isDataHeld`),
 * which callers combine with the mode here.
 *
 * Related: app/sessions/[id].tsx, hooks/useSessionScreen.ts,
 *          utils/retention.ts.
 */
import type { Session } from '../types'

export type SessionScreenMode = 'live' | 'ended'

const LIVE_STATUSES: ReadonlySet<Session['status']> = new Set([
  'active',
  'missed',
  'alerted',
])

/** 'live' for active/missed/alerted, 'ended' for completed/cancelled. */
export function sessionScreenMode(
  status: Session['status']
): SessionScreenMode {
  return LIVE_STATUSES.has(status) ? 'live' : 'ended'
}

/**
 * Which copy of session `id` the screen renders:
 *   1. a fetched copy that is ENDED wins — terminal states are final, so a
 *      still-live store copy is merely stale;
 *   2. otherwise the store's activeSession when it IS this session and is
 *      live (it's what Home and the Live Activity render — the screen must
 *      not disagree with them);
 *   3. otherwise the fetched copy, falling back to a matching store copy
 *      (e.g. the by-id fetch failed offline).
 * A store session for a different id never leaks in.
 */
export function pickSessionSource(
  fetched: Session | null,
  active: Session | null,
  id: string | undefined
): Session | null {
  const fetchedMatch = fetched && fetched.id === id ? fetched : null
  const activeMatch = active && active.id === id ? active : null
  if (fetchedMatch && sessionScreenMode(fetchedMatch.status) === 'ended') {
    return fetchedMatch
  }
  if (activeMatch && sessionScreenMode(activeMatch.status) === 'live') {
    return activeMatch
  }
  return fetchedMatch ?? activeMatch
}

/** The escalation poll only starts inside the final 2 minutes. */
export const LIVE_POLL_LEAD_MS = 2 * 60 * 1000
/** Poll cadence once inside the window. */
export const LIVE_POLL_INTERVAL_MS = 20_000

/**
 * Whether the live escalation poll still has something to learn:
 * ACTIVE (grace) → MISSED (dispatching) → ALERTED (delivered) →
 * acknowledged. Stops at alerted+acknowledged and once the session ended.
 */
export function shouldContinuePolling(
  status: Session['status'],
  acknowledged: boolean
): boolean {
  if (sessionScreenMode(status) !== 'live') return false
  return !(status === 'alerted' && acknowledged)
}

/** Inside the poll window: no deadline → never; else from T-2min on. */
export function isInPollWindow(deadlineMs: number | null, now: number): boolean {
  if (deadlineMs == null) return false
  return now >= deadlineMs - LIVE_POLL_LEAD_MS
}

/**
 * Did anything the lock-screen Live Activity renders change? Only then is
 * a `liveStatusService.update` worth making.
 */
export function liveStatusChanged(prev: Session, next: Session): boolean {
  return (
    prev.status !== next.status ||
    (prev.alert_acknowledged ?? false) !== (next.alert_acknowledged ?? false) ||
    (prev.circle_unreachable ?? false) !== (next.circle_unreachable ?? false)
  )
}
