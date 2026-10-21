/**
 * Shared battery reader. Battery is always capturable — reading the level needs
 * no OS permission and a dying phone is safety-critical context — so both the
 * location task and the opportunistic session-gather heartbeat use this.
 *
 * Lazy-loads expo-battery via the shared native-module loader so a build missing
 * the native module degrades (and alerts Bugsnag once) instead of crashing at
 * import. Related: services/locationTracking.ts, services/sessionGather.ts.
 */

import { loadNativeModule } from './nativeModules'

export interface BatteryReading {
  level?: number
  state?: string
}

export function loadBatteryModule(): typeof import('expo-battery') | null {
  return loadNativeModule<typeof import('expo-battery')>(
    'expo-battery',
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    () => require('expo-battery')
  )
}

export async function readBattery(): Promise<BatteryReading> {
  const Battery = loadBatteryModule()
  if (!Battery) return {}
  try {
    const level = await Battery.getBatteryLevelAsync()
    const state = await Battery.getBatteryStateAsync()
    const stateMap: Record<number, string> = {
      [Battery.BatteryState.CHARGING]: 'charging',
      [Battery.BatteryState.FULL]: 'full',
      [Battery.BatteryState.UNPLUGGED]: 'unplugged',
    }
    return {
      level: level >= 0 ? level : undefined,
      state: stateMap[state] || 'unknown',
    }
  } catch {
    // benign: battery is optional context
    return {}
  }
}
