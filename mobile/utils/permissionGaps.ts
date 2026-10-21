/**
 * Pure permission-gap logic for the Home "Permissions Home" card — no React or
 * native imports, so it's directly unit-testable. The card (components/
 * PermissionsHome.tsx) reads live OS statuses and feeds them here.
 *
 * A permission is a "gap" until it's FULLY granted: not-yet-asked
 * (undetermined) and denied both count as missing.
 */

export type PermKey = 'notifications' | 'location'

export interface PermissionStatuses {
  notifications: string
  location: string
}

export const PERMISSION_LABELS: Record<PermKey, string> = {
  notifications: 'Notifications',
  location: 'Location',
}

export function permissionGaps(s: PermissionStatuses): PermKey[] {
  const gaps: PermKey[] = []
  if (s.notifications !== 'granted') gaps.push('notifications')
  if (s.location !== 'granted') gaps.push('location')
  return gaps
}

/** Card body copy. Spell out the specific permission ONLY when exactly one is
 *  pending; otherwise keep it to a count so the card stays short. */
export function describeGaps(gaps: PermKey[]): string {
  const tail = 'so we can keep you safe during a session.'
  if (gaps.length === 1) {
    return `${PERMISSION_LABELS[gaps[0]]} access is still needed ${tail}`
  }
  return `${gaps.length} permissions are still needed ${tail}`
}
