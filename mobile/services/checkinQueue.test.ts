/**
 * checkinQueue terminal-vs-retryable classification: a 4xx refusal is dropped
 * (never retried forever), with a local heads-up only when the session is
 * genuinely still open; network/5xx failures stay queued.
 */
import AsyncStorage from '@react-native-async-storage/async-storage'

const mockCompleteSession = jest.fn()
const mockGetSession = jest.fn()
const mockScheduleNotification = jest.fn()

jest.mock('./api', () => ({
  __esModule: true,
  default: {
    completeSession: (...a: unknown[]) => mockCompleteSession(...a),
    getSession: (...a: unknown[]) => mockGetSession(...a),
  },
}))

jest.mock('expo-notifications', () => ({
  scheduleNotificationAsync: (...a: unknown[]) =>
    mockScheduleNotification(...a),
}))

import { enqueueCheckin, flushQueue, getQueueSize } from './checkinQueue'

function apiError(statusCode: number): Error & { statusCode: number } {
  return Object.assign(new Error(`HTTP ${statusCode}`), { statusCode })
}

beforeEach(async () => {
  jest.clearAllMocks()
  await AsyncStorage.clear()
})

describe('flushQueue error classification', () => {
  it('flushes successfully and empties the queue', async () => {
    await enqueueCheckin('s1')
    mockCompleteSession.mockResolvedValueOnce({})
    expect(await flushQueue()).toBe(1)
    expect(await getQueueSize()).toBe(0)
  })

  it('keeps the item queued on a network error', async () => {
    await enqueueCheckin('s1')
    mockCompleteSession.mockRejectedValueOnce(new Error('Network request failed'))
    expect(await flushQueue()).toBe(0)
    expect(await getQueueSize()).toBe(1)
    expect(mockScheduleNotification).not.toHaveBeenCalled()
  })

  it('keeps the item queued on a 5xx', async () => {
    await enqueueCheckin('s1')
    mockCompleteSession.mockRejectedValueOnce(apiError(503))
    expect(await flushQueue()).toBe(0)
    expect(await getQueueSize()).toBe(1)
  })

  it('drops a terminal 4xx silently when the session already ended', async () => {
    await enqueueCheckin('s1')
    mockCompleteSession.mockRejectedValueOnce(apiError(400))
    mockGetSession.mockResolvedValueOnce({ status: 'completed' })
    expect(await flushQueue()).toBe(0)
    expect(await getQueueSize()).toBe(0)
    expect(mockScheduleNotification).not.toHaveBeenCalled()
  })

  it('drops a terminal 4xx and notifies when the session is still open', async () => {
    await enqueueCheckin('s1')
    mockCompleteSession.mockRejectedValueOnce(apiError(404))
    mockGetSession.mockResolvedValueOnce({ status: 'missed' })
    expect(await flushQueue()).toBe(0)
    expect(await getQueueSize()).toBe(0)
    expect(mockScheduleNotification).toHaveBeenCalledTimes(1)
  })
})
