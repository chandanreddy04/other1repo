/**
 * Wiring test for the Android ongoing-notification press handlers.
 * services/liveStatus.test.ts's Notifee double has no `EventType` /
 * `onForegroundEvent` / `onBackgroundEvent`, so the registration guard in
 * registerAndroidNotificationPressHandler() skips there — this file supplies
 * a double that has them and pins: handlers register exactly once across
 * repeated startAndroid() calls (each `onForegroundEvent` call ADDS a
 * listener in Notifee), a PRESS on the ongoing notification routes to
 * /sessions/active from both the foreground and background handlers, other
 * notifications/event types don't route, a router throw is reported (not
 * raised), and the launch router's consumeInitialOngoingNotificationRoute()
 * reads Notifee's initial notification.
 *
 * Related: services/liveStatus.ts, services/liveStatus.test.ts,
 * services/liveStatusOngoingNotificationPressRoute.test.ts, app/index.tsx.
 */
import { Platform } from 'react-native'
import { router } from 'expo-router'
import { Session } from '../types'
import { notify } from './errorReporting'
import liveStatusService, {
  ANDROID_NOTIFICATION_ID,
  consumeInitialOngoingNotificationRoute,
} from './liveStatus'

type Handler = (event: {
  type: number
  detail: { notification?: { id?: string } }
}) => unknown

const PRESS = 1
const ACTION_PRESS = 2

const mockOnForegroundEvent = jest.fn()
const mockOnBackgroundEvent = jest.fn()
const mockGetInitialNotification = jest.fn()

jest.mock('./nativeModules', () => ({
  loadNativeModule: (_name: string, loader: () => unknown) => loader(),
}))
jest.mock('./errorReporting', () => ({ notify: jest.fn() }))
jest.mock('expo-router', () => ({ router: { push: jest.fn() } }))
jest.mock('expo-live-activity', () => ({
  __esModule: true,
  startOrUpdateActivity: jest.fn(),
  endAllActivities: jest.fn(),
}))
jest.mock('@notifee/react-native', () => ({
  __esModule: true,
  default: {
    createChannel: jest.fn().mockResolvedValue('session-status'),
    displayNotification: jest.fn(),
    cancelNotification: jest.fn(),
    stopForegroundService: jest.fn(),
    onForegroundEvent: (...a: unknown[]) => mockOnForegroundEvent(...a),
    onBackgroundEvent: (...a: unknown[]) => mockOnBackgroundEvent(...a),
    getInitialNotification: (...a: unknown[]) => mockGetInitialNotification(...a),
  },
  AndroidImportance: { LOW: 2 },
  EventType: { PRESS: 1, ACTION_PRESS: 2 },
}))

const mockPush = router.push as jest.Mock
const mockNotify = notify as jest.Mock

const session = {
  id: 's1',
  status: 'active',
  session_type: 'checkin',
  created_at: new Date(Date.now() - 1_800_000).toISOString(),
  expected_return_time: new Date(Date.now() + 3_600_000).toISOString(),
} as unknown as Session

function setPlatform(os: 'ios' | 'android') {
  Object.defineProperty(Platform, 'OS', { get: () => os, configurable: true })
}

const ongoingPress = {
  type: PRESS,
  detail: { notification: { id: ANDROID_NOTIFICATION_ID } },
}

describe('Android ongoing-notification press handlers', () => {
  let foreground: Handler
  let background: Handler

  beforeAll(async () => {
    jest.useFakeTimers()
    setPlatform('android')
    // Two starts (e.g. start + update) — must not double-register.
    await liveStatusService.start(session)
    await liveStatusService.start(session)
    foreground = mockOnForegroundEvent.mock.calls[0]?.[0]
    background = mockOnBackgroundEvent.mock.calls[0]?.[0]
  })

  afterAll(async () => {
    await liveStatusService.stop()
    jest.useRealTimers()
  })

  beforeEach(() => {
    mockPush.mockReset()
    mockNotify.mockReset()
  })

  it('registers each handler exactly once across repeated startAndroid() calls', () => {
    expect(mockOnForegroundEvent).toHaveBeenCalledTimes(1)
    expect(mockOnBackgroundEvent).toHaveBeenCalledTimes(1)
    expect(typeof foreground).toBe('function')
    expect(typeof background).toBe('function')
  })

  it('a foreground PRESS on the ongoing notification routes to /sessions/active', () => {
    foreground(ongoingPress)
    expect(mockPush).toHaveBeenCalledTimes(1)
    expect(mockPush).toHaveBeenCalledWith('/sessions/active')
  })

  it('a background PRESS on the ongoing notification routes to /sessions/active', async () => {
    await background(ongoingPress)
    expect(mockPush).toHaveBeenCalledWith('/sessions/active')
  })

  it('a PRESS on another notification does not route', async () => {
    const other = { type: PRESS, detail: { notification: { id: 'other' } } }
    foreground(other)
    await background(other)
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('a non-PRESS event on the ongoing notification does not route', () => {
    foreground({ ...ongoingPress, type: ACTION_PRESS })
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('a router throw (navigation not mounted) is reported, not raised', () => {
    const err = new Error('not mounted')
    mockPush.mockImplementationOnce(() => {
      throw err
    })
    expect(() => foreground(ongoingPress)).not.toThrow()
    expect(mockNotify).toHaveBeenCalledWith(
      err,
      'liveStatus.route-ongoing-notification-press'
    )
  })
})

describe('consumeInitialOngoingNotificationRoute (launch router)', () => {
  beforeEach(() => {
    mockGetInitialNotification.mockReset()
    mockNotify.mockReset()
    setPlatform('android')
  })

  it('routes a launch from the ongoing notification to /sessions/active', async () => {
    mockGetInitialNotification.mockResolvedValue({
      notification: { id: ANDROID_NOTIFICATION_ID },
      pressAction: { id: 'default' },
    })
    await expect(consumeInitialOngoingNotificationRoute()).resolves.toBe(
      '/sessions/active'
    )
  })

  it('ignores a launch from another Notifee notification or none', async () => {
    mockGetInitialNotification.mockResolvedValueOnce({
      notification: { id: 'other' },
      pressAction: { id: 'default' },
    })
    await expect(consumeInitialOngoingNotificationRoute()).resolves.toBeNull()
    mockGetInitialNotification.mockResolvedValueOnce(null)
    await expect(consumeInitialOngoingNotificationRoute()).resolves.toBeNull()
  })

  it('is a no-op on iOS (the Live Activity deep link covers it)', async () => {
    setPlatform('ios')
    await expect(consumeInitialOngoingNotificationRoute()).resolves.toBeNull()
    expect(mockGetInitialNotification).not.toHaveBeenCalled()
  })

  it('reports and returns null when Notifee throws', async () => {
    const err = new Error('boom')
    mockGetInitialNotification.mockRejectedValue(err)
    await expect(consumeInitialOngoingNotificationRoute()).resolves.toBeNull()
    expect(mockNotify).toHaveBeenCalledWith(
      err,
      'liveStatus.initial-ongoing-notification-route'
    )
  })
})
