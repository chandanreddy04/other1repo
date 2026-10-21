/**
 * Escalation pushes (circle_alerted / alert_acknowledged) received while the
 * is running refresh the live status from server truth — guarded on the
 * app — guarded on the push's session being the user's OWN (acknowledgement
 * broadcasts also concern circle members about other people's sessions), and fetched via
 * GET /sessions/{id} (the endpoint that computes alert_acknowledged).
 */

import notificationService from './notifications'
import api from './api'
import liveStatusService from './liveStatus'
import { useSessionStore } from '../store/useSessionStore'
import type * as Notifications from 'expo-notifications'

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('./api', () => ({
  __esModule: true,
  default: { getSession: jest.fn() },
}))
jest.mock('./locationTracking', () => ({
  __esModule: true,
  default: { escalateTracking: jest.fn().mockResolvedValue(undefined) },
}))
jest.mock('./liveStatus', () => ({
  __esModule: true,
  default: { update: jest.fn().mockResolvedValue(undefined) },
}))
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
  AndroidImportance: { MAX: 5 },
}))
jest.mock('../store/useSessionStore', () => {
  const state: { activeSession: { id: string } | null } = {
    activeSession: null,
  }
  return {
    useSessionStore: {
      getState: () => state,
      setState: jest.fn((partial: object) => Object.assign(state, partial)),
    },
  }
})

const mockGetSession = api.getSession as jest.Mock
const mockLiveUpdate = liveStatusService.update as jest.Mock
const storeState = useSessionStore.getState() as {
  activeSession: { id: string } | null
}

function pushNotification(type: string, sessionId: string) {
  return {
    request: { content: { data: { type, session_id: sessionId } } },
  } as unknown as Notifications.Notification
}

// The handler fires an un-awaited async chain — drain microtasks.
const flush = () => new Promise(resolve => setTimeout(resolve, 0))

beforeEach(() => {
  jest.clearAllMocks()
  storeState.activeSession = null
})

describe('handleNotification — escalation push refresh', () => {
  it('refreshes store + live status for the own active session', async () => {
    storeState.activeSession = { id: 's1' }
    const fresh = { id: 's1', status: 'alerted', alert_acknowledged: true }
    mockGetSession.mockResolvedValueOnce(fresh)

    notificationService.handleNotification(
      pushNotification('circle_alerted', 's1')
    )
    await flush()

    expect(mockGetSession).toHaveBeenCalledWith('s1')
    expect(mockLiveUpdate).toHaveBeenCalledWith(fresh)
    expect(storeState.activeSession).toEqual(fresh)
  })

  it('ignores alert_acknowledged about someone else’s session', async () => {
    storeState.activeSession = { id: 'mine' }

    notificationService.handleNotification(
      pushNotification('alert_acknowledged', 'theirs')
    )
    await flush()

    expect(mockGetSession).not.toHaveBeenCalled()
    expect(mockLiveUpdate).not.toHaveBeenCalled()
  })

  it('does nothing without an active session', async () => {
    notificationService.handleNotification(
      pushNotification('circle_alerted', 's1')
    )
    await flush()

    expect(mockGetSession).not.toHaveBeenCalled()
  })

  it('survives a failed fetch (poll remains the floor)', async () => {
    storeState.activeSession = { id: 's1' }
    mockGetSession.mockRejectedValueOnce(new Error('offline'))

    notificationService.handleNotification(
      pushNotification('alert_acknowledged', 's1')
    )
    await flush()

    expect(mockLiveUpdate).not.toHaveBeenCalled()
  })
})
