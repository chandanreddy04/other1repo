/**
 * Client-owned reminder ladder (owner decision 2026-07-18): ALL owner
 * reminder pushes (T-30/10/5/0) are OS-scheduled local notifications — they
 * fire in dead zones and backend outages; the server sends only the
 * at-deadline SMS. This is the behavior coverage for the ladder that used to
 * live in backend tests (test_owner_reminders_outbox.py now only pins the
 * SMS-only server contract).
 */

import * as Notifications from 'expo-notifications'
import api from './api'
import notificationService, {
  isStaleReminderPresentation,
} from './notifications'
import { useSessionStore } from '../store/useSessionStore'

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('./api', () => ({
  __esModule: true,
  default: { extendSession: jest.fn() },
}))
jest.mock('./locationTracking', () => ({ __esModule: true, default: {} }))
jest.mock('./liveStatus', () => ({ __esModule: true, default: {} }))
jest.mock('./notificationRouting', () => ({
  routeForNotificationType: jest.fn(),
}))
jest.mock('expo-device', () => ({ isDevice: true }))
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { extra: { eas: { projectId: 'p' } } } },
}))
jest.mock('expo-router', () => ({ router: { push: jest.fn() } }))
jest.mock('expo-notifications', () => ({
  setNotificationHandler: jest.fn(),
  scheduleNotificationAsync: jest.fn().mockResolvedValue('id'),
  cancelScheduledNotificationAsync: jest.fn().mockResolvedValue(undefined),
  SchedulableTriggerInputTypes: { DATE: 'date' },
  DEFAULT_ACTION_IDENTIFIER: 'default',
  AndroidImportance: { MAX: 5 },
}))
jest.mock('../store/useSessionStore', () => {
  const state: { activeSession: object | null } = { activeSession: null }
  return { useSessionStore: { getState: () => state } }
})

const mockSchedule = Notifications.scheduleNotificationAsync as jest.Mock
const mockCancel = Notifications.cancelScheduledNotificationAsync as jest.Mock
const mockExtend = api.extendSession as jest.Mock

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

beforeEach(() => {
  jest.clearAllMocks()
})

describe('scheduleCheckInReminder — the client-owned ladder', () => {
  it('schedules all four rungs with per-rung copy and the extend action', async () => {
    const deadline = new Date(Date.now() + 60 * 60_000) // 60 min out
    await notificationService.scheduleCheckInReminder(deadline, 's1')

    expect(mockSchedule).toHaveBeenCalledTimes(4)
    const byId = new Map(
      mockSchedule.mock.calls.map(([arg]) => [arg.identifier, arg])
    )
    expect([...byId.keys()].sort()).toEqual([
      'checkin-reminder-s1-0',
      'checkin-reminder-s1-10',
      'checkin-reminder-s1-30',
      'checkin-reminder-s1-5',
    ])

    const t30 = byId.get('checkin-reminder-s1-30')
    expect(t30.content.title).toMatch(/^⏰ Check in by /)
    expect(t30.content.body).toBe(
      'Your session ends in 30 min. Extend it or check in.'
    )
    expect(t30.content.categoryIdentifier).toBe('session_expiring')
    expect(t30.trigger.date.getTime()).toBe(deadline.getTime() - 30 * 60_000)

    // At-deadline rung carries the distinct "time's up" copy that opens the
    // grace window — mirrored from the backend constants.
    const t0 = byId.get('checkin-reminder-s1-0')
    expect(t0.content.title).toBe("⏰ Time's up")
    expect(t0.content.body).toContain('Circle will be alerted in about 5')
    expect(t0.trigger.date.getTime()).toBe(deadline.getTime())
  })

  it('skips past rungs for a short session', async () => {
    const deadline = new Date(Date.now() + 8 * 60_000) // 8 min out
    await notificationService.scheduleCheckInReminder(deadline, 's1')

    const ids = mockSchedule.mock.calls.map(([arg]) => arg.identifier)
    expect(ids.sort()).toEqual([
      'checkin-reminder-s1-0',
      'checkin-reminder-s1-5',
    ])
  })
})

