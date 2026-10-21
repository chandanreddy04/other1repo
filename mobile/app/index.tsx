import { useEffect, useState } from 'react'
import { Redirect, type Href } from 'expo-router'
import AsyncStorage from '@react-native-async-storage/async-storage'
import { STORAGE_KEYS } from '../constants'
import { useAuthStore } from '../store/useAuthStore'
import notificationService from '../services/notifications'
import { consumeInitialOngoingNotificationRoute } from '../services/liveStatus'

interface LaunchState {
  // Destination when a notification tap launched the app from killed state.
  notifRoute: Href | null
  // Device-local onboarding completion — an interrupted first run must
  // resume, not be silently skipped forever (flow-review D1). Per-device on
  // purpose: OS permissions are per-device, so a fresh install re-runs the
  // (fully skippable) permission steps once.
  onboarded: boolean
  // Whether any account ever logged in on this device — gates the intro
  // carousel to true first-runs only (flow-review D4).
  hasEverLoggedIn: boolean
}

export default function Index() {
  const isAuthenticated = useAuthStore(state => state.isAuthenticated)
  const [launch, setLaunch] = useState<LaunchState | null>(null)

  useEffect(() => {
    const resolve = async () => {
      const [pushRoute, ongoingRoute, onboarded, everLoggedIn] = await Promise.all([
        notificationService
          .consumeInitialNotificationRoute()
          .catch(
            () => /* benign: the service already returns null on failure */ null
          ),
        // Android's ongoing session notification is Notifee's, not
        // expo-notifications', so its launching tap is read separately.
        consumeInitialOngoingNotificationRoute().catch(
          () => /* benign: the helper already returns null on failure */ null
        ),
        AsyncStorage.getItem(STORAGE_KEYS.ONBOARDING_COMPLETED).catch(
          () =>
            /* benign: a missing flag falls through to the default route */ null
        ),
        AsyncStorage.getItem(STORAGE_KEYS.HAS_EVER_LOGGED_IN).catch(
          () =>
            /* benign: a missing flag falls through to the default route */ null
        ),
      ])
      setLaunch({
        notifRoute: pushRoute ?? ongoingRoute,
        onboarded: onboarded === 'true',
        hasEverLoggedIn: everLoggedIn === 'true',
      })
    }
    void resolve()
  }, [])

  if (!launch) {
    return null
  }

  // Declarative redirect: render the redirect rather than mounting this screen
  // and then imperatively router.replace()-ing in an effect (which unmounts
  // this screen mid-commit — a navigation churn @react-navigation 7.21.2 /
  // React 19 is sensitive to). The root layout gates on isLoading, so auth
  // state is settled by the time this renders.
  if (!isAuthenticated) {
    // Returning users skip the intro carousel and go straight to login.
    return (
      <Redirect
        href={launch.hasEverLoggedIn ? '/(auth)/login' : '/(auth)/welcome'}
      />
    )
  }
  if (!launch.onboarded && !launch.notifRoute) {
    // Interrupted/never-run onboarding resumes here instead of being
    // skipped forever. A notification launch outranks it — an alert tap
    // must land on the alert, not a permissions tour.
    return <Redirect href="/(auth)/onboarding" />
  }
  return <Redirect href={launch.notifRoute ?? '/(tabs)'} />
}
