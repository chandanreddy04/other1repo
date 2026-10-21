import { Platform } from 'react-native'
import { Session } from '../types'
import { COLORS } from '../constants'
import liveStatusService, {
  liveStatusContent,
  OVERDUE_FALLBACK,
} from './liveStatus'

// jest allows factory refs to vars prefixed with `mock`.
const mockStartOrUpdate = jest.fn()
const mockEndAll = jest.fn()
const mockDisplay = jest.fn()
const mockCancel = jest.fn()
const mockStopForegroundService = jest.fn()
const mockCreateChannel = jest.fn().mockResolvedValue('session-status')

// loadNativeModule just runs the loader here, so require() hits the mocks below.
jest.mock('./nativeModules', () => ({
  loadNativeModule: (_name: string, loader: () => unknown) => loader(),
}))

jest.mock('expo-live-activity', () => ({
  __esModule: true,
  startOrUpdateActivity: (...args: unknown[]) => mockStartOrUpdate(...args),
  endAllActivities: (...args: unknown[]) => mockEndAll(...args),
}))

jest.mock('@notifee/react-native', () => ({
  __esModule: true,
  default: {
    createChannel: (...a: unknown[]) => mockCreateChannel(...a),
    displayNotification: (...a: unknown[]) => mockDisplay(...a),
    cancelNotification: (...a: unknown[]) => mockCancel(...a),
    stopForegroundService: (...a: unknown[]) => mockStopForegroundService(...a),
  },
  AndroidImportance: { LOW: 2 },
  AndroidColor: { TEAL: 'teal', RED: 'red' },
}))

function makeSession(overrides: Record<string, unknown> = {}): Session {
  return {
    id: 's1',
    status: 'active',
    session_type: 'checkin',
    created_at: new Date(Date.now() - 1_800_000).toISOString(),
    expected_return_time: new Date(Date.now() + 3_600_000).toISOString(),
    ...overrides,
  } as unknown as Session
}

const session = makeSession()

const overdueSession = makeSession({
  id: 's2',
  expected_return_time: new Date(Date.now() - 60_000).toISOString(),
})

function setPlatform(os: 'ios' | 'android') {
  Object.defineProperty(Platform, 'OS', { get: () => os, configurable: true })
}

describe('liveStatusContent — brand voice, one source of truth for both OSes', () => {
  it('active before the deadline: brand title + "Check-in by" clock, not overdue', () => {
    const c = liveStatusContent(session)
    expect(c.title).toBe('Made It Home')
    expect(c.subtitle).toMatch(/^Check-in by /)
    expect(c.overdue).toBe(false)
    // Never the old developer jargon.
    expect(c.title).not.toMatch(/session/i)
    expect(c.subtitle).not.toMatch(/remaining/i)
  })

  it('active past the deadline (grace): "Time\'s up" prompt, overdue', () => {
    const c = liveStatusContent(overdueSession)
    expect(c.title).toBe('Check-in overdue')
    expect(c.overdue).toBe(true)
  })

  it('missed: mirrors the in-app "Notifying your Circle" copy', () => {
    const c = liveStatusContent(makeSession({ status: 'missed' }))
    expect(c.title).toBe('Notifying your Circle')
    expect(c.overdue).toBe(true)
  })

  it('alerted: mirrors the in-app "Your Circle has been notified" copy', () => {
    const c = liveStatusContent(makeSession({ status: 'alerted' }))
    expect(c.title).toBe('Your Circle has been notified')
    expect(c.overdue).toBe(true)
  })

  it('alerted + acknowledged: "Your alert was acknowledged" — server truth only', () => {
    const c = liveStatusContent(
      makeSession({ status: 'alerted', alert_acknowledged: true })
    )
    expect(c.title).toBe('Your alert was acknowledged')
    expect(c.overdue).toBe(true)
    // The flag NEVER upgrades the copy before the circle was notified.
    const notYet = liveStatusContent(
      makeSession({ status: 'missed', alert_acknowledged: true })
    )
    expect(notYet.title).toBe('Notifying your Circle')
  })
})

