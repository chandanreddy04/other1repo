/**
 * Once a user has denied an OS permission, the app can't re-prompt (iOS asks
 * only once) — the only path is the system Settings app. We open the most
 * specific screen the platform allows and, when we can only reach the app's
 * general settings page, spell out the final tap so it's a no-brainer.
 *
 * - Notifications: deep-linked straight to the app's notification settings —
 *   Android via `APP_NOTIFICATION_SETTINGS`, iOS via the local
 *   notification-settings native module (Apple's public
 *   openNotificationSettingsURLString, 15.4+). Both fall back to the app page.
 * - Location: the app's own settings page (all toggles listed) — the deepest
 *   reliable target; no public per-row deep link exists.
 *
 * Used by the onboarding steps.
 */
import { Alert, Linking, Platform } from 'react-native'
import * as IntentLauncher from 'expo-intent-launcher'
import { APP_INFO } from '../constants/config'
import { openIOSNotificationSettings } from '../modules/notification-settings'

/** Open the app's notification settings directly where the platform allows. */
export async function openNotificationSettings(): Promise<void> {
  if (Platform.OS === 'android') {
    try {
      await IntentLauncher.startActivityAsync(
        IntentLauncher.ActivityAction.APP_NOTIFICATION_SETTINGS,
        { extra: { 'android.provider.extra.APP_PACKAGE': APP_INFO.BUNDLE_ID } }
      )
      return
    } catch {
      // benign: Fall through to the general app settings page.
    }
  } else if (Platform.OS === 'ios') {
    if (await openIOSNotificationSettings()) return
  }
  await Linking.openSettings()
}

export interface DeniedPrompt {
  /** e.g. "Location is off" */
  title: string
  /** Spelled-out steps ending at the exact toggle, e.g.
   *  "Open Settings, tap Location, then choose Always." */
  instructions: string
  /** 'notifications' deep-links to notification settings; default opens the
   *  app's settings page. */
  target?: 'notifications'
}

export function promptEnableInSettings({
  title,
  instructions,
  target,
}: DeniedPrompt) {
  const open =
    target === 'notifications'
      ? openNotificationSettings
      : () => Linking.openSettings()
  Alert.alert(title, instructions, [
    { text: 'Not now', style: 'cancel' },
    { text: 'Open Settings', onPress: () => void open() },
  ])
}
