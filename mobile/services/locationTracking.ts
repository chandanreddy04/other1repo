import { Alert, Platform } from 'react-native'
import * as Location from 'expo-location'
import * as TaskManager from 'expo-task-manager'
import * as IntentLauncher from 'expo-intent-launcher'
import AsyncStorage from '@react-native-async-storage/async-storage'
import api from './api'
import { loadBatteryModule, readBattery } from './battery'
import { requestPermission as requestLocationPermission } from './permissions'
import { CHECKIN_CONFIG } from '../constants/config'
import { notify } from './errorReporting'

const LOCATION_TASK_NAME = 'made-it-home-location-tracking'
const LAST_UPDATE_KEY = '@MadeItHome:lastLocationUpdate'
const ACTIVE_SESSION_ID_KEY = '@MadeItHome:trackingSessionId'
const ESCALATED_KEY = '@MadeItHome:trackingEscalated'
// Set once we've asked the user to exempt us from Android battery
// optimization, so we prompt at most once per install (never nag).
const DOZE_PROMPTED_KEY = '@MadeItHome:dozePrompted'

const NORMAL_UPDATE_INTERVAL_MS = CHECKIN_CONFIG.LOCATION_UPDATE_INTERVAL // 5 minutes
const ESCALATED_UPDATE_INTERVAL_MS = 30000 // 30 seconds

TaskManager.defineTask(LOCATION_TASK_NAME, async ({ data, error }) => {
  if (error) {
    console.error('Location task error:', error)
    return
  }

  if (!data) return

  const { locations } = data as { locations: Location.LocationObject[] }
  if (!locations || locations.length === 0) return

  const location = locations[locations.length - 1]

  try {
    // Throttle: only send if enough time has passed since last update
    const escalated = await AsyncStorage.getItem(ESCALATED_KEY)
    const interval =
      escalated === 'true'
        ? ESCALATED_UPDATE_INTERVAL_MS
        : NORMAL_UPDATE_INTERVAL_MS
    const lastUpdateStr = await AsyncStorage.getItem(LAST_UPDATE_KEY)
    const now = Date.now()

    if (lastUpdateStr) {
      const elapsed = now - parseInt(lastUpdateStr, 10)
      if (elapsed < interval) return
    }

    const sessionId = await AsyncStorage.getItem(ACTIVE_SESSION_ID_KEY)
    if (!sessionId) return

    const battery = await readBattery()
    await api.updateLocation(
      sessionId,
      location.coords.latitude.toString(),
      location.coords.longitude.toString(),
      battery.level,
      battery.state
    )

    await AsyncStorage.setItem(LAST_UPDATE_KEY, now.toString())
  } catch (err) {
    notify(err, 'location.background-update')
  }
})

class LocationTrackingService {
  private static instance: LocationTrackingService

  private constructor() {}

  static getInstance(): LocationTrackingService {
    if (!LocationTrackingService.instance) {
      LocationTrackingService.instance = new LocationTrackingService()
    }
    return LocationTrackingService.instance
  }

  async requestPermissions(): Promise<boolean> {
    // Delegate the native request to the central module (the only place
    // request* runs); sufficiency there means Always (background) granted.
    const status = await requestLocationPermission('location')
    return status.sufficient
  }

  /**
   * A fast, non-blocking location+battery snapshot for the SOS button. Uses the
   * cached last-known position (no GPS wait) and only if permission is already
   * granted — never prompts, never blocks the panic press. Returns null when
   * there's no permission or no cached fix; the SOS still fires without it.
   */
  async getSosSnapshot(): Promise<{
    latitude: number
    longitude: number
    battery_level?: number
    battery_state?: string
  } | null> {
    try {
      const { status } = await Location.getForegroundPermissionsAsync()
      if (status !== 'granted') return null
      const pos = await Location.getLastKnownPositionAsync()
      if (!pos) return null
      const battery = await readBattery()
      return {
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
        battery_level: battery.level,
        battery_state: battery.state,
      }
    } catch {
      // benign: never block the panic button — no snapshot is fine
      return null
    }
  }

