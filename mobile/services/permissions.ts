/**
 * Central permission authority. This is the ONLY module allowed to call the
 * native `request*PermissionsAsync` APIs — every other file must go through the
 * wrappers here (enforced by the `no-restricted-syntax` eslint ban). That
 * guarantees a native permission dialog can only ever appear from a guided,
 * foregrounded flow, never as a cold surprise.
 *
 * Two responsibilities:
 *  1. Read the LIVE, point-of-use sufficiency of each permission — not just
 *     "granted" but granted at the LEVEL a feature needs (Location =
 *     Always/background, not "When in Use").
 *  2. Request a permission (guided only), and expose the contextual camera /
 *     image-picker requests so those native calls also live here.
 *
 * The state-mapping functions (`simpleState`, `locationState`)
 * are pure and unit-tested in permissions.test.ts. `getPermissionStatuses`
 * feeds hooks/usePermissionRequirements.ts and the inline
 * components/PermissionRequirements.tsx panel.
 *
 * NOTE: onboarding's asking flow is intentionally NOT changed by this module —
 * it stays the first-run prompt and is only reused as the "Learn more" target.
 */

import * as Contacts from 'expo-contacts'
import * as Notifications from 'expo-notifications'
import * as Location from 'expo-location'
import * as ImagePicker from 'expo-image-picker'

export type PermissionKey = 'contacts' | 'notifications' | 'location'

/**
 * - `granted`       — sufficient at the required level; nothing to surface.
 * - `undetermined`  — never asked; a request WILL show the OS dialog → "Allow".
 * - `insufficient`  — granted, but at the wrong level (Location When-in-Use
 *                     with no upgrade prompt left) → Open Settings.
 * - `denied`        — refused / revoked in Settings → Open Settings.
 */
export type PermissionState =
  | 'granted'
  | 'undetermined'
  | 'insufficient'
  | 'denied'

export interface PermissionStatus {
  key: PermissionKey
  state: PermissionState
  /** True only when `state === 'granted'`. */
  sufficient: boolean
}

export interface PermissionInfo {
  label: string
  /** What we need (the ask). */
  what: string
  /** Why we need it (the safety rationale). */
  why: string
  /** Onboarding step key to deep-link for the full "Learn more" explanation. */
  onboardingStep: PermissionKey
}

export const PERMISSION_INFO: Record<PermissionKey, PermissionInfo> = {
  contacts: {
    label: 'Contacts',
    what: 'Access to your contacts',
    why: 'so you can pick trusted people for your Circle of Trust.',
    onboardingStep: 'contacts',
  },
  notifications: {
    label: 'Notifications',
    what: 'Notifications turned on',
    why: 'so we can remind you before a check-in and reach you the moment your Circle needs you.',
    onboardingStep: 'notifications',
  },
  location: {
    label: 'Location',
    what: 'Location set to Always',
    why: 'so your Circle of Trust can find you even while the app is in the background during a session.',
    onboardingStep: 'location',
  },
}

// ---------------------------------------------------------------------------
// Pure state mapping (unit-tested). Inputs mirror the shapes returned by the
// expo `get*PermissionsAsync` calls, kept loose so they're trivially testable.
// ---------------------------------------------------------------------------

export interface RawStatus {
  status: string
  canAskAgain?: boolean
}

/** Contacts / notifications: presence is sufficiency. */
export function simpleState(s: RawStatus): PermissionState {
  if (s.status === 'granted') return 'granted'
  if (s.status === 'undetermined') return 'undetermined'
  return 'denied'
}

/**
 * Location: sufficiency is background ("Always"). Foreground-only is a gap —
 * `undetermined` if the OS can still be prompted to upgrade to Always,
 * otherwise `insufficient` (Settings-only).
 */
export function locationState(fg: RawStatus, bg: RawStatus): PermissionState {
  if (bg.status === 'granted') return 'granted'
  if (fg.status === 'granted') {
    if (bg.status === 'undetermined' && bg.canAskAgain !== false) {
      return 'undetermined'
    }
    return 'insufficient'
  }
  if (fg.status === 'undetermined') return 'undetermined'
  return 'denied'
}

// ---------------------------------------------------------------------------
// Live reads (check-only — never prompt).
// ---------------------------------------------------------------------------

async function readState(key: PermissionKey): Promise<PermissionState> {
  switch (key) {
    case 'contacts':
      return simpleState(await Contacts.getPermissionsAsync())
    case 'notifications':
      return simpleState(await Notifications.getPermissionsAsync())
    case 'location': {
      const [fg, bg] = await Promise.all([
        Location.getForegroundPermissionsAsync(),
        Location.getBackgroundPermissionsAsync(),
      ])
      return locationState(fg, bg)
    }
  }
}

export async function getPermissionStatus(
  key: PermissionKey
): Promise<PermissionStatus> {
  const state = await readState(key)
  return { key, state, sufficient: state === 'granted' }
}

export async function getPermissionStatuses(
  keys: PermissionKey[]
): Promise<PermissionStatus[]> {
  return Promise.all(keys.map(getPermissionStatus))
}

// ---------------------------------------------------------------------------
// Requests — the ONLY place native request* runs. Guided callers only.
// ---------------------------------------------------------------------------

/**
 * Request a permission from a guided context, then return its fresh
 * sufficiency. Location requests foreground first, then background ("Always")
 * only if foreground was granted (iOS requires that order).
 */
export async function requestPermission(
  key: PermissionKey
): Promise<PermissionStatus> {
  switch (key) {
    case 'contacts':
      await Contacts.requestPermissionsAsync()
      break
    case 'notifications':
      await Notifications.requestPermissionsAsync()
      break
    case 'location': {
      const fg = await Location.requestForegroundPermissionsAsync()
      if (fg.status === 'granted') {
        await Location.requestBackgroundPermissionsAsync()
      }
      break
    }
  }
  return getPermissionStatus(key)
}

/** Contextual camera request (image picker "Take Photo"). */
export async function requestCameraPermission(): Promise<boolean> {
  const perm = await ImagePicker.requestCameraPermissionsAsync()
  return perm.granted
}

/** Contextual image-picker library request ("Choose from Library"). */
export async function requestImagePickerMediaPermission(): Promise<boolean> {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync()
  return perm.granted
}