describe('cancelCheckInReminder', () => {
  it('cancels every rung plus the pre-ladder legacy id', async () => {
    await notificationService.cancelCheckInReminder('s1')

    const ids = mockCancel.mock.calls.map(([id]) => id)
    expect(ids.sort()).toEqual([
      'checkin-reminder-s1',
      'checkin-reminder-s1-0',
      'checkin-reminder-s1-10',
      'checkin-reminder-s1-30',
      'checkin-reminder-s1-5',
    ])
  })
})

describe('isStaleReminderPresentation — fire-time liveness check', () => {
  const storeState = useSessionStore.getState() as {
    activeSession: object | null
  }

  const session = (overrides: object = {}) => ({
    id: 's1',
    status: 'active',
    expected_return_time: new Date(Date.now() + 10 * 60_000).toISOString(),
    ...overrides,
  })

  const reminder = (overrides: object = {}) => ({
    type: 'session_reminder',
    sessionId: 's1',
    minutes_remaining: 10,
    ...overrides,
  })

  beforeEach(() => {
    storeState.activeSession = null
  })

  it('shows a live reminder (session active, deadline where expected)', () => {
    storeState.activeSession = session()
    expect(isStaleReminderPresentation(reminder())).toBe(false)
  })

  it('suppresses when another session shadowed the reminder target', () => {
    storeState.activeSession = session({ id: 'sos-2' })
    expect(isStaleReminderPresentation(reminder())).toBe(true)
  })

  it('suppresses once the session is no longer active', () => {
    storeState.activeSession = session({ status: 'missed' })
    expect(isStaleReminderPresentation(reminder())).toBe(true)
  })

  it('suppresses when the deadline moved (>2 min drift from the rung)', () => {
    // Rung says T-10 but the deadline is now 40 min out — an extend that
    // somehow escaped cancellation.
    storeState.activeSession = session({
      expected_return_time: new Date(Date.now() + 40 * 60_000).toISOString(),
    })
    expect(isStaleReminderPresentation(reminder())).toBe(true)
  })

  it('fails open when the store has no session (cold start)', () => {
    expect(isStaleReminderPresentation(reminder())).toBe(false)
  })

  it('never touches non-reminder notifications', () => {
    storeState.activeSession = session({ id: 'other' })
    expect(
      isStaleReminderPresentation({ type: 'circle_alerted', sessionId: 's1' })
    ).toBe(false)
  })
})

describe('one-tap extend from a reminder notification', () => {
  it('reschedules the ladder against the new deadline', async () => {
    const newDeadline = new Date(Date.now() + 40 * 60_000)
    mockExtend.mockResolvedValueOnce({
      id: 's1',
      expected_return_time: newDeadline.toISOString(),
    })

    notificationService.handleNotificationResponse({
      actionIdentifier: 'extend-30',
      notification: {
        request: {
          identifier: 'n1',
          content: { data: { sessionId: 's1' } },
        },
      },
    } as unknown as Notifications.NotificationResponse)
    await flush()

    expect(mockExtend).toHaveBeenCalledWith('s1', 30)
    // Old ladder cancelled (4 rungs + legacy id)…
    expect(mockCancel.mock.calls.length).toBeGreaterThanOrEqual(5)
    // …and a fresh ladder scheduled against the NEW deadline (T-30/10/5/0
    // all in the future for a 40-min extension), plus the confirmation.
    const scheduled = mockSchedule.mock.calls.map(([arg]) => arg.identifier)
    expect(scheduled).toEqual(
      expect.arrayContaining([
        'checkin-reminder-s1-30',
        'checkin-reminder-s1-10',
        'checkin-reminder-s1-5',
        'checkin-reminder-s1-0',
      ])
    )
  })
})
