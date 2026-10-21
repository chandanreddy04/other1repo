import { requireOptionalNativeModule } from 'expo-modules-core'

// requireOptional* returns null when the native module isn't present (Android,
// Expo Go, jest), so callers must handle the fallback path themselves.
const NotificationSettings = requireOptionalNativeModule<{
  openNotificationSettings: () => Promise<boolean>
}>('NotificationSettings')

/**
 * Open the app's iOS notification settings directly (iOS 15.4+). Returns false
 * when the native module isn't available (non-iOS, Expo Go, tests) so the
 * caller can fall back to the general app-settings page.
 */
export async function openIOSNotificationSettings(): Promise<boolean> {
  if (!NotificationSettings) return false
  try {
    return await NotificationSettings.openNotificationSettings()
  } catch {
    return false
  }
}
