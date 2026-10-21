/**
 * Push-token registration reaches the BACKEND on grant — not just on the next
 * cold start. `registerForPushNotificationsAsync` only writes the token to
 * AsyncStorage; `registerAndSaveToken` also persists it to the backend, and is
 * the entry point onboarding / the permission panel / app-foreground call after
 * a grant. Regression guard: a mid-app notifications grant used to leave the
 * backend with no token until relaunch, so server pushes silently never arrived.
 */

import { AppState } from 'react-native'
import * as Notifications from 'expo-notifications'
import api from './api'
import notificationService from './notifications'

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('./api', () => ({
  __esModule: true,
  default: { updateUser: jest.fn() },
}))
jest.mock('./locationTracking', () => ({ __esModule: true, default: {} }))
jest.mock('./notificationRouting', () => ({ routeForNotificationType: jest.fn() }))
jest.mock('expo-device', () => ({ isDevice: true }))
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { extra: { eas: { projectId: 'p' } } } },
}))
jest.mock('expo-router', () => ({ router: { push: jest.fn() } }))
jest.mock('expo-notifications', () => ({
  setNotificationHandler: jest.fn(),
  getPermissionsAsync: jest.fn(),
  getExpoPushTokenAsync: jest.fn(),
  setNotificationChannelAsync: jest.fn(),
  setNotificationCategoryAsync: jest.fn(),
  addNotificationReceivedListener: jest.fn(() => ({ remove: jest.fn() })),
  addNotificationResponseReceivedListener: jest.fn(() => ({ remove: jest.fn() })),
  addPushTokenListener: jest.fn(() => ({ remove: jest.fn() })),
  AndroidImportance: { MAX: 5 },
}))

const mockGetPerms = Notifications.getPermissionsAsync as jest.Mock
const mockGetToken = Notifications.getExpoPushTokenAsync as jest.Mock
const mockUpdateUser = api.updateUser as jest.Mock

const TOKEN = 'ExponentPushToken[abc]'

beforeEach(() => {
  jest.clearAllMocks()
  mockGetToken.mockResolvedValue({ data: TOKEN })
  mockUpdateUser.mockResolvedValue(undefined)
})

afterEach(() => {
  // Remove any listeners a test wired up (AppState / notification listeners),
  // so no open handle keeps jest alive.
  notificationService.cleanup()
})

describe('registerAndSaveToken', () => {
  it('saves the token to the backend when notifications are granted', async () => {
    mockGetPerms.mockResolvedValue({ status: 'granted' })
    const token = await notificationService.registerAndSaveToken()
    expect(token).toBe(TOKEN)
    expect(mockUpdateUser).toHaveBeenCalledWith({ expo_push_token: TOKEN })
  })

  it('is a no-op (no token fetch, no backend call) when not granted', async () => {
    mockGetPerms.mockResolvedValue({ status: 'denied' })
    const token = await notificationService.registerAndSaveToken()
    expect(token).toBeNull()
    expect(mockGetToken).not.toHaveBeenCalled()
    expect(mockUpdateUser).not.toHaveBeenCalled()
  })

  it('does not throw when the backend save fails', async () => {
    mockGetPerms.mockResolvedValue({ status: 'granted' })
    mockUpdateUser.mockRejectedValue(new Error('network'))
    await expect(notificationService.registerAndSaveToken()).resolves.toBe(TOKEN)
  })
})

describe('foreground re-registration wiring', () => {
  it('registers an AppState "change" listener that re-registers when no token is stored', async () => {
    const spy = jest.spyOn(AppState, 'addEventListener')
    notificationService.setupNotificationListeners()
    const changeCall = spy.mock.calls.find(c => c[0] === 'change')
    expect(changeCall).toBeDefined()
    spy.mockRestore()
  })
})
