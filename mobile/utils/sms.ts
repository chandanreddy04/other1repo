import { Alert, Linking, Platform, Share } from 'react-native'
import toast from './toast'
import { notify } from '../services/errorReporting'

/**
 * Strip formatting so the `sms:` URL is valid. Device-contact numbers carry
 * spaces/parens/dashes/dots (e.g. "+1 (415) 555-1234"); an unsanitized number
 * makes the URL malformed, and iOS then refuses to open Messages. Keep digits
 * and a leading "+".
 */
export function sanitizePhoneForSms(phone: string): string {
  return phone.replace(/[^\d+]/g, '')
}

/**
 * Open the Messages composer to text `phone` with `message`.
 *
 * Uses `Linking.openURL` (not `canOpenURL`): `canOpenURL('sms:…')` returns
 * false for a malformed number on iOS AND for the `sms` scheme on Android 11+
 * without a manifest `<queries>` entry — and the old code then *silently* fell
 * into the OS share sheet, which popped up "randomly" on flows the user never
 * associated with sharing. `openURL` fires the implicit intent directly (works
 * on both platforms) and only throws when there is genuinely no SMS handler
 * (e.g. the Simulator / an iPad), where we offer share only on explicit confirm.
 */
export async function openSmsOrFallback(
  phone: string | undefined,
  message: string
): Promise<void> {
  if (!phone) {
    toast.error('No phone number to text for this contact')
    return
  }
  const separator = Platform.OS === 'ios' ? '&' : '?'
  const smsUrl = `sms:${sanitizePhoneForSms(
    phone
  )}${separator}body=${encodeURIComponent(message)}`
  try {
    await Linking.openURL(smsUrl)
  } catch (err) {
    // The native rejection message embeds the sms: URL — the contact's number
    // and the invite text — so report a fresh error, never `err` itself.
    notify(
      new Error('No SMS handler could open the Messages link'),
      'sms.open-messages',
      {
        platform: Platform.OS,
        cause: err instanceof Error ? err.name : typeof err,
      }
    )
    Alert.alert(
      "Couldn't open Messages",
      'Want to share the invite another way?',
      [
        { text: 'Not now', style: 'cancel' },
        { text: 'Share', onPress: () => void Share.share({ message }) },
      ]
    )
  }
}
