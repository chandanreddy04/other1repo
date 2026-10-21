/**
 * Notification `type` → in-app destination. Pure module (no native imports)
 * so the mapping is unit-testable and the contract test can assert every
 * type in constants/notificationTypes.json has a deliberate entry.
 *
 * `null` means "just open the app" — a deliberate decision, not a gap.
 *
 * Related: services/notifications.ts (listener wiring),
 * constants/notificationTypes.json (the backend/mobile contract),
 * backend/tests/test_notification_types_contract.py (backend side).
 */

import type { Href } from 'expo-router'

export const NOTIFICATION_ROUTES: Record<string, Href | null> = {
  // Owner-side session lifecycle → their running session. No id in this
  // routing map's signature (type-only) — /sessions/active resolves the id
  // from the store, same as a push/Live Activity tap with no id to carry.
  session_reminder: '/sessions/active',
  session_expiring: '/sessions/active',
  session_expired: '/sessions/active',
  circle_alerted: '/sessions/active',

  // Circle members are SMS-only (owner decision) — these types no longer
  // dispatch a push to a circle member. The entries stay for contract
  // completeness (every type in notificationTypes.json needs a routing
  // entry) and route to Home as a neutral landing screen.
  alert_triggered: '/(tabs)',
  all_clear: '/(tabs)',
  alert_acknowledged: '/(tabs)',

  // Circle membership events → the Circle tab to repair the circle.
  contact_opted_out: '/(tabs)/circle',
  // A member left via the web leave page — same destination as
  // contact_opted_out (STOP), just a different trigger.
  contact_left: '/(tabs)/circle',
  contact_unreachable: '/sessions/active',
  circle_emptied: '/(tabs)/circle',
  circle_emptied_mid_session: '/(tabs)/circle',

  // Account/billing events → the Account tab (subscription + SMS management).
  account_holder_unsubscribed: '/(tabs)/account',
  account_holder_subscription_cancelled: '/(tabs)/account',
  // Group plan lapsed — land on /plans to re-establish access.
  group_plan_grace: '/plans',
  // Group or sponsored subscription lapsing or lapsed — same
  // destination as group_plan_grace: re-establish access via /plans.
  subscription_lapse: '/plans',

  // Informational only — opening the app is enough.
  data_deleted: null,
}

/**
 * Destination for a notification payload's `type`, or null when the type
 * is unknown (forward-compat: an older app receiving a new type just opens)
 * or deliberately unrouted.
 */
export function routeForNotificationType(type: unknown): Href | null {
  if (typeof type !== 'string') return null
  return NOTIFICATION_ROUTES[type] ?? null
}
