// `mock*` prefix: jest only lets a module factory reach out-of-scope names
// that start with "mock". Mutated per test to simulate a bundle with/without
// the key baked in.
const mockExtra: { bugsnag?: { apiKey?: string } } = {}
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: {
    expoConfig: {
      version: '1.3.0',
      get extra() {
        return mockExtra
      },
    },
  },
}))
const mockConfig = { env: 'staging' }
jest.mock('../constants/config', () => ({
  get APP_ENV() {
    return mockConfig.env
  },
}))

type BugsnagModule = typeof import('./errorReporting')
type SdkMock = { default: { start: jest.Mock; notify: jest.Mock } }

// services/errorReporting.ts keeps module-level state (started, reported), so every
// test loads it from a fresh registry — and reads the SDK mock from that SAME
// registry, otherwise the module would call a different set of jest.fn()s.
let start: jest.Mock
let notifySdk: jest.Mock

function freshModule(): BugsnagModule {
  jest.resetModules()
  const sdk = jest.requireMock<SdkMock>('@bugsnag/expo').default
  start = sdk.start
  notifySdk = sdk.notify
  return jest.requireActual<BugsnagModule>('./errorReporting')
}

type FakeEvent = {
  context?: string
  severity?: string
  metadata: Record<string, unknown>
  addMetadata: (section: string, data: unknown) => void
}
const fakeEvent = (): FakeEvent => {
  const event: FakeEvent = {
    metadata: {},
    addMetadata(section, data) {
      event.metadata[section] = data
    },
  }
  return event
}

const KEY = 'k'.repeat(32)

beforeEach(() => {
  delete mockExtra.bugsnag
})

describe('startErrorReporting', () => {
  it('starts with the key from extra.bugsnag.apiKey, the app env as release stage, and only prod/staging enabled', () => {
    mockExtra.bugsnag = { apiKey: KEY }
    const mod = freshModule()
    expect(mod.startErrorReporting()).toBe(true)
    expect(mod.isStarted()).toBe(true)
    const opts = start.mock.calls[0][0]
    expect(opts.apiKey).toBe(KEY)
    expect(opts.releaseStage).toBe('staging')
    expect(opts.enabledReleaseStages).toEqual(['production', 'staging'])
    expect(opts.appVersion).toBe('1.3.0')
    expect(opts.onError).toBe(mod.scrubEvent) // on-device phone redaction
    // idempotent
    expect(mod.startErrorReporting()).toBe(true)
    expect(start).toHaveBeenCalledTimes(1)
  })

  it('does not start without a key and says why, loudly', () => {
    const consoleError = jest
      .spyOn(console, 'error')
      .mockImplementation(() => {})
    const mod = freshModule()
    expect(mod.startErrorReporting()).toBe(false)
    expect(mod.isStarted()).toBe(false)
    expect(mod.startFailureReason()).toMatch(/MOBILE_BUGSNAG_API_KEY/)
    expect(start).not.toHaveBeenCalled()
    expect(consoleError).toHaveBeenCalled() // a staging build without a key must not be quiet
    consoleError.mockRestore()
  })

  it('surfaces a throwing SDK start instead of swallowing it', () => {
    mockExtra.bugsnag = { apiKey: KEY }
    const consoleError = jest
      .spyOn(console, 'error')
      .mockImplementation(() => {})
    const mod = freshModule()
    start.mockImplementation(() => {
      throw new Error('native module missing')
    })
    expect(mod.startErrorReporting()).toBe(false)
    expect(mod.startFailureReason()).toBe('native module missing')
    expect(consoleError).toHaveBeenCalled()
    consoleError.mockRestore()
  })
})

