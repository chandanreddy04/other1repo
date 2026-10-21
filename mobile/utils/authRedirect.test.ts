import AsyncStorage from '@react-native-async-storage/async-storage'
import {
  setPendingRoute,
  clearPendingRoute,
  consumeLandingRoute,
  pathWithQuery,
} from './authRedirect'

const KEY = '@MadeItHome:pendingRoute'

describe('authRedirect — deep-link destination preservation', () => {
  beforeEach(async () => {
    await AsyncStorage.clear()
    jest.restoreAllMocks()
  })

  it('round-trips a captured destination and reports it as pending', async () => {
    await setPendingRoute('/groups/ABC123')
    const { href, wasPending } = await consumeLandingRoute()
    expect(href).toBe('/groups/ABC123')
    expect(wasPending).toBe(true)
  })

  it('consume is one-shot: a second consume falls back to home', async () => {
    await setPendingRoute('/groups/XYZ')
    await consumeLandingRoute()
    const second = await consumeLandingRoute()
    expect(second.href).toBe('/(tabs)')
    expect(second.wasPending).toBe(false)
    // The key is cleared from storage, not just from memory.
    expect(await AsyncStorage.getItem(KEY)).toBeNull()
  })

  it('falls back to home when nothing was captured', async () => {
    const { href, wasPending } = await consumeLandingRoute()
    expect(href).toBe('/(tabs)')
    expect(wasPending).toBe(false)
  })

  it('rejects non-internal / unsafe paths (no open redirect)', async () => {
    for (const bad of [
      '//evil.com',
      'https://evil.com',
      'evil.com',
      '',
    ]) {
      await AsyncStorage.clear()
      await setPendingRoute(bad)
      const { href, wasPending } = await consumeLandingRoute()
      expect(href).toBe('/(tabs)')
      expect(wasPending).toBe(false)
    }
  })

  it('ignores a destination older than the TTL (no stale replay)', async () => {
    // Write a value timestamped 16 minutes ago (TTL is 15 min).
    const sixteenMinAgo = Date.now() - 16 * 60 * 1000
    await AsyncStorage.setItem(
      KEY,
      JSON.stringify({ path: '/c/STALE', ts: sixteenMinAgo })
    )
    const { href, wasPending } = await consumeLandingRoute()
    expect(href).toBe('/(tabs)')
    expect(wasPending).toBe(false)
    // Even when expired, the stale value is cleared on read.
    expect(await AsyncStorage.getItem(KEY)).toBeNull()
  })

  it('honors a destination within the TTL', async () => {
    const fiveMinAgo = Date.now() - 5 * 60 * 1000
    await AsyncStorage.setItem(
      KEY,
      JSON.stringify({ path: '/groups/FRESH', ts: fiveMinAgo })
    )
    const { href, wasPending } = await consumeLandingRoute()
    expect(href).toBe('/groups/FRESH')
    expect(wasPending).toBe(true)
  })

  it('clearPendingRoute discards a captured destination', async () => {
    await setPendingRoute('/c/ABC')
    await clearPendingRoute()
    const { href, wasPending } = await consumeLandingRoute()
    expect(href).toBe('/(tabs)')
    expect(wasPending).toBe(false)
  })

  it('falls back to home on a corrupt stored value', async () => {
    await AsyncStorage.setItem(KEY, 'not-json{')
    const { href, wasPending } = await consumeLandingRoute()
    expect(href).toBe('/(tabs)')
    expect(wasPending).toBe(false)
  })
})

describe('pathWithQuery — the stashed destination keeps its query', () => {
  it('keeps the Stripe-return query so /plans replays onto confirming', () => {
    expect(
      pathWithQuery('/plans', { checkout: 'success', session_id: 'cs_1' })
    ).toBe('/plans?checkout=success&session_id=cs_1')
  })

  it('is the bare pathname when there are no string params', () => {
    expect(pathWithQuery('/subscription', {})).toBe('/subscription')
    expect(pathWithQuery('/plans', { x: ['a', 'b'], y: undefined })).toBe(
      '/plans'
    )
  })

  it('encodes keys and values', () => {
    expect(pathWithQuery('/plans', { 'a b': 'c&d' })).toBe('/plans?a%20b=c%26d')
  })
})
