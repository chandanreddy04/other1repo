import AsyncStorage from '@react-native-async-storage/async-storage'
import * as Notifications from 'expo-notifications'
import api from './api'
import {
  enqueueSOS,
  clearPendingSOS,
  hasPendingSOS,
  flushSOSQueue,
  isTerminalSOSError,
  isAuthSOSError,
} from './sosQueue'

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('./api', () => ({
  __esModule: true,
  default: { sendSOS: jest.fn() },
}))
jest.mock('./errorReporting', () => ({ notify: jest.fn(), report: jest.fn() }))
jest.mock('./nativeModules', () => ({ loadNativeModule: () => null }))
jest.mock('expo-notifications', () => ({
  scheduleNotificationAsync: jest.fn(),
  dismissNotificationAsync: jest.fn(),
}))

const mockSendSOS = api.sendSOS as jest.MockedFunction<typeof api.sendSOS>

function apiError(statusCode?: number): Error {
  const err = new Error(`HTTP ${statusCode ?? 'network'}`) as Error & {
    statusCode?: number
  }
  err.statusCode = statusCode
  return err
}

// enqueueSOS arms a 30s retry setInterval; clear it after every test so no
// open timer keeps jest alive (CI hangs otherwise).
afterEach(async () => {
  await clearPendingSOS()
})

describe('isTerminalSOSError', () => {
  it.each([[400], [404], [422], [428]])(
    'treats 4xx (%i) as terminal — server refused, retrying cannot help',
    status => {
      expect(isTerminalSOSError(apiError(status))).toBe(true)
    }
  )

  it.each([[401], [403]])(
    'treats auth failure (%i) as retryable — re-login makes it deliverable',
    status => {
      expect(isTerminalSOSError(apiError(status))).toBe(false)
    }
  )

  it.each([[undefined], [408], [429], [500], [503]])(
    'treats %s as retryable (network / timeout / rate-limit / server fault)',
    status => {
      expect(isTerminalSOSError(apiError(status as number | undefined))).toBe(
        false
      )
    }
  )

  it('treats non-Error values as retryable rather than dropping the queue', () => {
    expect(isTerminalSOSError('boom')).toBe(false)
    expect(isTerminalSOSError(undefined)).toBe(false)
  })
})

describe('SOS queue flush', () => {
  beforeEach(async () => {
    jest.clearAllMocks()
    await AsyncStorage.clear()
  })

  it('clears the queue on successful delivery', async () => {
    await enqueueSOS()
    mockSendSOS.mockResolvedValueOnce({ id: 's1' } as never)

    const session = await flushSOSQueue()

    expect(session).toEqual({ id: 's1' })
    expect(await hasPendingSOS()).toBe(false)
  })

  it('keeps the queue on a retryable failure', async () => {
    await enqueueSOS()
    mockSendSOS.mockRejectedValueOnce(apiError(undefined))

    const session = await flushSOSQueue()

    expect(session).toBeNull()
    expect(await hasPendingSOS()).toBe(true)
  })

  it('clears the queue on a terminal failure — never retries a refused SOS', async () => {
    await enqueueSOS()
    mockSendSOS.mockRejectedValueOnce(apiError(400))

    const session = await flushSOSQueue()

    expect(session).toBeNull()
    expect(await hasPendingSOS()).toBe(false)
  })

  it('does nothing when the queue is empty', async () => {
    const session = await flushSOSQueue()
    expect(session).toBeNull()
    expect(mockSendSOS).not.toHaveBeenCalled()
  })

  it('clearPendingSOS empties the queue', async () => {
    await enqueueSOS()
    await clearPendingSOS()
    expect(await hasPendingSOS()).toBe(false)
  })
})

describe('isAuthSOSError', () => {
  it('is true only for 401/403', () => {
    expect(isAuthSOSError(apiError(401))).toBe(true)
    expect(isAuthSOSError(apiError(403))).toBe(true)
    expect(isAuthSOSError(apiError(400))).toBe(false)
    expect(isAuthSOSError(apiError(undefined))).toBe(false)
  })
})

describe('SOS queue auth failure', () => {
  beforeEach(async () => {
    jest.clearAllMocks()
    await AsyncStorage.clear()
  })

  it('keeps the queue and nudges to sign in ONCE on repeated 401s', async () => {
    await enqueueSOS()
    jest.clearAllMocks() // ignore enqueue's own "SOS not sent" notification
    mockSendSOS.mockRejectedValue(apiError(401))

    await flushSOSQueue()
    await flushSOSQueue()

    expect(await hasPendingSOS()).toBe(true) // never dropped
    // Exactly one auth nudge across both attempts.
    const authNudges = (
      Notifications.scheduleNotificationAsync as jest.Mock
    ).mock.calls.filter(c => c[0]?.content?.title === 'Finish sending your SOS')
    expect(authNudges).toHaveLength(1)
  })

  it('treats a legacy bare-timestamp queue value as pending and nudges', async () => {
    // A queued SOS from an older app version stored a bare ISO string.
    await AsyncStorage.setItem('@sos_pending', new Date().toISOString())
    mockSendSOS.mockRejectedValue(apiError(403))

    await flushSOSQueue()

    expect(await hasPendingSOS()).toBe(true)
    expect(Notifications.scheduleNotificationAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        content: expect.objectContaining({ title: 'Finish sending your SOS' }),
      })
    )
  })
})
