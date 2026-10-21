/**
 * Offline check-in queue — persists check-in attempts to AsyncStorage
 * when the network is unavailable, and flushes them on reconnect.
 *
 * Errors are classified like the SOS queue (terminal-vs-retryable,
 * .claude/rules): a 4xx means the server refused and retrying can't help —
 * the item is dropped instead of retrying forever. "Already completed" is
 * benign (another path marked safe first); anything else gets a local
 * notification, because the UI already optimistically cleared and the user
 * believes they're marked safe.
 */

import AsyncStorage from '@react-native-async-storage/async-storage'
import * as Notifications from 'expo-notifications'
import api from './api'
import { isTerminalSOSError } from './sosQueue'
import { notify, report } from './errorReporting'

const QUEUE_KEY = '@checkin_queue'

interface QueuedCheckin {
  sessionId: string
  enqueuedAt: string
}

export async function enqueueCheckin(sessionId: string): Promise<void> {
  const raw = await AsyncStorage.getItem(QUEUE_KEY)
  const queue: QueuedCheckin[] = raw ? JSON.parse(raw) : []
  if (queue.some(q => q.sessionId === sessionId)) return
  queue.push({ sessionId, enqueuedAt: new Date().toISOString() })
  await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue))
}

/** The session reached a terminal state by some other path — the queued
 * check-in is moot, drop it without alarming the user. */
async function isSessionAlreadyOver(sessionId: string): Promise<boolean> {
  try {
    const session = await api.getSession(sessionId)
    return session.status === 'completed' || session.status === 'cancelled'
  } catch (err) {
    notify(err, 'checkin-queue.session-status')
    return false
  }
}

async function notifyCheckinFailed(): Promise<void> {
  try {
    await Notifications.scheduleNotificationAsync({
      identifier: 'checkin-failed',
      content: {
        title: "Couldn't confirm you're safe",
        body: 'Please open the app and check your session status.',
        sound: 'default',
      },
      trigger: null,
    })
  } catch (err) {
    notify(err, 'checkin-queue.notify-failure')
    // Best-effort — a notification failure must not break the flush.
  }
}

export async function flushQueue(): Promise<number> {
  const raw = await AsyncStorage.getItem(QUEUE_KEY)
  if (!raw) return 0
  const queue: QueuedCheckin[] = JSON.parse(raw)
  if (queue.length === 0) return 0

  const remaining: QueuedCheckin[] = []
  let flushed = 0

  for (const item of queue) {
    try {
      await api.completeSession(item.sessionId)
      flushed++
    } catch (error) {
      if (isTerminalSOSError(error)) {
        // Server refused — retrying forever can't help. Drop the item; only
        // alarm the user when the session is genuinely still open.
        if (!(await isSessionAlreadyOver(item.sessionId))) {
          // report(), not notify(): a 4xx refusal is exactly the case to see here.
          report(error, 'checkin-queue.terminal-refusal', {
            sessionId: item.sessionId,
          })
          await notifyCheckinFailed()
        }
      } else {
        // Network/5xx — keep it queued for the next flush.
        remaining.push(item)
      }
    }
  }

  if (remaining.length > 0) {
    await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(remaining))
  } else {
    await AsyncStorage.removeItem(QUEUE_KEY)
  }

  return flushed
}

export async function getQueueSize(): Promise<number> {
  const raw = await AsyncStorage.getItem(QUEUE_KEY)
  if (!raw) return 0
  return (JSON.parse(raw) as QueuedCheckin[]).length
}
