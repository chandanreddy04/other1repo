/**
 * Shared date/time formatting utilities.
 */

export const formatTime = (date: Date | string): string => {
  const d = typeof date === 'string' ? new Date(date) : date
  return d.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  })
}

/**
 * Round a Date to the nearest 30-minute boundary (:00 or :30), zeroing
 * seconds/ms. Ties (:15, :45) round up. Used for the session return-time
 * default so the value is clean and the ±30-min stepper stays on the grid.
 */
export const roundToNearest30Minutes = (date: Date): Date => {
  const d = new Date(date)
  d.setSeconds(0, 0)
  const remainder = d.getMinutes() % 30
  d.setMinutes(d.getMinutes() + (remainder < 15 ? -remainder : 30 - remainder))
  return d
}

export const formatDate = (date: Date | string): string => {
  const d = typeof date === 'string' ? new Date(date) : date
  return d.toLocaleDateString([], {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

export const formatDateTime = (date: Date | string): string => {
  return `${formatDate(date)} at ${formatTime(date)}`
}

/**
 * Human countdown to a deadline (given the remaining milliseconds).
 * Shows seconds only in the final urgent stretch (< 5 min) so the number
 * visibly ticks; otherwise minute/hour granularity. Non-positive → "Overdue".
 */
export const formatCountdown = (remainingMs: number): string => {
  if (remainingMs <= 0) return 'Overdue'
  const totalSeconds = Math.floor(remainingMs / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return `${hours}h ${minutes}m left`
  if (minutes >= 5) return `${minutes}m left`
  return `${minutes}:${String(seconds).padStart(2, '0')} left`
}

/**
 * Compact "how long ago" label ("just now", "12m ago", "1h 5m ago",
 * "2d ago"). Pass `now` when the caller re-renders on a tick so the label
 * ages visibly.
 */
export const formatTimeAgo = (
  date: Date | string,
  now: number = Date.now()
): string => {
  const d = typeof date === 'string' ? new Date(date) : date
  const minutes = Math.floor((now - d.getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ${minutes % 60}m ago`
  return `${Math.floor(hours / 24)}d ago`
}

/** Zero-padded hh:mm:ss for a remaining-time countdown; clamps at 00:00:00. */
export const formatHms = (ms: number): string => {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(totalSeconds / 3600))}:${pad(
    Math.floor((totalSeconds % 3600) / 60)
  )}:${pad(totalSeconds % 60)}`
}
