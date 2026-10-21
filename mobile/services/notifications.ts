import * as Notifications from 'expo-notifications'
import * as Device from 'expo-device'
import Constants from 'expo-constants'
import { Platform, AppState, type NativeEventSubscription } from 'react-native'
import AsyncStorage from '@react-native-async-storage/async-storage'
import { router, type Href } from 'expo-router'
import { CHECKIN_CONFIG, STORAGE_KEYS } from '../constants'
import api from './api'
import locationTracking from './locationTracking'
import liveStatusService from './liveStatus'
import { routeForNotificationType } from './notificationRouting'
import {
  computeReminderRungs,
  getSessionDeadline,
  REMINDER_LADDER_MINUTES,
} from '../utils/sessionTiming'
import { notify } from './errorReporting'

// Action identifier for the one-tap extend button on session reminders.
const EXTEND_ACTION_ID = 'extend-30'

// Deterministic per-session+rung id so the ladder can be cancelled/rescheduled
// without touching other scheduled notifications.
const checkInReminderId = (sessionId: string, minutesBefore: number) =>
  `checkin-reminder-${sessionId}-${minutesBefore}`
// Pre-ladder id format — sessions scheduled before the client-side ladder
// shipped still carry one of these; cancel must clear them too.
const legacyCheckInReminderId = (sessionId: string) =>
  `checkin-reminder-${sessionId}`

// Owner reminder copy. The at-deadline pair (SESSION_DEADLINE_*) MUST mirror
// backend notification_constants.py (SESSION_DEADLINE_TITLE/_BODY) — that
// pair is ALSO sent server-side as the T-0 SMS, so both channels speak in one
// voice. The pre-deadline copy (session_expiring, below) has no server
// equivalent any more — the backend SESSION_EXPIRING_* constants were
// deleted 2026-09-27 (nothing ever sent them; the client ladder always
// covered those rungs) — this IS the source now, not a mirror. All reminder
// PUSHES are client-scheduled (owner decision 2026-07-18 — they fire in dead
// zones and backend outages); the server sends only the at-deadline SMS.
//
// {time} is the DEADLINE (check-in-by) in the device's own timezone, "h:mm a"
// ("9:40 PM", no leading zero) — the same Intl options as the Live Activity's
// return clock (liveStatus.ts formatReturnClock). Not utils formatTime: that
// one pads the hour ("09:40 PM").
const formatReminderClock = (d: Date) =>
  d.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
const sessionExpiringTitle = (checkInTime: Date) =>
  `⏰ Check in by ${formatReminderClock(checkInTime)}`
const sessionExpiringBody = (minutes: number) =>
  `Your session ends in ${minutes} min. Extend it or check in.`
const SESSION_DEADLINE_TITLE = "⏰ Time's up"
const SESSION_DEADLINE_BODY =
  'Check in now, or your Circle will be alerted in about ' +
  `${CHECKIN_CONFIG.ALERT_GRACE_MINUTES} minutes.`

// Configure how notifications should be presented when app is in foreground
/**
 * Fire-time liveness check for locally scheduled session reminders: suppress
 * one only when the store can PROVE it's stale — the session it points at is
 * gone/shadowed (SOS overwrote it), no longer active, or its deadline moved
 * (>2 min drift from the rung's expected fire time). Fail-open everywhere
 * else: over-notifying beats silently dropping a safety reminder (e.g. a
 * cold start where the store hasn't loaded yet). Foreground-only by nature —
 * the OS presents directly when the app isn't running, which cancellation
 * hygiene (complete/extend/SOS) covers.
 */
export function isStaleReminderPresentation(
  data: Record<string, unknown> | undefined
): boolean {
  if (data?.type !== 'session_reminder') return false
  const sessionId = data?.sessionId as string | undefined
  const minutesRemaining = data?.minutes_remaining as number | undefined
  if (!sessionId) return false
  try {
    // Lazy require — avoids the module cycle (the store imports this service).
    const { useSessionStore } =
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      require('../store/useSessionStore') as typeof import('../store/useSessionStore')
    const active = useSessionStore.getState().activeSession
    if (!active) return false // can't prove anything — show it
    if (active.id !== sessionId) return true // shadowed by another session
    if (active.status !== 'active') return true // already escalated/ended
    if (minutesRemaining != null) {
      const deadline = getSessionDeadline(active)
      if (deadline) {
        const expectedFire = deadline.getTime() - minutesRemaining * 60_000
        if (Math.abs(Date.now() - expectedFire) > 2 * 60_000) {
          return true // deadline moved since this rung was scheduled
        }
      }
    }
    return false
  } catch {
    // benign: fail-open — an unreadable store means the reminder shows
    return false
  }
}

