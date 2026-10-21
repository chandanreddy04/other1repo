import * as SecureStore from 'expo-secure-store'
import AsyncStorage from '@react-native-async-storage/async-storage'
import { STORAGE_KEYS, SECURE_STORE_KEYS } from '../constants'

const MIGRATED_KEY = '@MadeItHome:tokensMigratedToSecureStore'

// AsyncStorage keys (STORAGE_KEYS.*) are the legacy *source* of the one-time
// migration only; SecureStore keys (SECURE_STORE_KEYS.*) must be used for every
// SecureStore call — the '@'/':' in the AsyncStorage keys are rejected by
// expo-secure-store >= 15 ("Invalid key provided to SecureStore").
async function migrateFromAsyncStorage(): Promise<void> {
  const migrated = await AsyncStorage.getItem(MIGRATED_KEY)
  if (migrated === 'true') return

  const access = await AsyncStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN)
  const refresh = await AsyncStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN)

  if (access) {
    await SecureStore.setItemAsync(SECURE_STORE_KEYS.ACCESS_TOKEN, access)
    await AsyncStorage.removeItem(STORAGE_KEYS.ACCESS_TOKEN)
  }
  if (refresh) {
    await SecureStore.setItemAsync(SECURE_STORE_KEYS.REFRESH_TOKEN, refresh)
    await AsyncStorage.removeItem(STORAGE_KEYS.REFRESH_TOKEN)
  }

  await AsyncStorage.setItem(MIGRATED_KEY, 'true')
}

export async function initTokenStorage(): Promise<void> {
  await migrateFromAsyncStorage()
}

export async function getAccessToken(): Promise<string | null> {
  return SecureStore.getItemAsync(SECURE_STORE_KEYS.ACCESS_TOKEN)
}

export async function getRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(SECURE_STORE_KEYS.REFRESH_TOKEN)
}

export async function setTokens(
  accessToken: string,
  refreshToken: string
): Promise<void> {
  await SecureStore.setItemAsync(SECURE_STORE_KEYS.ACCESS_TOKEN, accessToken)
  await SecureStore.setItemAsync(SECURE_STORE_KEYS.REFRESH_TOKEN, refreshToken)
}

export async function clearTokens(): Promise<void> {
  await SecureStore.deleteItemAsync(SECURE_STORE_KEYS.ACCESS_TOKEN)
  await SecureStore.deleteItemAsync(SECURE_STORE_KEYS.REFRESH_TOKEN)
}