describe('liveStatusService.reconcile', () => {
  afterAll(() => setPlatform('ios'))
  beforeEach(() => jest.clearAllMocks())

  describe('iOS', () => {
    beforeEach(() => setPlatform('ios'))

    it('active session → startOrUpdate (idempotent, never a raw start)', async () => {
      await liveStatusService.reconcile(session)
      expect(mockStartOrUpdate).toHaveBeenCalledTimes(1)
      expect(mockEndAll).not.toHaveBeenCalled()
    })

    it('passes brand design-system colors + logo to the native config (no inline hex)', async () => {
      await liveStatusService.reconcile(session)
      const [state, config] = mockStartOrUpdate.mock.calls[0]
      expect(state.title).toBe('Made It Home')
      expect(state.imageName).toBe('MadeItHomeMark') // brand mark on lock screen
      expect(state.dynamicIslandImageName).toBe('MadeItHomeMark') // + Dynamic Island
      expect(config.backgroundColor).toBe(COLORS.primary) // brand teal
      expect(config.overdueBackgroundColor).toBe(COLORS.danger) // widget's danger flip
      expect(config.titleColor).toBe(COLORS.white)
      expect(config.subtitleColor).toBe(COLORS.white)
    })

    it('active session carries the pre-baked overdue copy for the on-device stale flip', async () => {
      // The widget flips to the danger treatment at staleDate (= deadline)
      // with NO JS running — the overdue words must already be in the state.
      await liveStatusService.reconcile(session)
      const [state] = mockStartOrUpdate.mock.calls[0]
      expect(state.overdue).toBe(false)
      expect(state.overdueTitle).toBe(OVERDUE_FALLBACK.title)
      expect(state.overdueSubtitle).toBe(OVERDUE_FALLBACK.subtitle)
    })

    it('progress bar gets the full session interval (start → deadline)', async () => {
      await liveStatusService.reconcile(session)
      const [state] = mockStartOrUpdate.mock.calls[0]
      expect(state.progressBar.date).toBe(
        new Date(session.expected_return_time).getTime()
      )
      expect(state.progressBar.startDate).toBe(
        new Date(session.created_at).getTime()
      )
    })

    it('overdue → state.overdue true, copy on both sides, background stays constant', async () => {
      // The danger color is the WIDGET's job now (overdue flag / stale flip
      // picks overdueBackgroundColor) — JS never swaps backgroundColor, which
      // would end+restart the activity.
      await liveStatusService.reconcile(overdueSession)
      const [state, config] = mockStartOrUpdate.mock.calls[0]
      expect(state.title).toBe('Check-in overdue')
      expect(state.overdue).toBe(true)
      expect(state.overdueTitle).toBe(state.title)
      expect(state.overdueSubtitle).toBe(state.subtitle)
      expect(config.backgroundColor).toBe(COLORS.primary)
      expect(config.overdueBackgroundColor).toBe(COLORS.danger)
    })

    it('SOS session → no countdown/progress bar, overdue treatment from the start', async () => {
      const sos = makeSession({
        session_type: 'sos',
        status: 'alerted',
        expected_return_time: new Date().toISOString(),
      })
      await liveStatusService.reconcile(sos)
      const [state] = mockStartOrUpdate.mock.calls[0]
      expect(state.progressBar).toBeUndefined()
      expect(state.overdue).toBe(true)
      expect(state.title).toBe('Your Circle has been notified')
    })

    it('no active session → endAllActivities (clears any orphan)', async () => {
      await liveStatusService.reconcile(null)
      expect(mockEndAll).toHaveBeenCalledTimes(1)
      expect(mockStartOrUpdate).not.toHaveBeenCalled()
    })

    it('repeated start stays on startOrUpdate — no id, no duplicate', async () => {
      await liveStatusService.start(session)
      await liveStatusService.start(session)
      expect(mockStartOrUpdate).toHaveBeenCalledTimes(2)
    })
  })

  describe('Android', () => {
    beforeEach(() => setPlatform('android'))

    it('active session → displays the fixed-id ongoing notification with brand teal', async () => {
      await liveStatusService.reconcile(session)
      expect(mockDisplay).toHaveBeenCalled()
      const notif = mockDisplay.mock.calls[0][0]
      expect(notif.id).toBe('active-session')
      expect(notif.title).toBe('Made It Home')
      expect(notif.android.color).toBe(COLORS.primary) // brand teal, not AndroidColor.TEAL
      expect(notif.android.largeIcon).toBeDefined() // brand mark
      // Countdown TO the deadline while active…
      expect(notif.android.chronometerDirection).toBe('down')
      // …and a bar filling left → right with true session progress.
      const { max, current } = notif.android.progress
      expect(max).toBe(
        new Date(session.expected_return_time).getTime() -
          new Date(session.created_at).getTime()
      )
      expect(current).toBeGreaterThan(0)
      expect(current).toBeLessThan(max)
    })

    it('overdue session → danger accent + chronometer counts UP ("how long overdue"), no bar', async () => {
      await liveStatusService.reconcile(overdueSession)
      const notif = mockDisplay.mock.calls[0][0]
      expect(notif.title).toBe('Check-in overdue')
      expect(notif.android.color).toBe(COLORS.danger)
      expect(notif.android.chronometerDirection).toBe('up')
      expect(notif.android.progress).toBeUndefined()
    })

    it('flips to the overdue treatment AT the deadline (one-shot timeout, not the 60s interval)', async () => {
      jest.useFakeTimers()
      try {
        const soon = makeSession({
          id: 's3',
          expected_return_time: new Date(Date.now() + 5_000).toISOString(),
        })
        await liveStatusService.start(soon)
        mockDisplay.mockClear()
        await jest.advanceTimersByTimeAsync(7_000) // past deadline, well under 60s
        expect(mockDisplay).toHaveBeenCalled()
        const notif = mockDisplay.mock.calls[0][0]
        expect(notif.android.color).toBe(COLORS.danger)
        expect(notif.android.chronometerDirection).toBe('up')
      } finally {
        jest.useRealTimers()
      }
    })

    it('no active session → cancels notification + stops foreground service', async () => {
      await liveStatusService.reconcile(null)
      expect(mockStopForegroundService).toHaveBeenCalledTimes(1)
      expect(mockCancel).toHaveBeenCalledWith('active-session')
    })

    it('repeated start does not leak timers that re-post after stop', async () => {
      jest.useFakeTimers()
      try {
        await liveStatusService.start(session)
        await liveStatusService.start(session)
        await liveStatusService.stop()
        mockDisplay.mockClear()
        jest.advanceTimersByTime(7_200_000) // 2 hours: past interval AND deadline timeout
        expect(mockDisplay).not.toHaveBeenCalled()
      } finally {
        jest.useRealTimers()
      }
    })
  })
})