Notifications.setNotificationHandler({
  handleNotification: async notification => {
    const stale = isStaleReminderPresentation(
      notification.request.content.data as Record<string, unknown> | undefined
    )
    return {
      shouldShowAlert: !stale,
      shouldPlaySound: !stale,
      shouldSetBadge: !stale,
      shouldShowBanner: !stale,
      shouldShowList: !stale,
    }
  },
})

class NotificationService {
  private static instance: NotificationService
  private notificationListener: Notifications.EventSubscription | null = null
  private responseListener: Notifications.EventSubscription | null = null
  private pushTokenListener: Notifications.EventSubscription | null = null
  private appStateListener: NativeEventSubscription | null = null

  private constructor() {}

  static getInstance(): NotificationService {
    if (!NotificationService.instance) {
      NotificationService.instance = new NotificationService()
    }
    return NotificationService.instance
  }

  async initialize() {
    // Register for push notifications + persist the token to the backend.
    await this.registerAndSaveToken()

    // Session-reminder pushes (backend category "session_expiring" and the
    // local pre-deadline reminder) carry a one-tap "Extend 30 min" action —
    // extending from the notification itself, without opening the app, is
    // the fastest running-late path (flow-review §4.3 C2).
    try {
      await Notifications.setNotificationCategoryAsync('session_expiring', [
        {
          identifier: EXTEND_ACTION_ID,
          buttonTitle: 'Extend 30 min',
          options: { opensAppToForeground: false },
        },
      ])
    } catch (err) {
      notify(err, 'notifications.register-category')
    }

    // Set up notification listeners
    this.setupNotificationListeners()
  }

  async registerForPushNotificationsAsync(): Promise<string | null> {
    if (!Device.isDevice) {
      // eslint-disable-next-line no-console
      console.log('Must use physical device for Push Notifications')
      return null
    }

    try {
      // Check-only — NEVER request here. initialize() calls this at startup, so
      // a request would be a cold prompt. The grant comes from a guided flow
      // (onboarding / the permission panel) via services/permissions.ts; this
      // just picks up the token once permission already exists.
      const { status } = await Notifications.getPermissionsAsync()
      if (status !== 'granted') {
        // eslint-disable-next-line no-console
        console.log('Notifications not granted yet — skipping push token')
        return null
      }

      // Get Expo push token. Pass projectId explicitly — implicit
      // resolution is flaky in dev builds and fails outright when the
      // runtime config drifts from the EAS project.
      const projectId: string | undefined =
        Constants.expoConfig?.extra?.eas?.projectId
      const tokenData = await Notifications.getExpoPushTokenAsync(
        projectId ? { projectId } : undefined
      )

      const token = tokenData.data

      // Save token locally
      await AsyncStorage.setItem(STORAGE_KEYS.EXPO_PUSH_TOKEN, token)

      // Configure Android-specific settings
      if (Platform.OS === 'android') {
        await Notifications.setNotificationChannelAsync('default', {
          name: 'default',
          importance: Notifications.AndroidImportance.MAX,
          vibrationPattern: [0, 250, 250, 250],
          lightColor: '#FF231F7C',
        })
      }

      return token
    } catch (error) {
      notify(error, 'notifications.register-push-token')
      return null
    }
  }

  async saveTokenToBackend(token: string) {
    try {
      // Update user profile with push token
      await api.updateUser({ expo_push_token: token })
    } catch (error) {
      notify(error, 'notifications.save-push-token')
    }
  }

  /**
   * Register for push AND persist the token to the backend — the single "close
   * the loop after a grant" entry point. Registration alone only writes the
   * token to AsyncStorage; the backend save happens ONLY here and in
   * initialize(). Onboarding, the inline permission panel, and app-foreground
   * all call this so a freshly-granted permission reaches the backend
   * immediately, not just on the next cold start. Check-only registration means
   * it's a safe no-op until permission actually exists.
   */
  async registerAndSaveToken(): Promise<string | null> {
    const token = await this.registerForPushNotificationsAsync()
    if (token) {
      await this.saveTokenToBackend(token)
    }
    return token
  }

