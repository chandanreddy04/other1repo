/**
 * completeSession tears down LOCAL live state (activeSession, location
 * tracking, gather, the Live Activity) only when the completed session IS
 * the store's session. The session screen can mark any live session safe by
 * id — e.g. a lingering MISSED session while a fresh SOS is the store's —
 * and must not stop the SOS's tracking/Live Activity doing so.
 */
import { useSessionStore } from './useSessionStore'
import api from '../services/api'
import locationTracking from '../services/locationTracking'
import sessionGather from '../services/sessionGather'
import liveStatusService from '../services/liveStatus'
import notificationService from '../services/notifications'
import { enqueueCheckin } from '../services/checkinQueue'
import { isNetworkFailure } from '../services/apiReporting'
import type { Session } from '../types'

jest.mock('../services/api', () => ({
  __esModule: true,
  default: {
    completeSession: jest.fn(),
    getSessions: jest.fn().mockResolvedValue([]),
  },
}))
jest.mock('../services/locationTracking', () => ({
  __esModule: true,
  default: { stopTracking: jest.fn().mockResolvedValue(undefined) },
}))
jest.mock('../services/sessionGather', () => ({
  __esModule: true,
  default: { stop: jest.fn().mockResolvedValue(undefined) },
}))
jest.mock('../services/liveStatus', () => ({
  __esModule: true,
  default: { stop: jest.fn().mockResolvedValue(undefined) },
}))
jest.mock('../services/notifications', () => ({
  __esModule: true,
  default: { cancelCheckInReminder: jest.fn().mockResolvedValue(undefined) },
}))
jest.mock('../services/checkinQueue', () => ({
  enqueueCheckin: jest.fn().mockResolvedValue(undefined),
  flushQueue: jest.fn(),
}))
jest.mock('../services/sosQueue', () => ({}))
jest.mock('../services/apiReporting', () => ({
  isNetworkFailure: jest.fn().mockReturnValue(false),
}))
jest.mock('../services/errorReporting', () => ({ notify: jest.fn() }))

const mockComplete = api.completeSession as jest.Mock
const mockNetworkFailure = isNetworkFailure as jest.Mock

function session(id: string): Session {
  return {
    id,
    user_id: 'u1',
    session_type: 'checkin',
    expected_return_time: '2026-01-01T12:00:00Z',
    location_sharing_enabled: true,
    status: 'active',
    created_at: '2026-01-01T10:00:00Z',
    updated_at: '2026-01-01T10:00:00Z',
  }
}

beforeEach(() => {
  jest.clearAllMocks()
  mockComplete.mockResolvedValue(undefined)
  mockNetworkFailure.mockReturnValue(false)
})

describe('completeSession local-state guard', () => {
  it("completing the store's session clears it and stops live state", async () => {
    useSessionStore.setState({ activeSession: session('s1') })
    await useSessionStore.getState().completeSession('s1')

    expect(mockComplete).toHaveBeenCalledWith('s1')
    expect(useSessionStore.getState().activeSession).toBeNull()
    expect(locationTracking.stopTracking).toHaveBeenCalled()
    expect(sessionGather.stop).toHaveBeenCalled()
    expect(liveStatusService.stop).toHaveBeenCalled()
    expect(notificationService.cancelCheckInReminder).toHaveBeenCalledWith(
      's1'
    )
  })

  it('completing ANOTHER session leaves the store session live', async () => {
    const sos = session('sos-1')
    useSessionStore.setState({ activeSession: sos })
    await useSessionStore.getState().completeSession('missed-1')

    expect(mockComplete).toHaveBeenCalledWith('missed-1')
    expect(useSessionStore.getState().activeSession).toBe(sos)
    expect(locationTracking.stopTracking).not.toHaveBeenCalled()
    expect(sessionGather.stop).not.toHaveBeenCalled()
    expect(liveStatusService.stop).not.toHaveBeenCalled()
    // The completed session's own reminder ladder is still cancelled.
    expect(notificationService.cancelCheckInReminder).toHaveBeenCalledWith(
      'missed-1'
    )
  })

  it('offline completion of another session queues it without touching the store session', async () => {
    const sos = session('sos-1')
    useSessionStore.setState({ activeSession: sos })
    mockComplete.mockRejectedValue(new Error('Network request failed'))
    mockNetworkFailure.mockReturnValue(true)

    await useSessionStore.getState().completeSession('missed-1')

    expect(enqueueCheckin).toHaveBeenCalledWith('missed-1')
    expect(useSessionStore.getState().activeSession).toBe(sos)
    expect(liveStatusService.stop).not.toHaveBeenCalled()
  })
})
