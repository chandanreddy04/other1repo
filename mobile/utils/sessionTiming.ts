/**
 * Canonical resolver for a session's deadline timestamp.
 *
 * A session exposes its deadline under several historical field names
 * (`expected_arrival_time` is an alias for `expected_return_time`;
 * `expected_end_time` is a backend-compat fallback). Resolving that fallback
 * inline at each call site let the ordering drift — the home screen preferred
 * `expected_arrival_time`, other screens preferred `expected_return_time`.
 * Resolve it in ONE place so callers never hand-roll the chain again.
 *
 * Related: utils/dateFormatting.ts (formatCountdown), services/liveStatus.ts.
 */
import { CHECKIN_CONFIG } from '../constants/config'

export interface SessionLike {
  expected_arrival_time?: string | null
  expected_return_time?: string | null
  expected_end_time?: string | null
}

/** The session's deadline as a Date, or null when no timestamp is present. */
export const getSessionDeadline = (session: SessionLike): Date | null => {
  const raw =
    session.expected_arrival_time ||
    session.expected_return_time ||
    session.expected_end_time
  return raw ? new Date(raw) : null
}

/**
 * The owner reminder ladder, minutes before the deadline. ALL reminder pushes
 * are client-scheduled local notifications (owner decision 2026-07-18) — the
 * device's own clock fires them in dead zones and backend outages, which
 * server pushes can't reach. The server's only reminder duty is the
 * at-deadline SMS. Cadence: the old backend ladder (30/10/0) plus the
 * historical local T-5 backstop.
 */
export const REMINDER_LADDER_MINUTES = [30, 10, 5, 0] as const

export interface ReminderRung {
  minutesBefore: number
  fireAt: Date
}

/**
 * The reminder rungs still strictly in the future for a deadline — a short
 * session simply gets fewer rungs. Past-dated DATE triggers are never
 * returned (the OS either fires them immediately or silently drops them).
 */
/**
 * Alarm-app semantics for a directly-picked clock time: the NEXT occurrence
 * of hh:mm — today if still ahead, otherwise tomorrow (picking "1:00 AM" at
 * 11 PM means tonight's small hours). Always lands within 24h, matching the
 * session-length cap.
 */
export const nextOccurrenceOfTime = (
  hours: number,
  minutes: number,
  now: Date = new Date(),
  // Occurrences closer than this roll to the next day — a deadline can
  // never be set inside the minimum session length.
  minLeadMinutes = 0
): Date => {
  const threshold = now.getTime() + minLeadMinutes * 60_000
  const next = new Date(now)
  next.setHours(hours, minutes, 0, 0)
  if (next.getTime() <= threshold) {
    next.setDate(next.getDate() + 1)
  }
  return next
}

/**
 * True when a location fix is too old to honestly present as "live" — the
 * trail dot renders static gray instead of pulsing blue. Measured against the
 * SERVER-stored fix (what the circle actually sees), never device GPS.
 */
export const isLocationStale = (
  recordedAt: string | Date,
  now: number = Date.now()
): boolean => {
  const recorded =
    typeof recordedAt === 'string' ? new Date(recordedAt) : recordedAt
  return now - recorded.getTime() > CHECKIN_CONFIG.LOCATION_STALE_THRESHOLD_MS
}

export const computeReminderRungs = (
  deadline: Date,
  now: Date = new Date()
): ReminderRung[] =>
  REMINDER_LADDER_MINUTES.map(minutesBefore => ({
    minutesBefore,
    fireAt: new Date(deadline.getTime() - minutesBefore * 60_000),
  })).filter(({ fireAt }) => fireAt.getTime() > now.getTime())