describe('notify', () => {
  it('sets context, severity and a metadata tab on the event', () => {
    mockExtra.bugsnag = { apiKey: KEY }
    const mod = freshModule()
    mod.startErrorReporting()
    const err = new Error('boom')
    mod.notify(err, 'request-otp', { endpoint: '/auth/request-otp' }, 'warning')
    expect(notifySdk).toHaveBeenCalledTimes(1)
    const [reportedErr, onError] = notifySdk.mock.calls[0]
    expect(reportedErr).toBe(err)
    const event = fakeEvent()
    onError(event)
    expect(event.context).toBe('request-otp')
    expect(event.severity).toBe('warning')
    expect(event.metadata.context).toEqual({ endpoint: '/auth/request-otp' })
  })

  it('wraps non-Error values', () => {
    mockExtra.bugsnag = { apiKey: KEY }
    const mod = freshModule()
    mod.startErrorReporting()
    mod.notify('string failure', 'ctx')
    expect(notifySdk.mock.calls[0][0]).toBeInstanceOf(Error)
    expect(notifySdk.mock.calls[0][0].message).toBe('string failure')
  })

  it('skips an error the API layer already reported, and reports each error once', () => {
    mockExtra.bugsnag = { apiKey: KEY }
    const mod = freshModule()
    mod.startErrorReporting()
    const err = new Error('network')
    mod.markReported(err)
    mod.notify(err, 'screen')
    expect(notifySdk).not.toHaveBeenCalled()

    const other = new Error('once')
    mod.notify(other, 'a')
    mod.notify(other, 'b')
    expect(notifySdk).toHaveBeenCalledTimes(1)
  })

  it('skips ordinary 4xx refusals but reports client-bug statuses', () => {
    mockExtra.bugsnag = { apiKey: KEY }
    const mod = freshModule()
    mod.startErrorReporting()
    mod.notify(
      Object.assign(new Error('Not authenticated'), { statusCode: 401 }),
      'auth.check'
    )
    mod.notify(
      Object.assign(new Error('Subscription required'), { statusCode: 402 }),
      'x'
    )
    mod.notify(Object.assign(new Error('Too many'), { statusCode: 429 }), 'x')
    expect(notifySdk).not.toHaveBeenCalled()
    // A payload, route or client-vs-server disagreement is a bug on one side.
    mod.notify(
      Object.assign(new Error('bad payload'), { statusCode: 422 }),
      'x'
    )
    mod.notify(Object.assign(new Error('gone'), { statusCode: 405 }), 'x')
    mod.notify(Object.assign(new Error('not found'), { statusCode: 404 }), 'x')
    mod.notify(
      Object.assign(new Error('bad request'), { statusCode: 400 }),
      'x'
    )
    expect(notifySdk).toHaveBeenCalledTimes(4)
  })

  it('echoes to the console on a keyed dev machine too (the SDK drops that stage silently)', () => {
    const consoleError = jest
      .spyOn(console, 'error')
      .mockImplementation(() => {})
    mockExtra.bugsnag = { apiKey: KEY }
    mockConfig.env = 'development'
    try {
      const mod = freshModule()
      expect(mod.startErrorReporting()).toBe(true)
      mod.notify(new Error('x'), 'ctx')
      expect(consoleError).toHaveBeenCalledWith(
        '[error-reporting:ctx]',
        expect.any(Error),
        ''
      )
    } finally {
      mockConfig.env = 'staging'
      consoleError.mockRestore()
    }
  })

  it('echoes to the console when not started (dev), never throws', () => {
    const consoleError = jest
      .spyOn(console, 'error')
      .mockImplementation(() => {})
    const mod = freshModule()
    expect(() => mod.notify(new Error('x'), 'ctx')).not.toThrow()
    expect(notifySdk).not.toHaveBeenCalled()
    expect(consoleError).toHaveBeenCalledWith(
      '[error-reporting:ctx]',
      expect.any(Error),
      ''
    )
    consoleError.mockRestore()
  })
})

describe('sendSmokeTest', () => {
  it('refuses to claim success while the device is offline', async () => {
    mockExtra.bugsnag = { apiKey: KEY }
    const mod = freshModule()
    mod.startErrorReporting()
    const netinfo = jest.requireMock<{ default: { fetch: jest.Mock } }>(
      '@react-native-community/netinfo'
    ).default
    netinfo.fetch.mockResolvedValueOnce({
      isConnected: false,
      isInternetReachable: false,
      type: 'none',
    })
    await expect(mod.sendSmokeTest()).resolves.toEqual({
      ok: false,
      detail: 'device is offline — nothing was sent',
    })
    expect(notifySdk).not.toHaveBeenCalled()
  })

  it('fails honestly when the client could not start', async () => {
    jest.spyOn(console, 'error').mockImplementation(() => {})
    const mod = freshModule()
    mod.startErrorReporting() // no key in this bundle
    await expect(mod.sendSmokeTest()).resolves.toEqual({
      ok: false,
      detail: expect.stringMatching(/MOBILE_BUGSNAG_API_KEY/),
    })
  })

  it('resolves ok when the SDK confirms delivery, and fails on a delivery error', async () => {
    mockExtra.bugsnag = { apiKey: KEY }
    const mod = freshModule()
    mod.startErrorReporting()
    notifySdk.mockImplementation((_err, onError, cb) => {
      onError(fakeEvent())
      cb(null)
    })
    await expect(mod.sendSmokeTest()).resolves.toEqual({
      ok: true,
      detail: 'accepted by Bugsnag under release stage "staging"',
    })
    notifySdk.mockImplementation((_err, _onError, cb) =>
      cb(new Error('401 Unauthorized'))
    )
    await expect(mod.sendSmokeTest()).resolves.toEqual({
      ok: false,
      detail: 'delivery failed: 401 Unauthorized',
    })
  })
})
