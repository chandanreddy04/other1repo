/**
 * Pure-function test for the Android ongoing-notification press mapping.
 * The Android session notification is Notifee's (not expo-notifications'),
 * so a tap on it doesn't flow through services/notifications.ts's response
 * listener — services/liveStatus.ts wires its own Notifee foreground/
 * background press handlers. `ongoingNotificationPressRoute` is the pure
 * decision at the heart of that wiring: given a Notifee event and its
 * PRESS event-type constant, does this tap route the owner to their
 * session (mirroring the iOS Live Activity's
 * madeithome://sessions/active deep link)? Kept dependency-free (no
 * `@notifee/react-native` import) so this needs no native-module mocking.
 *
 * Related: services/liveStatus.ts (registerAndroidNotificationPressHandler,
 * pressAction.launchActivity), services/liveStatus.test.ts (the existing
 * Android notification-content coverage, left untouched).
 */
import { ongoingNotificationPressRoute, ANDROID_NOTIFICATION_ID } from './liveStatus'

const PRESS = 1
const ACTION_PRESS = 2 // a different Notifee event type, e.g. a custom action tap

describe('ongoingNotificationPressRoute', () => {
  it('routes to the active session on a press of the ongoing notification', () => {
    const route = ongoingNotificationPressRoute(
      { type: PRESS, detail: { notification: { id: ANDROID_NOTIFICATION_ID } } },
      PRESS
    )
    expect(route).toBe('/sessions/active')
  })

  it('ignores a press on a different notification', () => {
    const route = ongoingNotificationPressRoute(
      { type: PRESS, detail: { notification: { id: 'some-other-notification' } } },
      PRESS
    )
    expect(route).toBeNull()
  })

  it('ignores a non-press event on the ongoing notification', () => {
    const route = ongoingNotificationPressRoute(
      {
        type: ACTION_PRESS,
        detail: { notification: { id: ANDROID_NOTIFICATION_ID } },
      },
      PRESS
    )
    expect(route).toBeNull()
  })

  it('ignores an event with no notification id', () => {
    const route = ongoingNotificationPressRoute({ type: PRESS, detail: {} }, PRESS)
    expect(route).toBeNull()
  })
})
