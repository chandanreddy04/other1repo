import { useEffect } from 'react'
import { View } from 'react-native'
import {
  ErrorBoundary as RouterErrorBoundary,
  Stack,
  type ErrorBoundaryProps,
} from 'expo-router'
import * as SplashScreen from 'expo-splash-screen'
import {
  SafeAreaProvider,
  initialWindowMetrics,
} from 'react-native-safe-area-context'
import Toast from 'react-native-toast-message'
import { useAuthStore } from '../store/useAuthStore'
import { useAppConfigStore } from '../store/useAppConfigStore'
import { notify, startErrorReporting } from '../services/errorReporting'
import { verifyNativeModules } from '../services/nativeModules'
import { toastConfig } from '../components/ui/ToastConfig'
import { EnvBanner } from '../components/EnvBanner'

// Synchronous, first: everything below (the native-module probe, the root
// ErrorBoundary, every store) reports through this client.
startErrorReporting()
// Probe every native-backed dependency at startup; any that fails to load
// (a degraded build) fires a Bugsnag alert instead of silently breaking a
// feature.
verifyNativeModules()

/**
 * Root error boundary: report the render crash, then hand it to expo-router's
 * boundary (which renders the retry UI). Without this, a crash here was
 * caught and swallowed with no report at all.
 */
export function ErrorBoundary(props: ErrorBoundaryProps) {
  useEffect(() => {
    notify(props.error, 'root-error-boundary')
  }, [props.error])
  return <RouterErrorBoundary {...props} />
}

export const unstable_settings = {
  // Ensure that reloading on `/modal` keeps a back button present.
  initialRouteName: 'index',
}

// Prevent the splash screen from auto-hiding before asset loading is complete.
SplashScreen.preventAutoHideAsync()

export default function RootLayout() {
  const checkAuth = useAuthStore(state => state.checkAuth)
  const isLoading = useAuthStore(state => state.isLoading)
  const initAppConfig = useAppConfigStore(state => state.initialize)

  useEffect(() => {
    // Kick off runtime config fetch in parallel with auth check; UI
    // gets cached values immediately and any update from the network
    // re-renders subscribed screens. Don't block the splash on it.
    void initAppConfig()
    checkAuth().finally(() => {
      SplashScreen.hideAsync()
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (isLoading) {
    return null
  }

  return (
    // SafeAreaProvider is required by useSafeAreaInsets()/SafeAreaView (used by
    // EnvBanner, the tab bar, and several banners). expo-router used to inject
    // one implicitly; SDK 54 doesn't, so without this every render throws "No
    // safe area value available", which the ErrorBoundary catches and remounts
    // — an infinite remount loop (blank screen + /config request flood).
    <SafeAreaProvider initialMetrics={initialWindowMetrics}>
      <View style={{ flex: 1 }}>
        <Stack>
          <Stack.Screen name="index" options={{ headerShown: false }} />
          <Stack.Screen name="(auth)" options={{ headerShown: false }} />
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          {/* Folder navigator (app/sessions/_layout.tsx). Its screens hide
              their headers in the NESTED stack; this hides the root Stack's
              own header for the folder entry, or it would sit above them. */}
          <Stack.Screen name="sessions" options={{ headerShown: false }} />
          {/* Folder navigator (app/account/_layout.tsx — profile/delete/
              restore). Same reasoning as "sessions" above. The (tabs)/
              account.tsx tab screen owns the bare /account URL; this
              folder has no index.tsx so there's no collision. */}
          <Stack.Screen name="account" options={{ headerShown: false }} />
          <Stack.Screen
            name="plans"
            options={{ headerShown: false, presentation: 'modal' }}
          />
          <Stack.Screen name="subscription" options={{ headerShown: false }} />
          {/* Flat redirect shim (app/sub.tsx) for the frozen lapse-SMS
              universal link /sub -> /plans — headerShown:false so the root
              header never flashes during the instant redirect. */}
          <Stack.Screen name="sub" options={{ headerShown: false }} />
          {/* Folder navigators (each owns its own _layout.tsx) — same
              reasoning as "sessions"/"account" above. */}
          <Stack.Screen name="referrals" options={{ headerShown: false }} />
          <Stack.Screen
            name="sponsorship-requests"
            options={{ headerShown: false }}
          />
          <Stack.Screen name="groups" options={{ headerShown: false }} />
          {/* Universal-link landing folders (each owns a trivial _layout.tsx;
              now redirect shims) — declared so the root header never flashes
              above them during the redirect. */}
          <Stack.Screen name="g" options={{ headerShown: false }} />
          <Stack.Screen name="r" options={{ headerShown: false }} />
          <Stack.Screen name="+not-found" options={{ headerShown: false }} />
        </Stack>
        <Toast config={toastConfig} />
        {/* Persistent non-production indicator; overlays the top, renders last so
          it's above all screens. No-op in production. */}
        <EnvBanner />
      </View>
    </SafeAreaProvider>
  )
}
