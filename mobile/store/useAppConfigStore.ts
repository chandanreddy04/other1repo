// Runtime app config — wraps services/runtimeConfig so React screens
// (and zustand selectors) can subscribe to changes.
//
// Lifecycle on cold start (driven from app/_layout.tsx):
//   1. initialize() reads the AsyncStorage cache and sets it as the
//      current config. Synchronous from the UI's perspective — by the
//      time the splash hides, screens have a populated value.
//   2. initialize() then fires a network fetch in the background. On
//      success the store updates; React Native re-renders any screen
//      subscribed via useAppConfig().
//   3. On fetch failure the cached value sticks. The next launch tries
//      again. Display values are stable enough that one stale render
//      doesn't matter.
//
// Non-React callers (services) read via the `getAppConfigSnapshot()`
// helper instead of the hook.

import { create } from 'zustand'

import {
  AppConfig,
  FALLBACK_CONFIG,
  fetchRuntimeConfig,
  readCachedConfig,
} from '../services/runtimeConfig'

interface AppConfigState {
  config: AppConfig
  initialize: () => Promise<void>
  refresh: () => Promise<void>
}

export const useAppConfigStore = create<AppConfigState>(set => ({
  config: FALLBACK_CONFIG,

  initialize: async () => {
    const cached = await readCachedConfig()
    if (cached) {
      set({ config: cached })
    }
    // Always refresh in the background — we don't await so the splash
    // can hide while the network call runs.
    void fetchRuntimeConfig().then(fresh => {
      if (fresh) set({ config: fresh })
    })
  },

  refresh: async () => {
    const fresh = await fetchRuntimeConfig()
    if (fresh) set({ config: fresh })
  },
}))

// Hook for React components.
export function useAppConfig(): AppConfig {
  return useAppConfigStore(state => state.config)
}

// Snapshot read for non-React contexts (services, utilities). Returns
// the current value; does NOT subscribe to changes.
export function getAppConfigSnapshot(): AppConfig {
  return useAppConfigStore.getState().config
}
