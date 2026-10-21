/**
 * Post-session data-retention math for the owner's session summary.
 *
 * Mirrors the backend rules (PUT /sessions/{id}/retention — keep in sync):
 * the purge date moves in ±7d steps, and reductions are floored at the
 * HIGHER of the original deletion date (session end +
 * SESSION_DATA_RETENTION_DAYS) and now — so the owner can only walk back
 * extensions they personally added, never beat the original evidence
 * window, and never schedule deletion in the past (owner decisions
 * 2026-07-19; a hostile phone-holder must not be able to destroy the trail).
 *
 * Related: app/sessions/[id].tsx, app/sessions/index.tsx,
 *          backend app/api/v1/endpoints/sessions.py
 */

import { CHECKIN_CONFIG } from '../constants'

export interface RetentionSessionLike {
  actual_return_time?: string | null
  cancelled_at?: string | null
  purge_after?: string | null
  purged_at?: string | null
}

const DAY_MS = 24 * 60 * 60 * 1000
const RETENTION_MS = CHECKIN_CONFIG.SESSION_DATA_RETENTION_DAYS * DAY_MS

/**
 * When the session ended: the owner's mark-safe time, or the admin-close
 * time for cancelled sessions. Null for legacy terminal rows missing both.
 */
export function getSessionEnd(session: RetentionSessionLike): Date | null {
  const raw = session.actual_return_time || session.cancelled_at
  return raw ? new Date(raw) : null
}

/** The ORIGINAL deletion date — session end + retention, recomputable forever. */
export function getOriginalDeletionDate(
  session: RetentionSessionLike
): Date | null {
  const end = getSessionEnd(session)
  return end ? new Date(end.getTime() + RETENTION_MS) : null
}

/**
 * The reduction floor: the higher of the original deletion date and now.
 * Null when the original date is unrecoverable (legacy rows — extend-only).
 */
export function getRetentionFloor(
  session: RetentionSessionLike,
  now: number = Date.now()
): Date | null {
  const original = getOriginalDeletionDate(session)
  if (!original) return null
  return original.getTime() > now ? original : new Date(now)
}

/** Whether -7d is available: a floor exists and we're strictly above it. */
export function canReduceRetention(
  session: RetentionSessionLike,
  now: number = Date.now()
): boolean {
  if (!session.purge_after) return false
  const floor = getRetentionFloor(session, now)
  if (!floor) return false
  return new Date(session.purge_after).getTime() > floor.getTime()
}

/** Data still exists server-side (not yet purged, purge date in the future). */
export function isDataHeld(
  session: RetentionSessionLike,
  now: number = Date.now()
): boolean {
  if (session.purged_at) return false
  if (!session.purge_after) return false
  return new Date(session.purge_after).getTime() > now
}

/**
 * The deletion date to DISPLAY once data is gone: the actual purge stamp,
 * falling back to session end + retention for rows purged before purged_at
 * existed (owner decision: one formula, no copy branch), then the last
 * known schedule.
 */
export function getDisplayedDeletionDate(
  session: RetentionSessionLike
): Date | null {
  if (session.purged_at) return new Date(session.purged_at)
  return (
    getOriginalDeletionDate(session) ??
    (session.purge_after ? new Date(session.purge_after) : null)
  )
}

/**
 * Compact "Xd Yh" for the deletion countdown ("6d 23h", "5h", "<1h").
 * Clamps at zero — the worker purges within a tick of the deadline.
 */
export function formatDaysHours(ms: number): string {
  if (ms <= 0) return '0h'
  const hoursTotal = Math.floor(ms / (60 * 60 * 1000))
  const days = Math.floor(hoursTotal / 24)
  const hours = hoursTotal % 24
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h`
  return '<1h'
}