  setupNotificationListeners() {
    // Handle notifications received while app is foregrounded
    this.notificationListener = Notifications.addNotificationReceivedListener(
      notification => {
        // eslint-disable-next-line no-console
        console.log('Notification received:', notification)
        this.handleNotification(notification)
      }
    )

    // Handle user tapping on notification
    this.responseListener =
      Notifications.addNotificationResponseReceivedListener(response => {
        // eslint-disable-next-line no-console
        console.log('Notification response:', response)
        this.handleNotificationResponse(response)
      })

    // Re-register when Expo rotates the push token — otherwise alerts to this
    // device silently stop once the stored token goes stale. (H5)
    this.pushTokenListener = Notifications.addPushTokenListener(tokenData => {
      const token = tokenData.data
      AsyncStorage.setItem(STORAGE_KEYS.EXPO_PUSH_TOKEN, token).catch(err =>
        notify(err, 'notifications.persist-rotated-token')
      )
      this.saveTokenToBackend(token).catch(err =>
        notify(err, 'notifications.save-rotated-token')
      )
    })

    // If notifications get granted in OS Settings while the app is backgrounded,
    // there's no token yet — register+save on the next foreground so server
    // pushes start arriving without waiting for a relaunch.
    this.appStateListener = AppState.addEventListener('change', state => {
      if (state !== 'active') return
      void (async () => {
        const stored = await AsyncStorage.getItem(STORAGE_KEYS.EXPO_PUSH_TOKEN)
        if (!stored) await this.registerAndSaveToken()
      })()
    })
  }

  handleNotification(notification: Notifications.Notification) {
    const { data } = notification.request.content

    // The owner's own session went overdue — escalate their device's
    // location tracking (higher-frequency updates) so the circle gets a
    // fresher trail. `session_expired` is the type the backend actually
    // sends to the owner (constants/notificationTypes.json); the previous
    // check matched types that were never emitted and so never fired.
    if (data?.type === 'session_expired') {
      locationTracking
        .escalateTracking()
        .catch(err => notify(err, 'notifications.escalate-tracking-from-push'))
    }

    // Server escalation pushes: refresh the lock-screen Live Activity /
    // ongoing notification (and the store) immediately instead of waiting
    // for the next poll tick. Foreground-only by nature — this handler
    // doesn't run while suspended — so the poll stays the guaranteed floor
    // and this is the accelerant.
    if (
      data?.type === 'circle_alerted' ||
      data?.type === 'alert_acknowledged'
    ) {
      const sessionId = data?.session_id as string | undefined
      if (sessionId) {
        void this.refreshLiveStatusFromPush(sessionId)
      }
    }

    // A contact opted out (possibly the last one) — refresh the circle so
    // the session screens can retract the "your contacts will be alerted"
    // promise while it's actually false. Foreground-only; closed-app cases
    // catch up on the next mount's circle load.
    if (
      data?.type === 'contact_opted_out' ||
      data?.type === 'circle_emptied' ||
      data?.type === 'circle_emptied_mid_session'
    ) {
      void (async () => {
        try {
          // Lazy require — avoids a module cycle, same as the session store.
          const { useCircleStore } =
            // eslint-disable-next-line @typescript-eslint/no-require-imports
            require('../store/useCircleStore') as typeof import('../store/useCircleStore')
          await useCircleStore.getState().loadCircleOfTrust()
        } catch (err) {
          notify(err, 'notifications.refresh-circle-from-push')
        }
      })()
    }
  }

  private async refreshLiveStatusFromPush(sessionId: string): Promise<void> {
    try {
      // Lazy require: useSessionStore imports this service (cycle otherwise).
      const { useSessionStore } =
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        require('../store/useSessionStore') as typeof import('../store/useSessionStore')
      const active = useSessionStore.getState().activeSession
      // Defensive: only a push about the owner's own current session may
      // drive their live status (a push about any other session is ignored). GET /sessions/{id} is used (not /active) because
      // it computes alert_acknowledged/circle_unreachable.
      if (!active || active.id !== sessionId) return
      const session = await api.getSession(sessionId)
      useSessionStore.setState({ activeSession: session })
      await liveStatusService.update(session)
    } catch (err) {
      // Best-effort accelerant — the session screen's own poll remains the floor.
      notify(err, 'notifications.refresh-live-status-from-push')
    }
  }

