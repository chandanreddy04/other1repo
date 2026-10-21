/**
 * Unified session data gather — a single "collect whatever is available right
 * now" step, fed by more than one engine:
 *   - the existing background LOCATION task (frequent, when Location is Always),
 *   - a foreground call (gatherNow) while the app is open,
 *   - an OS-scheduled OPPORTUNISTIC background task (expo-background-task) so a
 *     locked phone still reports battery (and last-known location) even when
 *     the location task isn't feeding updates.
 *
 * Each signal degrades INDEPENDENTLY and self-gates on live permission:
 *   - battery: always (no permission, no toggle),
 *   - location: only if the session shares it AND permission is Always
 *     (last-known position only — never prompts or waits on GPS).
 * A failure in one never blocks the other. The opportunistic task's cadence is
 * OS-decided (~15 min to hours, favouring charge/Wi-Fi) — a best-effort
 * supplement, never the primary safety signal.
 *
 * Backend note: battery-only updates (no coords) are accepted by
 * POST /sessions/{id}/locations — see app/schemas/session.py. Related:
 * services/battery.ts, services/permissions.ts, store/useSessionStore.ts.
 */

import AsyncStorage from '@react-native-async-storage/async-storage'
import * as Location from 'expo-location'
import api from './api'
import { readBattery, type BatteryReading } from './battery'
import { getPermissionStatus } from './permissions'
import { loadNativeModule } from './nativeModules'
import { notify } from './errorReporting'

const GATHER_CONFIG_KEY = '@MadeItHome:gatherConfig'
export const SESSION_GATHER_TASK = 'made-it-home-session-gather'

// Lazy-loaded so a build missing the native module degrades to the foreground
// path (and alerts Bugsnag once) instead of crashing at import.
const TaskManager = loadNativeModule<typeof import('expo-task-manager')>(
  'expo-task-manager',
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  () => require('expo-task-manager')
)
const BackgroundTask = loadNativeModule<typeof import('expo-background-task')>(
  'expo-background-task',
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  () => require('expo-background-task')
)

export interface GatherConfig {
  sessionId: string
  locationSharing: boolean
}

export interface GatherPlan {
  battery: boolean
  location: boolean
}

/**
 * Pure decision: given the session's sharing config and live permission
 * sufficiency, decide which signals to gather. Battery is always gathered (no
 * permission, no toggle); location requires BOTH the session's sharing toggle
 * AND sufficient permission.
 */
export function planGather(
  config: Pick<GatherConfig, 'locationSharing'>,
  perms: { locationSufficient: boolean }
): GatherPlan {
  return {
    battery: true,
    location: config.locationSharing && perms.locationSufficient,
  }
}

/** Collect whatever the plan allows for this session and upload it. */
export async function gatherSessionData(config: GatherConfig): Promise<void> {
  const locStatus = await getPermissionStatus('location').catch(
    () => /* benign: an unreadable permission reads as insufficient */ null
  )
  const plan = planGather(config, {
    locationSufficient: !!locStatus?.sufficient,
  })

  const battery = await readBattery().catch(
    (): BatteryReading => /* benign: battery is optional context */ ({})
  )

  let latitude: string | undefined
  let longitude: string | undefined
  if (plan.location) {
    try {
      // Last-known only — never prompts or waits on a GPS fix in the background.
      const pos = await Location.getLastKnownPositionAsync()
      if (pos) {
        latitude = pos.coords.latitude.toString()
        longitude = pos.coords.longitude.toString()
      }
    } catch {
      // benign: No cached fix — send battery alone.
    }
  }

  const hasBattery = battery.level !== undefined || battery.state !== undefined
  if (hasBattery || (latitude !== undefined && longitude !== undefined)) {
    try {
      await api.updateLocation(
        config.sessionId,
        latitude,
        longitude,
        battery.level,
        battery.state
      )
    } catch (err) {
      notify(err, 'gather.update')
    }
  }
}

// Task body must be defined at module scope so it exists when the OS wakes the
// app headlessly. sessionGather is imported by the session store on launch.
TaskManager?.defineTask(SESSION_GATHER_TASK, async () => {
  try {
    const raw = await AsyncStorage.getItem(GATHER_CONFIG_KEY)
    if (!raw) return BackgroundTask?.BackgroundTaskResult.Success
    await gatherSessionData(JSON.parse(raw) as GatherConfig)
    return BackgroundTask?.BackgroundTaskResult.Success
  } catch (err) {
    notify(err, 'gather.task')
    return BackgroundTask?.BackgroundTaskResult.Failed
  }
})

class SessionGatherService {
  /** Begin opportunistic gathering for a session (call when it becomes active). */
  async start(config: GatherConfig): Promise<void> {
    await AsyncStorage.setItem(GATHER_CONFIG_KEY, JSON.stringify(config))
    if (!BackgroundTask) return
    try {
      await BackgroundTask.registerTaskAsync(SESSION_GATHER_TASK, {
        minimumInterval: 15, // minutes — OS-scheduled floor
      })
    } catch (err) {
      notify(err, 'gather.register-task')
    }
  }

  /** Stop opportunistic gathering (call when the session ends). */
  async stop(): Promise<void> {
    await AsyncStorage.removeItem(GATHER_CONFIG_KEY)
    if (!BackgroundTask) return
    try {
      await BackgroundTask.unregisterTaskAsync(SESSION_GATHER_TASK)
    } catch {
      // benign: Not registered — nothing to clean up.
    }
  }

  /** Run one gather immediately (foreground), if a session is configured. */
  async gatherNow(): Promise<void> {
    const raw = await AsyncStorage.getItem(GATHER_CONFIG_KEY)
    if (!raw) return
    await gatherSessionData(JSON.parse(raw) as GatherConfig)
  }
}

export default new SessionGatherService()
