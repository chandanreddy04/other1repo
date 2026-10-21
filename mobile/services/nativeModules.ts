/**
 * Centralized loading + health-check for native-backed modules.
 *
 * Expo modules bind their underlying native module at JS import time, so a
 * missing or unlinked native module throws during `require()` (e.g. "Cannot
 * find native module 'ExpoBattery'"). A proper build always ships every native
 * module the app declares, so any failure here means a degraded build — which
 * must never be silent. Every failure fires a Bugsnag alert (once per package;
 * `notify()` is a no-op outside production/staging).
 *
 * Use `loadNativeModule()` for optional modules accessed off the main path
 * (the loader caches, so the require + alert run at most once). Call
 * `verifyNativeModules()` once at startup to proactively probe every
 * native-backed dependency so a load failure alerts immediately rather than
 * only when the dependent feature is first exercised.
 *
 * Related: services/errorReporting.ts (notify), services/locationTracking.ts (battery
 * consumer), app/_layout.tsx (startup call site).
 */
import { notify } from './errorReporting'

// undefined = not yet attempted; null = native module unavailable.
const cache = new Map<string, unknown | null>()

/**
 * Lazily load a native-backed module, caching the result. On failure the module
 * is recorded as unavailable and a Bugsnag alert fires exactly once. Returns
 * `null` when the native module can't be loaded so callers degrade gracefully.
 */
export function loadNativeModule<T>(packageName: string, loader: () => T): T | null {
  if (!cache.has(packageName)) {
    try {
      cache.set(packageName, loader())
    } catch (err) {
      cache.set(packageName, null)
      notify(
        err instanceof Error ? err : new Error(String(err)),
        `${packageName} native module unavailable — dependent features disabled`
      )
    }
  }
  return (cache.get(packageName) as T | null) ?? null
}

/**
 * The native-backed modules this app depends on. Each entry's loader binds the
 * package's native module via `require()`; a degraded build makes the require
 * throw, which `loadNativeModule()` turns into a one-time Bugsnag alert.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
const NATIVE_MODULES: { name: string; load: () => unknown }[] = [
  { name: 'expo-secure-store', load: () => require('expo-secure-store') },
  { name: 'expo-location', load: () => require('expo-location') },
  { name: 'expo-task-manager', load: () => require('expo-task-manager') },
  { name: 'expo-background-task', load: () => require('expo-background-task') },
  { name: 'expo-notifications', load: () => require('expo-notifications') },
  { name: 'expo-device', load: () => require('expo-device') },
  { name: 'expo-contacts', load: () => require('expo-contacts') },
  { name: 'expo-local-authentication', load: () => require('expo-local-authentication') },
  { name: 'expo-sms', load: () => require('expo-sms') },
  { name: 'expo-image-picker', load: () => require('expo-image-picker') },
  { name: 'expo-image-manipulator', load: () => require('expo-image-manipulator') },
  { name: 'expo-battery', load: () => require('expo-battery') },
  {
    name: '@react-native-async-storage/async-storage',
    load: () => require('@react-native-async-storage/async-storage'),
  },
]
/* eslint-enable @typescript-eslint/no-require-imports */

/**
 * Probe every native-backed dependency once at startup. Any module that fails
 * to load fires a Bugsnag alert via `loadNativeModule()`, so a degraded build
 * is reported immediately instead of only when a feature is first used.
 */
export function verifyNativeModules(): void {
  for (const m of NATIVE_MODULES) {
    loadNativeModule(m.name, m.load)
  }
}

/** Test-only: reset the load cache between cases. */
export function __resetNativeModuleCacheForTests(): void {
  cache.clear()
}
