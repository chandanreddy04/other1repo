/**
 * SOS retry queue — persists a pending panic alert to AsyncStorage when
 * delivery fails for a RETRYABLE reason (network outage, server fault) and
 * keeps retrying it without user action:
 *   - a foreground interval while the app is alive,
 *   - an AppState listener (retry the moment the app returns to foreground),
 *   - an OS-scheduled background task (expo-background-task) so a locked
 *     phone that regains signal still delivers without the app being opened.
 *
 * TERMINAL failures (4xx: the server understood and refused — e.g. no active
 * circle members) are never queued or retried: retrying can't change the
 * outcome, and a permanently-retrying queue shows the user a false "we're
 * reaching your circle" state. Callers must surface an honest failure
 * instead (see app/(tabs)/index.tsx SOS handling).
 *
 * Related: store/useSessionStore.ts (sendSOS/flushSOSQueue),
 * services/api.ts (sendSOS retries network errors synchronously first),
 * docs/flow-review.md §4.2 (A3) / Tier-0 finding A1.
 */

import AsyncStorage from '@react-native-async-storage/async-storage'
import { AppState } from 'react-native'
import * as Notifications from 'expo-notifications'
import type { Session } from '../types'
import api, { type ApiError } from './api'
import { notify, report } from './errorReporting'
import { loadNativeModule } from './nativeModules'

const KEY = '@sos_pending'
const PENDING_NOTIFICATION_ID = 'sos-pending'
const RETRY_INTERVAL_MS = 30_000
export const SOS_RETRY_TASK = 'sos-background-retry'

// Lazy-loaded so a build missing the native module degrades to the
// foreground retry paths (and alerts Bugsnag once) instead of crashing.
const TaskManager = loadNativeModule<typeof import('expo-task-manager')>(
  'expo-task-manager',
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  () => require('expo-task-manager')
)
const BackgroundTask = loadNativeModule<typeof import('expo-background-task')>(
  'expo-background-task',
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  () => require('expo-background-task')
)

/**
 * A terminal SOS error is one where retrying cannot help: the request
 * reached the server and was refused (4xx), e.g. "no active contacts in
 * your circle". Network-level failures (no statusCode), timeouts (408),
 * rate limits (429), and server faults (5xx) are retryable.
 */
export function isTerminalSOSError(error: unknown): boolean {
  const status = (error as ApiError | undefined)?.statusCode
  if (status === undefined) return false
  if (status === 408 || status === 429) return false
  // 401/403 is an AUTH problem, not a refusal — `api.request` retries once
  // after a token refresh, but if the refresh token is also expired the 401
  // propagates. Re-login makes the SOS deliverable, so it must NOT be terminal.
  if (status === 401 || status === 403) return false
  if (status >= 500) return false
  return status >= 400
}

/** An SOS failure that only re-authentication can clear (see isTerminalSOSError). */
export function isAuthSOSError(error: unknown): boolean {
  const status = (error as ApiError | undefined)?.statusCode
  return status === 401 || status === 403
}

interface PendingSOS {
  queuedAt: string
  /** True once the "sign in to finish your SOS" nudge has been shown. */
  authNudged?: boolean
}

/** Read the queued SOS, tolerating the legacy bare-ISO-string format. */
async function readPending(): Promise<PendingSOS | null> {
  const raw = await AsyncStorage.getItem(KEY)
  if (raw === null) return null
  try {
    const parsed = JSON.parse(raw)
    if (
      parsed &&
      typeof parsed === 'object' &&
      typeof parsed.queuedAt === 'string'
    ) {
      return { queuedAt: parsed.queuedAt, authNudged: !!parsed.authNudged }
    }
  } catch {
    // benign: Legacy value: a bare ISO timestamp string.
  }
  return { queuedAt: raw, authNudged: false }
}

async function writePending(pending: PendingSOS): Promise<void> {
  await AsyncStorage.setItem(KEY, JSON.stringify(pending))
}

export async function hasPendingSOS(): Promise<boolean> {
  return (await AsyncStorage.getItem(KEY)) !== null
}

export async function clearPendingSOS(): Promise<void> {
  await AsyncStorage.removeItem(KEY)
  stopSOSRetry()
  await dismissPendingNotification()
  await unregisterBackgroundRetry()
}

/**
 * Queue a failed (retryable) SOS and arm every retry path. Also posts a
 * local notification so the user knows the alert has NOT reached their
 * circle yet — the alarm UI alone must never imply delivery.
 */
export async function enqueueSOS(): Promise<void> {
  await writePending({ queuedAt: new Date().toISOString(), authNudged: false })
  ensureSOSRetryScheduled()
  // Notification + background registration are best-effort: their failure
  // must never break the durable queueing itself.
  try {
    await Notifications.scheduleNotificationAsync({
      identifier: PENDING_NOTIFICATION_ID,
      content: {
        title: 'SOS not sent yet',
        body:
          "No connection — we'll keep retrying in the background. " +
          'If this is an emergency, call 911 now.',
        sound: 'default',
      },
      trigger: null,
    })
  } catch (err) {
    notify(
      err instanceof Error ? err : new Error(String(err)),
      'failed to post SOS-pending notification'
    )
  }
  await registerBackgroundRetry()
}

