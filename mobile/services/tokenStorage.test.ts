import { SECURE_STORE_KEYS, STORAGE_KEYS } from '../constants'

// expo-secure-store >= 15 (SDK 54) validates keys and rejects anything outside
// [A-Za-z0-9._-] with "Invalid key provided to SecureStore". The legacy
// AsyncStorage keys ('@MadeItHome:...') contain '@' and ':', so auth tokens
// must use the dedicated SECURE_STORE_KEYS for every SecureStore call.
const SECURE_STORE_VALID = /^[A-Za-z0-9._-]+$/

describe('SecureStore auth token keys', () => {
  it('every SecureStore key is accepted by expo-secure-store', () => {
    for (const key of Object.values(SECURE_STORE_KEYS)) {
      expect(key).toMatch(SECURE_STORE_VALID)
    }
  })

  it('the legacy AsyncStorage token keys are NOT reused for SecureStore', () => {
    // They contain '@'/':' and would throw; keeping them distinct also
    // preserves the one-time migration source in tokenStorage.ts.
    expect(STORAGE_KEYS.ACCESS_TOKEN).not.toMatch(SECURE_STORE_VALID)
    expect(SECURE_STORE_KEYS.ACCESS_TOKEN).not.toBe(STORAGE_KEYS.ACCESS_TOKEN)
    expect(SECURE_STORE_KEYS.REFRESH_TOKEN).not.toBe(STORAGE_KEYS.REFRESH_TOKEN)
  })
})
