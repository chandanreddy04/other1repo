import { notify } from './errorReporting'
import {
  loadNativeModule,
  __resetNativeModuleCacheForTests,
} from './nativeModules'

jest.mock('./errorReporting', () => ({ notify: jest.fn() }))

const mockNotify = notify as jest.MockedFunction<typeof notify>

describe('loadNativeModule', () => {
  beforeEach(() => {
    __resetNativeModuleCacheForTests()
    mockNotify.mockClear()
  })

  it('returns the module and does not alert when the loader succeeds', () => {
    const fake = { foo: 1 }
    const result = loadNativeModule('pkg-ok', () => fake)
    expect(result).toBe(fake)
    expect(mockNotify).not.toHaveBeenCalled()
  })

  it('returns null and fires a Bugsnag alert when the native module is missing', () => {
    const result = loadNativeModule('pkg-missing', () => {
      throw new Error('Cannot find native module')
    })
    expect(result).toBeNull()
    expect(mockNotify).toHaveBeenCalledTimes(1)
    const [err, context] = mockNotify.mock.calls[0]
    expect(err).toBeInstanceOf(Error)
    expect(context).toContain('pkg-missing')
  })

  it('alerts at most once per package (cached) across repeated calls', () => {
    const loader = jest.fn(() => {
      throw new Error('missing')
    })
    loadNativeModule('pkg-once', loader)
    loadNativeModule('pkg-once', loader)
    loadNativeModule('pkg-once', loader)
    expect(loader).toHaveBeenCalledTimes(1)
    expect(mockNotify).toHaveBeenCalledTimes(1)
  })
})
