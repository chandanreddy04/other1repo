/**
 * O1 copy: the pre-deadline reminder title/body, owner-reviewed 2026-09-27
 * (docs/notifications.md §2.1, O1). This is now mobile's own source of
 * truth for that copy — the backend SESSION_EXPIRING_* mirror was deleted,
 * so there's no server-side pin for it any more. Kept separate from the
 * ladder-timing behavior coverage in notifications.reminderLadder.test.ts.
 * Deadlines are fixed LOCAL wall-clock times far in the future (so no rung is
 * skipped as past) and the expected titles are literals — "h:mm a", no
 * leading zero on the hour.
 */

import * as Notifications from 'expo-notifications'
import notificationService from './notifications'

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

// Local (device-timezone) wall-clock deadlines.
const PM_DEADLINE = new Date(2099, 0, 1, 21, 40) // 9:40 PM
const MIDNIGHT_DEADLINE = new Date(2099, 0, 2, 0, 0) // 12:00 AM

const byIdentifier = () =>
  new Map(mockSchedule.mock.calls.map(([arg]) => [arg.identifier, arg]))

beforeEach(() => {
  jest.clearAllMocks()
})

describe('O1 reminder copy — owner-reviewed 2026-09-27', () => {
  it('titles a pre-deadline rung "⏰ Check in by {deadline, h:mm a}" (PM)', async () => {
    await notificationService.scheduleCheckInReminder(PM_DEADLINE, 's-copy-1')

    const t30 = byIdentifier().get('checkin-reminder-s-copy-1-30')
    expect(t30.content.title).toBe('⏰ Check in by 9:40 PM')
  })

  it('renders a midnight deadline as 12:00 AM', async () => {
    await notificationService.scheduleCheckInReminder(
      MIDNIGHT_DEADLINE,
      's-copy-midnight'
    )

    const t5 = byIdentifier().get('checkin-reminder-s-copy-midnight-5')
    expect(t5.content.title).toBe('⏰ Check in by 12:00 AM')
  })

  it('bodies a pre-deadline rung "Your session ends in {minutes} min. Extend it or check in."', async () => {
    await notificationService.scheduleCheckInReminder(PM_DEADLINE, 's-copy-2')

    const t30 = byIdentifier().get('checkin-reminder-s-copy-2-30')
    const t10 = byIdentifier().get('checkin-reminder-s-copy-2-10')
    expect(t30.content.body).toBe(
      'Your session ends in 30 min. Extend it or check in.'
    )
    expect(t10.content.body).toBe(
      'Your session ends in 10 min. Extend it or check in.'
    )
  })

  it('every pre-deadline rung shares the same deadline-based title', async () => {
    await notificationService.scheduleCheckInReminder(PM_DEADLINE, 's-copy-3')

    const byId = byIdentifier()
    const expected = '⏰ Check in by 9:40 PM'
    expect(byId.get('checkin-reminder-s-copy-3-30').content.title).toBe(expected)
    expect(byId.get('checkin-reminder-s-copy-3-10').content.title).toBe(expected)
    expect(byId.get('checkin-reminder-s-copy-3-5').content.title).toBe(expected)
  })

  it('leaves the at-deadline (T-0) title as "⏰ Time\'s up" — unchanged, mirrors the server SMS', async () => {
    await notificationService.scheduleCheckInReminder(PM_DEADLINE, 's-copy-4')

    const t0 = byIdentifier().get('checkin-reminder-s-copy-4-0')
    expect(t0.content.title).toBe("⏰ Time's up")
  })
})