  /**
   * On Android, Doze/battery optimization can pause our background location
   * updates mid-session. If the app isn't already exempt, explain WHY (same as
   * every other permission ask) and take the user to the exemption screen —
   * at most once per install so we never nag. No-op on iOS and when already
   * exempt. Best-effort: never blocks or fails tracking.
   */
  async ensureBackgroundExecution(): Promise<void> {
    if (Platform.OS !== 'android') return
    try {
      const Battery = loadBatteryModule()
      if (!Battery) return
      const optimized = await Battery.isBatteryOptimizationEnabledAsync()
      if (!optimized) return
      if (await AsyncStorage.getItem(DOZE_PROMPTED_KEY)) return
      await AsyncStorage.setItem(DOZE_PROMPTED_KEY, 'true')
      Alert.alert(
        'Keep alerts working in the background',
        'Android pauses apps in the background to save battery, which can stop ' +
          'us from sharing your location during a session. On the next screen, ' +
          'find Made It Home and choose "Don\'t optimize" so your Circle of ' +
          'Trust can always reach you.',
        [
          { text: 'Not now', style: 'cancel' },
          {
            text: 'Open Settings',
            onPress: () =>
              void IntentLauncher.startActivityAsync(
                IntentLauncher.ActivityAction
                  .IGNORE_BATTERY_OPTIMIZATION_SETTINGS
              ),
          },
        ]
      )
    } catch {
      // benign: Best-effort — tracking still runs; the foreground service covers most
      // cases even without the exemption.
    }
  }

  async startTracking(sessionId: string): Promise<boolean> {
    const hasPermission = await this.requestPermissions()
    if (!hasPermission) return false

    // Nudge Android users to exempt us from Doze so background updates survive
    // (once per install, non-blocking).
    void this.ensureBackgroundExecution()

    await AsyncStorage.setItem(ACTIVE_SESSION_ID_KEY, sessionId)
    await AsyncStorage.removeItem(LAST_UPDATE_KEY)

    try {
      const location = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Low,
      })
      const battery = await readBattery()
      await api.updateLocation(
        sessionId,
        location.coords.latitude.toString(),
        location.coords.longitude.toString(),
        battery.level,
        battery.state
      )
      await AsyncStorage.setItem(LAST_UPDATE_KEY, Date.now().toString())
    } catch (err) {
      notify(err, 'location.initial-update')
    }

    // Start background location updates
    const isTracking = await Location.hasStartedLocationUpdatesAsync(
      LOCATION_TASK_NAME
    ).catch(
      () =>
        /* benign: throws when the task was never registered, i.e. not tracking */ false
    )

    if (!isTracking) {
      await Location.startLocationUpdatesAsync(LOCATION_TASK_NAME, {
        accuracy: Location.Accuracy.Low,
        distanceInterval: 200,
        timeInterval: 300000, // Every 5 minutes, matches API throttle
        deferredUpdatesInterval: 300000,
        showsBackgroundLocationIndicator: true,
        foregroundService: {
          notificationTitle: 'Made It Home',
          notificationBody: 'Sharing your location with your Circle of Trust',
          notificationColor: '#14B8A6',
        },
        pausesUpdatesAutomatically: true,
        activityType: Location.ActivityType.Other,
      })
    }

    return true
  }

  async escalateTracking(): Promise<void> {
    const isCurrentlyTracking = await this.isTracking()
    if (!isCurrentlyTracking) return

    // Mark as escalated so background task uses shorter throttle interval
    await AsyncStorage.setItem(ESCALATED_KEY, 'true')
    // Clear last update so the next tick sends immediately
    await AsyncStorage.removeItem(LAST_UPDATE_KEY)

    // Restart with higher accuracy and more frequent updates
    await Location.stopLocationUpdatesAsync(LOCATION_TASK_NAME)
    await Location.startLocationUpdatesAsync(LOCATION_TASK_NAME, {
      accuracy: Location.Accuracy.Balanced,
      distanceInterval: 20,
      timeInterval: 30000,
      deferredUpdatesInterval: 30000,
      showsBackgroundLocationIndicator: true,
      foregroundService: {
        notificationTitle: 'Made It Home',
        notificationBody: 'Alert triggered — sharing precise location',
        notificationColor: '#14B8A6',
      },
      pausesUpdatesAutomatically: false,
      activityType: Location.ActivityType.Other,
    })
  }

  async stopTracking(): Promise<void> {
    const isCurrentlyTracking = await Location.hasStartedLocationUpdatesAsync(
      LOCATION_TASK_NAME
    ).catch(
      () =>
        /* benign: throws when the task was never registered, i.e. not tracking */ false
    )

    if (isCurrentlyTracking) {
      await Location.stopLocationUpdatesAsync(LOCATION_TASK_NAME)
    }

    await AsyncStorage.multiRemove([
      ACTIVE_SESSION_ID_KEY,
      LAST_UPDATE_KEY,
      ESCALATED_KEY,
    ])
  }

  async isTracking(): Promise<boolean> {
    return Location.hasStartedLocationUpdatesAsync(LOCATION_TASK_NAME).catch(
      () =>
        /* benign: throws when the task was never registered, i.e. not tracking */ false
    )
  }
}

export default LocationTrackingService.getInstance()
