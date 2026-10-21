import contract from '../constants/notificationTypes.json'
import {
  NOTIFICATION_ROUTES,
  routeForNotificationType,
} from './notificationRouting'

// The routing map and the backend/mobile type contract must not drift:
// the original handlers checked type names the backend never emitted, so
// tap-routing and escalation were silently dead. The backend side of this
// contract lives in backend/tests/test_notification_types_contract.py.
describe('notification type contract (mobile side)', () => {
  const contractTypes = [...contract.backend, ...contract.local].sort()

  it('every contract type has a deliberate routing entry', () => {
    expect(Object.keys(NOTIFICATION_ROUTES).sort()).toEqual(contractTypes)
  })

  it('routes owner session events to the active session', () => {
    expect(routeForNotificationType('session_expiring')).toBe(
      '/sessions/active'
    )
    expect(routeForNotificationType('session_expired')).toBe(
      '/sessions/active'
    )
    expect(routeForNotificationType('session_reminder')).toBe(
      '/sessions/active'
    )
  })

  it('routes circle membership events to the Circle tab', () => {
    expect(routeForNotificationType('contact_opted_out')).toBe(
      '/(tabs)/circle'
    )
    expect(routeForNotificationType('circle_emptied')).toBe('/(tabs)/circle')
    expect(routeForNotificationType('circle_emptied_mid_session')).toBe(
      '/(tabs)/circle'
    )
  })

  it('routes account/billing events to the Account tab', () => {
    expect(routeForNotificationType('account_holder_unsubscribed')).toBe(
      '/(tabs)/account'
    )
    expect(
      routeForNotificationType('account_holder_subscription_cancelled')
    ).toBe('/(tabs)/account')
  })

  it('routes circle-member-facing types to Home (SMS-only, owner decision)', () => {
    // Circle members are SMS-only now — these types no longer dispatch a
    // push to a circle member, but the routing entry stays for contract
    // completeness and routes to Home (server-truth status).
    expect(routeForNotificationType('alert_triggered')).toBe('/(tabs)')
    expect(routeForNotificationType('all_clear')).toBe('/(tabs)')
    expect(routeForNotificationType('alert_acknowledged')).toBe('/(tabs)')
  })

  it('returns null for unknown or missing types (forward-compat)', () => {
    expect(routeForNotificationType('some_future_type')).toBeNull()
    expect(routeForNotificationType(undefined)).toBeNull()
    expect(routeForNotificationType(42)).toBeNull()
  })
})
