import { create } from 'zustand'
import { Session } from '../types'
import api from '../services/api'
import { enqueueCheckin, flushQueue } from '../services/checkinQueue'
import {
  enqueueSOS,
  ensureSOSRetryScheduled,
  flushSOSQueue,
  hasPendingSOS,
  isTerminalSOSError,
} from '../services/sosQueue'
import notificationService from '../services/notifications'
import locationTracking from '../services/locationTracking'
import liveStatusService from '../services/liveStatus'
import sessionGather from '../services/sessionGather'
import { getSessionDeadline } from '../utils/sessionTiming'
import { isNetworkFailure } from '../services/apiReporting'
import { notify } from '../services/errorReporting'

interface SessionState {
  activeSession: Session | null
  sessions: Session[]
  isLoading: boolean
  error: string | null

  loadActiveSession: () => Promise<void>
  loadSessions: () => Promise<void>
  createSession: (data: {
    expected_return_time: string
    destination?: string
    location_sharing_enabled?: boolean
  }) => Promise<Session>
  sendSOS: () => Promise<Session>
  completeSession: (sessionId?: string) => Promise<void>
  extendSession: (
    additionalMinutes: number,
    sessionId?: string
  ) => Promise<void>
  updateLocation: (
    latitude: string,
    longitude: string,
    sessionId?: string
  ) => Promise<void>
  fetchActiveSession: () => Promise<void>
  flushCheckinQueue: () => Promise<void>
  flushSOSQueue: () => Promise<void>
}

