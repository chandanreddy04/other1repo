import { Platform } from 'react-native'
import { router, type Href } from 'expo-router'
import { Session } from '../types'
import { COLORS } from '../constants'
import { loadNativeModule } from './nativeModules'
import { getSessionDeadline } from '../utils/sessionTiming'
import { notify } from './errorReporting'

// NOTE: expo-live-activity is deprecated; startOrUpdateActivity/endAllActivities
// and the branded widget layout come from a local patch (mobile/patches/).
// Migrate to expo-widgets at the next Expo SDK upgrade (needs SDK >= 55) — see
// docs/mobile-release.md "Tech debt".
//
// No id/persistence is tracked. The native iOS startOrUpdateActivity /
// endAllActivities are idempotent against the OS's running activities, and
// Android's ongoing notification uses a fixed id — so live status is a pure
// reconcile of "is there an active session?": a live session ⇒ exactly one
// activity/notification, no session ⇒ none. This survives app relaunches
// without orphaning (which the old start-only, module-memory-id code did).
let androidNotificationInterval: ReturnType<typeof setInterval> | null = null
// One-shot timer that re-renders the Android notification AT the deadline, so
// the danger flip is on time instead of up to a minute late (the 60s interval).
let androidDeadlineTimeout: ReturnType<typeof setTimeout> | null = null

export const ANDROID_NOTIFICATION_ID = 'active-session'

// Brand mark bundled into the iOS widget target from assets/liveActivity/
// (MadeItHomeMark.png → MadeItHomeMark.imageset via the expo-live-activity
// plugin). The name matches the imageset; iOS resolves it with UIImage(named:).
const LIVE_ACTIVITY_MARK = 'MadeItHomeMark'

// Lazy, require-based native loads via the shared helper (cached, alerts once,
// returns null when unavailable) — keeps this testable and consistent with the
// rest of the app instead of raw dynamic import().
function loadLiveActivity() {
  return loadNativeModule<typeof import('expo-live-activity')>(
    'expo-live-activity',
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    () => require('expo-live-activity')
  )
}

function loadNotifee() {
  return loadNativeModule<typeof import('@notifee/react-native')>(
    '@notifee/react-native',
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    () => require('@notifee/react-native')
  )
}

function getDeadlineMs(session: Session): number {
  return getSessionDeadline(session)?.getTime() ?? 0
}

function getStartMs(session: Session): number {
  return session.created_at ? new Date(session.created_at).getTime() : 0
}