// ---------------------------------------------------------------------------
// Retry paths
// ---------------------------------------------------------------------------

// The runner is swapped by useSessionStore for a store-aware flush so a
// successful background/interval retry also updates in-app session state.
let flushRunner: () => Promise<unknown> = () => flushSOSQueue()
let retryTimer: ReturnType<typeof setInterval> | null = null
let appStateSub: { remove: () => void } | null = null

/**
 * Arm the foreground retry paths (interval + on-foreground). Idempotent —
 * safe to call from enqueue and from app start when a queued SOS exists.
 */
export function ensureSOSRetryScheduled(runner?: () => Promise<unknown>): void {
  if (runner) flushRunner = runner
  if (!retryTimer) {
    retryTimer = setInterval(() => {
      void flushRunner()
    }, RETRY_INTERVAL_MS)
  }
  if (!appStateSub) {
    appStateSub = AppState.addEventListener('change', state => {
      if (state === 'active') void flushRunner()
    })
  }
}

function stopSOSRetry(): void {
  if (retryTimer) {
    clearInterval(retryTimer)
    retryTimer = null
  }
  if (appStateSub) {
    appStateSub.remove()
    appStateSub = null
  }
}

async function dismissPendingNotification(): Promise<void> {
  try {
    await Notifications.dismissNotificationAsync(PENDING_NOTIFICATION_ID)
  } catch {
    // benign: Notification may already be gone — nothing to clean up.
  }
}

async function registerBackgroundRetry(): Promise<void> {
  if (!BackgroundTask) return
  try {
    await BackgroundTask.registerTaskAsync(SOS_RETRY_TASK, {
      minimumInterval: 15, // minutes — OS-scheduled floor
    })
  } catch (err) {
    notify(
      err instanceof Error ? err : new Error(String(err)),
      'failed to register SOS background retry task'
    )
  }
}

async function unregisterBackgroundRetry(): Promise<void> {
  if (!BackgroundTask) return
  try {
    await BackgroundTask.unregisterTaskAsync(SOS_RETRY_TASK)
  } catch {
    // benign: Not registered — nothing to clean up.
  }
}

// Task body must be defined at module scope so it exists when the OS wakes
// the app headlessly. sosQueue is imported via the session store on every
// launch, so this runs before any background invocation.
TaskManager?.defineTask(SOS_RETRY_TASK, async () => {
  const session = await flushSOSQueue()
  return session
    ? BackgroundTask?.BackgroundTaskResult.Success
    : BackgroundTask?.BackgroundTaskResult.Failed
})

// ---------------------------------------------------------------------------
// Flush
// ---------------------------------------------------------------------------

/**
 * Retry a queued SOS. Returns the created session on success (clearing the
 * queue and every retry path). A retryable failure stays queued for the
 * next trigger. A TERMINAL failure clears the queue and tells the user
 * honestly — a queue that can never succeed must not keep the "reaching
 * your circle" state alive.
 */
export async function flushSOSQueue(): Promise<Session | null> {
  if (!(await hasPendingSOS())) {
    stopSOSRetry()
    return null
  }
  try {
    const session = await api.sendSOS()
    await clearPendingSOS()
    return session
  } catch (error) {
    if (isTerminalSOSError(error)) {
      await clearPendingSOS()
      // report(), not notify(): a 4xx refusal is exactly the case to see here.
      report(
        error instanceof Error ? error : new Error(String(error)),
        'queued SOS failed terminally — user notified to call 911'
      )
      try {
        await Notifications.scheduleNotificationAsync({
          content: {
            title: 'SOS could not be sent',
            body:
              'We could not alert your Circle' +
              (error instanceof Error && error.message
                ? ` (${error.message})`
                : '') +
              '. If this is an emergency, call 911 now.',
            sound: 'default',
          },
          trigger: null,
        })
      } catch {
        // benign: Best-effort — the Bugsnag report above still records the failure.
      }
    } else if (isAuthSOSError(error)) {
      // Retryable (stays queued), but retries can't succeed until re-login.
      // Nudge the user ONCE to sign in; a later login re-runs flushSOSQueue.
      const pending = await readPending()
      if (pending && !pending.authNudged) {
        await writePending({ ...pending, authNudged: true })
        try {
          await Notifications.scheduleNotificationAsync({
            identifier: PENDING_NOTIFICATION_ID,
            content: {
              title: 'Finish sending your SOS',
              body:
                'Please sign in to finish alerting your Circle. ' +
                'If this is an emergency, call 911 now.',
              sound: 'default',
            },
            trigger: null,
          })
        } catch {
          // benign: Best-effort — the queue still retries on the next trigger/login.
        }
      }
    }
    return null
  }
}