export const useSessionStore = create<SessionState>((set, get) => ({
  activeSession: null,
  sessions: [],
  isLoading: false,
  error: null,

  loadActiveSession: async () => {
    set({ isLoading: true, error: null })
    try {
      const session = await api.getActiveSession()
      set({ activeSession: session, isLoading: false })

      // Reconcile live status from the source of truth. Crucially this also
      // STOPS a stale Live Activity / ongoing notification when there's no
      // active session (e.g. it ended while the app was closed) — the old
      // start-only path never cleared those, leaving the card up after safe.
      liveStatusService
        .reconcile(session)
        .catch(err => notify(err, 'session.reconcile-live-status'))

      if (session) {
        // Opportunistic gather (battery always; location self-gates on the
        // session toggle + live permission). Safe to (re)start on reload.
        void sessionGather.start({
          sessionId: session.id,
          locationSharing: session.location_sharing_enabled,
        })

        // Self-heal the local reminder ladder — reminders are client-owned
        // (OS-scheduled), and a reinstall/data-clear wipes them. Cancel +
        // reschedule is idempotent; past rungs are skipped automatically.
        if (session.status === 'active') {
          const deadline = getSessionDeadline(session)
          if (deadline) {
            notificationService
              .cancelCheckInReminder(session.id)
              .then(() =>
                notificationService.scheduleCheckInReminder(
                  deadline,
                  session.id
                )
              )
              .catch(err => notify(err, 'session.reschedule-reminders'))
          }
        }

        if (session.location_sharing_enabled) {
          const isTracking = await locationTracking.isTracking()
          if (!isTracking) {
            const escalated =
              session.status === 'missed' || session.status === 'alerted'
            locationTracking
              .startTracking(session.id)
              .then(async started => {
                if (started && escalated) {
                  await locationTracking.escalateTracking()
                }
              })
              .catch(err => notify(err, 'session.restart-location-tracking'))
          }
        }
      }
    } catch (error) {
      // Check if it's a profile incomplete error
      const apiErr = error as { statusCode?: number; requiresProfile?: boolean }
      if (apiErr.statusCode === 428 || apiErr.requiresProfile) {
        // Don't set as error, let the UI handle navigation
        set({ isLoading: false })
        throw error // Re-throw to let UI handle
      }
      const message =
        error instanceof Error ? error.message : 'Failed to load session'
      set({ error: message, isLoading: false })
    }
  },

  loadSessions: async () => {
    set({ isLoading: true, error: null })
    try {
      const sessions = await api.getSessions()
      set({ sessions, isLoading: false })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to load sessions'
      set({ error: message, isLoading: false })
    }
  },

  createSession: async data => {
    set({ isLoading: true, error: null })
    try {
      const session = await api.createSession(data)
      set({ activeSession: session, isLoading: false })

      // Schedule local reminder notification
      const expectedTime = getSessionDeadline(session)
      if (expectedTime) {
        await notificationService.scheduleCheckInReminder(
          expectedTime,
          session.id
        )
      }

      void sessionGather.start({
        sessionId: session.id,
        locationSharing: session.location_sharing_enabled,
      })

      if (session.location_sharing_enabled) {
        locationTracking
          .startTracking(session.id)
          .catch(err => notify(err, 'session.start-location-tracking'))
      }

      // Start live status (iOS Live Activity / Android ongoing notification)
      liveStatusService
        .start(session)
        .catch(err => notify(err, 'session.start-live-status'))

      // Reload sessions list
      get().loadSessions()

      return session
    } catch (error) {
      // Re-throw 402 so UI can navigate to paywall
      const apiErr = error as {
        statusCode?: number
        requiresSubscription?: boolean
      }
      if (apiErr.statusCode === 402 || apiErr.requiresSubscription) {
        set({ isLoading: false })
        throw error
      }
      const message =
        error instanceof Error ? error.message : 'Failed to create session'
      set({ error: message, isLoading: false })
      throw error
    }
  },

  sendSOS: async () => {
    set({ isLoading: true, error: null })
    // A live check-in escalates into this SOS server-side (same session,
    // accelerated deadline) — either way its scheduled reminder ladder is
    // stale the moment the SOS lands. Capture the id BEFORE state changes;
    // cancel only on success (if the SOS queues, the check-in — and its
    // reminders — are still live).
    const priorSessionId = get().activeSession?.id
    // Grab a fast last-known location snapshot so the first alert already has a
    // map pin. Never let this block or fail the SOS button — null is fine.
    const snapshot = await locationTracking
      .getSosSnapshot()
      .catch(
        () =>
          /* benign: never block the SOS button — no snapshot is fine */ null
      )
    try {
      const session = await api.sendSOS(snapshot ?? undefined)
      set({ activeSession: session, isLoading: false })
      if (priorSessionId) {
        notificationService
          .cancelCheckInReminder(priorSessionId)
          .catch(err => notify(err, 'session.cancel-stale-reminders'))
      }
      // Opportunistic gather (battery always; location self-gates on the
      // session toggle + live permission).
      void sessionGather.start({
        sessionId: session.id,
        locationSharing: session.location_sharing_enabled,
      })
      // Permission was granted (we got a fix) — keep the pin live for the
      // circle as the person moves. Don't prompt post-SOS if it wasn't.
      if (snapshot) {
        locationTracking
          .startTracking(session.id)
          .catch(err => notify(err, 'session.start-sos-tracking'))
      }
      get().loadSessions()
      return session
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to send SOS'
      set({ error: message, isLoading: false })
      // TERMINAL (4xx — server refused, e.g. no active circle): do NOT
      // queue. Retrying can't help, and a forever-retrying queue shows a
      // false "reaching your circle" alarm. The UI must fail honestly.
      if (isTerminalSOSError(error)) {
        throw error
      }
      // RETRYABLE (network/5xx — api.sendSOS already retried briefly):
      // persist and arm every retry path (interval, on-foreground,
      // OS background task) so the user never has to re-press. The
      // store-aware runner keeps activeSession in sync when a retry lands.
      await enqueueSOS()
      ensureSOSRetryScheduled(() => get().flushSOSQueue())
      throw error
    }
  },

  flushSOSQueue: async () => {
    const session = await flushSOSQueue()
    if (session) {
      set({ activeSession: session })
      get().loadSessions()
    } else if (await hasPendingSOS()) {
      // Still queued after a retryable failure (e.g. app relaunched while
      // offline) — re-arm the retry paths with the store-aware runner so a
      // later success also updates in-app state.
      ensureSOSRetryScheduled(() => get().flushSOSQueue())
    }
  },

  completeSession: async (sessionId?: string) => {
    const id = sessionId || get().activeSession?.id
    if (!id) return
    // The session screen can complete ANY live session by id (e.g. a
    // lingering MISSED one while a fresh SOS is the store's session). Local
    // live state — tracking, gather, the Live Activity — belongs to the
    // store's session, so it's torn down only when that's the one completed.
    const isStoreSession = id === get().activeSession?.id
    const clearLocalLiveState = async () => {
      if (isStoreSession) {
        set({ activeSession: null })
        await locationTracking.stopTracking()
        await sessionGather.stop()
        await liveStatusService.stop()
      }
      await notificationService.cancelCheckInReminder(id)
    }

    set({ isLoading: true, error: null })
    try {
      await api.completeSession(id)
      set({ isLoading: false })
      await clearLocalLiveState()

      get().loadSessions()
    } catch (error) {
      const msg = error instanceof Error ? error.message : ''
      // Queue + clear locally ONLY when our server never answered (offline,
      // gateway page). A 5xx that answered is a refusal — keep the session.
      if (!isNetworkFailure(error)) {
        // The server rejected the request — do NOT optimistically mark safe.
        // Claiming "safe" here would leave the circle's outstanding alerts
        // unresolved while the user believes they checked in.
        set({ error: msg || 'Failed to mark safe', isLoading: false })
        throw error
      }
      // Offline: queue for retry and optimistically clear locally.
      await enqueueCheckin(id)
      set({ isLoading: false })
      await clearLocalLiveState()
    }
  },

  extendSession: async (additionalMinutes: number, sessionId?: string) => {
    const id = sessionId || get().activeSession?.id
    if (!id) return

    set({ isLoading: true, error: null })
    try {
      const updatedSession = await api.extendSession(id, additionalMinutes)
      set({ activeSession: updatedSession, isLoading: false })

      // Reschedule notifications
      await notificationService.cancelCheckInReminder(updatedSession.id)
      const newExpectedTime = getSessionDeadline(updatedSession)
      if (newExpectedTime) {
        await notificationService.scheduleCheckInReminder(
          newExpectedTime,
          updatedSession.id
        )
      }

      // Update live status with new expected time
      liveStatusService
        .update(updatedSession)
        .catch(err => notify(err, 'session.update-live-status'))
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to extend session'
      set({ error: message, isLoading: false })
      throw error
    }
  },

  updateLocation: async (
    latitude: string,
    longitude: string,
    sessionId?: string
  ) => {
    const id = sessionId || get().activeSession?.id
    if (!id) return

    try {
      await api.updateLocation(id, latitude, longitude)
    } catch (error) {
      notify(error, 'session.update-location')
    }
  },

  fetchActiveSession: async () => {
    await get().loadActiveSession()
  },

  flushCheckinQueue: async () => {
    const flushed = await flushQueue()
    if (flushed > 0) {
      get().loadSessions()
    }
  },
}))