function formatReturnClock(session: Session): string {
  const deadline = getSessionDeadline(session)
  if (!deadline) return ''
  return deadline.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

// Brand-voice, state-aware copy for the Live Activity. The lock screen is the
// most-seen surface during a check-in, so it must speak the app's language, not
// "Session"/"Overdue" developer jargon — these strings mirror the in-app
// session screen's live mode (overdueHeading) so the two surfaces never drift.
// Single source of truth for BOTH iOS and Android.
export interface LiveStatusContent {
  title: string
  subtitle: string
  overdue: boolean
}

// The escalation-ladder copy, one shared table: consumed by liveStatusContent
// (lock screen / ongoing notification) AND the in-app session screen's live
// heading, so the two surfaces literally cannot drift — never restate these
// strings inline.
export const LIVE_STATUS_COPY = {
  // alert_acknowledged is server truth from the owner poll endpoints — a
  // circle member pressed Acknowledge. Copy states exactly what a tap
  // proves: an acknowledgement — never "on their way" (nobody promised to
  // travel; owner decision 2026-07-18).
  acknowledged: {
    title: 'Your alert was acknowledged',
    // The tap proves a human deliberately responded — the strongest TRUE
    // statement, short of promising they're coming.
    subtitle: 'A Circle member knows you need help',
  },
  alerted: {
    title: 'Your Circle has been notified',
    // What the system provably DID (the alert SMS literally asks this) —
    // never a prediction of what humans will do.
    subtitle: "They've been asked to check on you",
  },
  missed: {
    title: 'Notifying your Circle',
    subtitle: 'Stay safe'
  },
  // circle_unreachable is server truth from the owner poll endpoints — every
  // circle-alert delivery is terminally undeliverable (or the circle emptied
  // mid-session). "Notifying your Circle…" would be false reassurance here:
  // no one is coming unless the owner acts themselves.
  unreachable: {
    title: "We couldn't reach your Circle",
    subtitle: 'Call or text them directly, or call 911',
  },
  // ACTIVE past the deadline (grace window). Also the copy the iOS widget
  // swaps to when it flips to the overdue treatment ON-DEVICE (staleDate =
  // the deadline passing while the app is suspended) — it must be pre-baked
  // into the activity state because no JS runs at that moment.
  overdue: {
    title: "Check-in overdue",
    subtitle: 'Your Circle will be notified soon',
  },
} as const

export const OVERDUE_FALLBACK = LIVE_STATUS_COPY.overdue

export function liveStatusContent(session: Session): LiveStatusContent {
  const returnMs = getDeadlineMs(session)
  const pastDeadline = returnMs > 0 && Date.now() >= returnMs

  if (session.status === 'alerted') {
    return {
      ...(session.alert_acknowledged
        ? LIVE_STATUS_COPY.acknowledged
        : LIVE_STATUS_COPY.alerted),
      overdue: true,
    }
  }
  if (session.status === 'missed') {
    return {
      ...(session.circle_unreachable
        ? LIVE_STATUS_COPY.unreachable
        : LIVE_STATUS_COPY.missed),
      overdue: true,
    }
  }
  // ACTIVE — counting down, or in the grace window past the deadline.
  if (pastDeadline) {
    return { ...LIVE_STATUS_COPY.overdue, overdue: true }
  }
  const clock = formatReturnClock(session)
  return {
    title: 'Made It Home',
    subtitle: clock ? `Check-in by ${clock}` : 'Check-in soon',
    overdue: false,
  }
}

// Compact server-truth label for the Home countdown pill. MISSED/ALERTED
// relabel the pill from the shared table; null means "no escalation — show
// the clock label". "acknowledged" is deliberately excluded: the compact pill
// can't carry it, and the session screen's live mode owns that state.
export function homePillStatusTitle(session: Session): string | null {
  if (session.status === 'missed') {
    return (
      session.circle_unreachable
        ? LIVE_STATUS_COPY.unreachable
        : LIVE_STATUS_COPY.missed
    ).title
  }
  if (session.status === 'alerted') return LIVE_STATUS_COPY.alerted.title
  return null
}

// ─── iOS Live Activity ───

function startIOS(session: Session) {
  const LiveActivity = loadLiveActivity()
  if (!LiveActivity) return
  const returnMs = getDeadlineMs(session)
  if (!returnMs) return

  const { title, subtitle, overdue } = liveStatusContent(session)
  // SOS has no meaningful deadline (it IS now) — no countdown, no bar; the
  // status copy carries the card. Check-ins get the full timer treatment,
  // with startDate so the bar fills start → deadline.
  const isSOS = session.session_type === 'sos'
  const startMs = getStartMs(session)

  // Idempotent: updates the running activity in place if one exists, else
  // starts one. No id to track, so relaunch/foreground never duplicates.
  //
  // Colors come from the design system (brand teal / danger), never inline
  // hex. Both live in the immutable iOS attributes; the WIDGET picks between
  // them per render (`overdue` flag OR its on-device stale flip at the
  // deadline), so the card turns danger-red the moment time runs out even
  // with the app suspended — no restart, no JS involved. The pre-baked
  // overdueTitle/Subtitle are what that native flip displays; once the server
  // escalates (missed → alerted → acknowledged) we pass the live copy on both
  // sides so the paths agree.
  LiveActivity.startOrUpdateActivity(
    {
      title,
      subtitle,
      overdue,
      overdueTitle: overdue ? title : OVERDUE_FALLBACK.title,
      overdueSubtitle: overdue ? subtitle : OVERDUE_FALLBACK.subtitle,
      ...(isSOS
        ? {}
        : {
            progressBar: {
              date: returnMs,
              ...(startMs ? { startDate: startMs } : {}),
            },
          }),
      imageName: LIVE_ACTIVITY_MARK,
      dynamicIslandImageName: LIVE_ACTIVITY_MARK,
    },
    {
      deepLinkUrl: 'madeithome://sessions/active',
      backgroundColor: COLORS.primary,
      overdueBackgroundColor: COLORS.danger,
      titleColor: COLORS.white,
      subtitleColor: COLORS.white,
      progressViewTint: COLORS.white,
      progressViewLabelColor: COLORS.white,
    }
  )
}

function stopIOS() {
  const LiveActivity = loadLiveActivity()
  if (!LiveActivity) return
  // Ends every running activity immediately — clears any orphan a prior launch
  // may have left, without needing its id.
  LiveActivity.endAllActivities()
}

// ─── Android Ongoing Notification ───

function clearAndroidTimers() {
  if (androidNotificationInterval) {
    clearInterval(androidNotificationInterval)
    androidNotificationInterval = null
  }
  if (androidDeadlineTimeout) {
    clearTimeout(androidDeadlineTimeout)
    androidDeadlineTimeout = null
  }
}

// The ongoing notification is a Notifee notification, not an expo-
// notifications one, so a tap on it never reaches
// services/notifications.ts's response listener — Notifee has its own
// foreground/background press-event system. This is the pure mapping from a
// press event to a destination, mirroring the iOS Live Activity's
// `madeithome://sessions/active` deep link (both land the owner back on
// their running session). Kept pure (no notifee import) so it's unit-
// testable without mocking the native module: callers pass the loaded
// module's own `EventType.PRESS` value.
export function ongoingNotificationPressRoute(
  event: { type: number; detail: { notification?: { id?: string } } },
  pressEventType: number
): Href | null {
  if (event.type !== pressEventType) return null
  if (event.detail.notification?.id !== ANDROID_NOTIFICATION_ID) return null
  return '/sessions/active'
}

let androidPressHandlerRegistered = false

/**
 * Wires Notifee's press events for the ongoing session notification to
 * in-app navigation. Registers once per JS runtime (the module-level flag):
 * `onBackgroundEvent` keeps a single handler (a re-register would replace
 * it), but every `onForegroundEvent` call ADDS a listener, so without the
 * flag each startAndroid() would route one tap N times. Registers both
 * foreground (app resumed → emitted event) and background (app not resumed →
 * Notifee's headless task) handlers since either fires depending on the app
 * state when the notification is tapped.
 *
 * Registering lazily here, rather than at app entry, is sound because this
 * notification only exists while the JS runtime that registered the handlers
 * is alive: it's an `asForegroundService` notification, posted only by this
 * runtime, and stopForegroundService()/process death removes it. The one gap
 * — the activity was destroyed (swiped from recents) while the process and
 * service lived on, so the tap relaunches a fresh navigation tree and
 * router.push() below can't land — is covered by
 * consumeInitialOngoingNotificationRoute(), read by the launch router
 * (app/index.tsx), exactly like the expo-notifications cold-start path.
 */
function registerAndroidNotificationPressHandler() {
  if (androidPressHandlerRegistered) return
  const notifeeModule = loadNotifee()
  if (!notifeeModule) return
  const notifee = notifeeModule.default
  const { EventType } = notifeeModule
  // Defensive: guards a test double that stubs only the methods it needs
  // (see liveStatus.test.ts) as well as any future stripped-down build.
  if (
    !EventType ||
    typeof notifee.onForegroundEvent !== 'function' ||
    typeof notifee.onBackgroundEvent !== 'function'
  ) {
    return
  }

  const handlePress = (event: {
    type: number
    detail: { notification?: { id?: string } }
  }) => {
    const route = ongoingNotificationPressRoute(event, EventType.PRESS)
    if (!route) return
    try {
      router.push(route)
    } catch (err) {
      // Navigation not mounted yet (tap relaunched the activity) — the
      // launch router's consumeInitialOngoingNotificationRoute() covers
      // that case; same handling as the expo-notifications response
      // listener in services/notifications.ts.
      notify(err, 'liveStatus.route-ongoing-notification-press')
    }
  }

  notifee.onForegroundEvent(handlePress)
  notifee.onBackgroundEvent(async event => handlePress(event))
  androidPressHandlerRegistered = true
}

/**
 * The destination when a press on the ongoing notification (re)launched the
 * app's activity — Notifee's `getInitialNotification()`, which it consumes
 * once. app/index.tsx reads this alongside
 * notificationService.consumeInitialNotificationRoute() so a tap that
 * arrived before navigation mounted still lands on the session. Android
 * only (the iOS surface is the Live Activity's deep link); never throws.
 */
export async function consumeInitialOngoingNotificationRoute(): Promise<Href | null> {
  if (Platform.OS !== 'android') return null
  const notifeeModule = loadNotifee()
  if (!notifeeModule) return null
  const notifee = notifeeModule.default
  if (typeof notifee.getInitialNotification !== 'function') return null
  try {
    const initial = await notifee.getInitialNotification()
    if (!initial) return null
    if (initial.notification.id !== ANDROID_NOTIFICATION_ID) return null
    return '/sessions/active'
  } catch (err) {
    notify(err, 'liveStatus.initial-ongoing-notification-route')
    return null
  }
}

async function startAndroid(session: Session) {
  const notifeeModule = loadNotifee()
  if (!notifeeModule) return
  const notifee = notifeeModule.default
  const { AndroidImportance } = notifeeModule

  registerAndroidNotificationPressHandler()

  // Clear any prior timers FIRST — repeated start()s must not leak intervals/
  // timeouts that would re-post the (fixed-id) notification after stop().
  clearAndroidTimers()

  const channelId = await notifee.createChannel({
    id: 'session-status',
    name: 'Session Status',
    importance: AndroidImportance.LOW,
    vibration: false,
  })

  const returnMs = getDeadlineMs(session)
  const startMs = getStartMs(session)
  const isSOS = session.session_type === 'sos'
  // displayNotification with a fixed id is idempotent — the first call creates
  // it, each later call updates it in place. The re-render recomputes
  // liveStatusContent, so the copy + accent flip to the overdue treatment; a
  // one-shot timeout at the deadline makes that flip on time (the 60s interval
  // alone lagged up to a minute). Brand hex from the design system (teal
  // active / danger overdue — the same danger the in-app session screen's
  // live mode shows), never notifee's generic AndroidColor names. The
  // chronometer counts DOWN to the deadline while active and UP from it once
  // overdue — the up count answers "how long overdue am I", second-accurate
  // and OS-rendered.
  const render = async () => {
    const { title, subtitle, overdue } = liveStatusContent(session)
    const showTimer = returnMs > 0 && !isSOS
    await notifee.displayNotification({
      id: ANDROID_NOTIFICATION_ID,
      title,
      body: subtitle,
      android: {
        channelId,
        asForegroundService: true,
        ongoing: true,
        smallIcon: 'notification_icon',
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        largeIcon: require('../assets/liveActivity/MadeItHomeMark.png'),
        color: overdue ? COLORS.danger : COLORS.primary,
        // launchActivity is required on Android for a press to actually
        // bring the app forward at all (Notifee gotcha — pressAction alone
        // is inert); registerAndroidNotificationPressHandler() then routes
        // that press to the session screen, mirroring the iOS Live
        // Activity's madeithome://sessions/active deep link.
        pressAction: { id: 'default', launchActivity: 'default' },
        ...(showTimer
          ? {
              timestamp: returnMs,
              showTimestamp: true,
              showChronometer: true,
              chronometerDirection: overdue ? ('up' as const) : ('down' as const),
            }
          : {}),
        // Session progress filling left → right (start → deadline), mirroring
        // the iOS bar; recomputed on each render. Dropped once overdue — the
        // count-up chronometer carries the state from there.
        ...(showTimer && !overdue && startMs && returnMs > startMs
          ? {
              progress: {
                max: returnMs - startMs,
                current: Math.min(returnMs - startMs, Date.now() - startMs),
              },
            }
          : {}),
      },
    })
  }

  await render()
  androidNotificationInterval = setInterval(render, 60000)
  // Re-render exactly at the deadline so the danger flip is on time. The
  // asForegroundService notification keeps the JS runtime alive in the
  // background, so this fires with the app off-screen too. (+1s so
  // liveStatusContent's now >= deadline comparison is decisively true.)
  if (returnMs > Date.now()) {
    androidDeadlineTimeout = setTimeout(() => {
      void render()
    }, returnMs - Date.now() + 1000)
  }
}

async function stopAndroid() {
  clearAndroidTimers()
  const notifeeModule = loadNotifee()
  if (!notifeeModule) return
  const notifee = notifeeModule.default
  await notifee.stopForegroundService()
  await notifee.cancelNotification(ANDROID_NOTIFICATION_ID)
}

// ─── Public API ───

const liveStatusService = {
  async start(session: Session) {
    if (Platform.OS === 'ios') startIOS(session)
    else if (Platform.OS === 'android') await startAndroid(session)
  },

  // startOrUpdate (iOS) and the fixed-id notification (Android) make "update"
  // identical to "start" — both reconcile to the latest session state.
  async update(session: Session) {
    await this.start(session)
  },

  async stop() {
    if (Platform.OS === 'ios') stopIOS()
    else if (Platform.OS === 'android') await stopAndroid()
  },

  // Source-of-truth reconcile: active session ⇒ one live status, none ⇒ stop.
  // Call on app launch (both branches — this is what clears a status left over
  // from a session that ended while the app was closed), create, and complete.
  async reconcile(session: Session | null) {
    if (session) await this.start(session)
    else await this.stop()
  },
}

export default liveStatusService
