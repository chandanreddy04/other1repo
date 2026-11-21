/**
 * Clock picker on the "Start a session" screen (useCreateSession.handleTimePicked).
 *
 * Client request (2026-11-19): a picked time that is still ahead today must
 * stay TODAY, even when it is less than 30 minutes away (the old code rolled
 * it to tomorrow, so a 20-minute session started as "24h 20m"). Only a time
 * that has already passed rolls over to tomorrow. A time inside the 5-minute
 * minimum is NOT moved either: the form refuses it when the user taps Start.
 */
import React from 'react'
import { act, create } from 'react-test-renderer'

import { useCreateSession } from './useCreateSession'

jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
}))
jest.mock('../services/api', () => ({ __esModule: true, default: {} }))
jest.mock('../store/useSessionStore', () => ({
  useSessionStore: (select: (state: object) => unknown) =>
    select({ createSession: jest.fn(), isLoading: false }),
}))
jest.mock('../store/useAuthStore', () => ({
  useAuthStore: (select: (state: object) => unknown) => select({ user: null }),
}))
jest.mock('../store/useCircleStore', () => ({
  useCircleStore: (select: (state: object) => unknown) =>
    select({ circleOfTrust: null, loadCircleOfTrust: jest.fn() }),
}))
jest.mock('./useImagePicker', () => ({
  useImagePicker: () => ({
    photo: null,
    showPicker: jest.fn(),
    clearPhoto: jest.fn(),
    restorePhoto: jest.fn(),
  }),
}))
jest.mock('../utils/sessionDraft', () => ({
  consumeSessionDraft: jest.fn().mockResolvedValue(null),
  saveSessionDraft: jest.fn(),
}))
jest.mock('../utils/toast', () => ({
  __esModule: true,
  default: { error: jest.fn(), success: jest.fn() },
}))
jest.mock('../services/errorReporting', () => ({ notify: jest.fn() }))

let hook: ReturnType<typeof useCreateSession>

function Probe() {
  hook = useCreateSession()
  return null
}

const NOW = new Date('2026-07-09T22:00:00') // 10:00 PM local
const MINUTE = 60_000

/** Simulate the user picking hh:mm on the clock; return the deadline set. */
function pickClockTime(hours: number, minutes: number): Date {
  const picked = new Date(NOW)
  picked.setHours(hours, minutes, 0, 0)
  act(() => {
    hook.handleTimePicked(picked)
  })
  return hook.expectedReturnTime
}

describe('useCreateSession: picking a time on the clock', () => {
  beforeEach(async () => {
    jest.useFakeTimers()
    jest.setSystemTime(NOW)
    await act(async () => {
      create(<Probe />)
    })
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  it('a time 20 minutes ahead stays today, not tomorrow', () => {
    const deadline = pickClockTime(22, 20)
    expect(deadline.getDate()).toBe(NOW.getDate())
    expect(deadline.getTime() - NOW.getTime()).toBe(20 * MINUTE)
  })

  it('a time 25 minutes ahead stays today, not tomorrow', () => {
    const deadline = pickClockTime(22, 25)
    expect(deadline.getDate()).toBe(NOW.getDate())
    expect(deadline.getTime() - NOW.getTime()).toBe(25 * MINUTE)
  })

  it('a time 15 minutes ahead stays today (the client example)', () => {
    const deadline = pickClockTime(22, 15)
    expect(deadline.getDate()).toBe(NOW.getDate())
    expect(deadline.getTime() - NOW.getTime()).toBe(15 * MINUTE)
  })

  it('a time 3 minutes ahead is not moved to tomorrow (Start refuses it instead)', () => {
    const deadline = pickClockTime(22, 3)
    expect(deadline.getDate()).toBe(NOW.getDate())
    expect(deadline.getTime() - NOW.getTime()).toBe(3 * MINUTE)
  })

  it('a time that already passed rolls to tomorrow (by design)', () => {
    const deadline = pickClockTime(21, 0)
    expect(deadline.getDate()).toBe(NOW.getDate() + 1)
    expect(deadline.getHours()).toBe(21)
  })
})