  handleNotificationResponse(response: Notifications.NotificationResponse) {
    const { notification: responseNotification, actionIdentifier } = response
    const { data } = responseNotification.request.content

    if (actionIdentifier === EXTEND_ACTION_ID) {
      // One-tap extend straight from the reminder — no app foregrounding.
      // Backend pushes use session_id; the local reminder uses sessionId.
      const sessionId = (data?.session_id ?? data?.sessionId) as
        | string
        | undefined
      if (sessionId) {
        api
          .extendSession(sessionId, 30)
          .then(async updated => {
            // Reminders are client-owned: the deadline moved, so the local
            // ladder must move with it — even from this no-app-foreground
            // path (the in-app extend flow reschedules via the store).
            const newDeadline = getSessionDeadline(updated)
            if (newDeadline) {
              await this.cancelCheckInReminder(sessionId)
              await this.scheduleCheckInReminder(newDeadline, sessionId)
            }
            await this.sendLocalNotification(
              'Session extended',
              'Your check-in deadline moved back 30 minutes.'
            )
          })
          .catch(err => {
            notify(err, 'notifications.extend-from-action')
            this.sendLocalNotification(
              "Couldn't extend",
              'Open the app to extend your session or check in.'
            )
          })
      }
      return
    }

    if (actionIdentifier === Notifications.DEFAULT_ACTION_IDENTIFIER) {
      this.handledResponseIds.add(responseNotification.request.identifier)
      const route = routeForNotificationType(data?.type)
      if (route) {
        try {
          router.push(route)
        } catch (err) {
          // Navigation not mounted yet (tap raced a cold start) — the
          // initial-route consumption in app/index.tsx covers that case.
          notify(err, 'notifications.route-tap')
        }
      }
    }
  }

  // Response identifiers already routed by the live listener, so the
  // cold-start consumption below can't double-route the same tap.
  private handledResponseIds = new Set<string>()

  /**
   * The destination for the notification tap that LAUNCHED the app from a
   * killed state, consumed exactly once. The live response listener isn't
   * reliably mounted in time for that first tap; app/index.tsx calls this
   * after auth settles and redirects accordingly.
   */
  async consumeInitialNotificationRoute(): Promise<Href | null> {
    try {
      const last = await Notifications.getLastNotificationResponseAsync()
      if (!last) return null
      const id = last.notification.request.identifier
      if (this.handledResponseIds.has(id)) return null
      this.handledResponseIds.add(id)
      if (last.actionIdentifier !== Notifications.DEFAULT_ACTION_IDENTIFIER) {
        return null
      }
      const data = last.notification.request.content.data
      return routeForNotificationType(data?.type)
    } catch (err) {
      notify(err, 'notifications.initial-route')
      return null
    }
  }

  /**
   * Schedule the full owner reminder ladder (T-30/10/5/0) as OS-scheduled
   * local notifications — the device's own clock fires them with no network,
   * so they survive dead zones and backend outages. Rungs already in the
   * past are skipped (a short session simply gets fewer). Idempotent per
   * rung id; callers cancel first when rescheduling.
   */
  async scheduleCheckInReminder(checkInTime: Date, sessionId: string) {
    for (const { minutesBefore, fireAt } of computeReminderRungs(checkInTime)) {
      const atDeadline = minutesBefore === 0
      await Notifications.scheduleNotificationAsync({
        // Scoped id so cancel/reschedule targets only THIS session's rung,
        // never unrelated scheduled notifications.
        identifier: checkInReminderId(sessionId, minutesBefore),
        content: {
          title: atDeadline
            ? SESSION_DEADLINE_TITLE
            : sessionExpiringTitle(checkInTime),
          body: atDeadline
            ? SESSION_DEADLINE_BODY
            : sessionExpiringBody(minutesBefore),
          data: {
            type: 'session_reminder',
            sessionId,
            minutes_remaining: minutesBefore,
          },
          sound: true,
          // Carries the one-tap "Extend 30 min" action (same category the
          // backend pushes used).
          categoryIdentifier: 'session_expiring',
        },
        trigger: {
          type: Notifications.SchedulableTriggerInputTypes.DATE,
          date: fireAt,
        },
      })
    }
  }

  /** Cancel this session's whole reminder ladder (scoped, not app-wide). */
  async cancelCheckInReminder(sessionId: string) {
    for (const minutes of REMINDER_LADDER_MINUTES) {
      await this.cancelScheduledNotification(
        checkInReminderId(sessionId, minutes)
      )
    }
    // Sessions scheduled before the ladder shipped carry the old single id.
    await this.cancelScheduledNotification(legacyCheckInReminderId(sessionId))
  }

  async cancelAllScheduledNotifications() {
    await Notifications.cancelAllScheduledNotificationsAsync()
  }

  async cancelScheduledNotification(identifier: string) {
    await Notifications.cancelScheduledNotificationAsync(identifier)
  }

  // Send immediate local notification
  async sendLocalNotification(
    title: string,
    body: string,
    data?: Record<string, unknown>
  ) {
    await Notifications.scheduleNotificationAsync({
      content: {
        title,
        body,
        data,
        sound: true,
      },
      trigger: null, // Immediate
    })
  }

  // Clean up listeners
  cleanup() {
    if (this.notificationListener) {
      this.notificationListener.remove()
    }
    if (this.responseListener) {
      this.responseListener.remove()
    }
    if (this.appStateListener) {
      this.appStateListener.remove()
    }
  }
}

export default NotificationService.getInstance()
