import { routeForNotificationType } from './notificationRouting'

// contact_left (web leave, POST /circles/{code}/leave) is a new backend
// notification `type` alongside contact_opted_out (SMS STOP cascade) — see
// docs/notifications.md O8b and backend/tests/test_web_leave_notifies_owner.py.
// New file (not an edit to notificationRouting.test.ts, which already
// asserts every contract type has a routing entry and picks this one up
// automatically once it's added to constants/notificationTypes.json).
describe('contact_left routing', () => {
  it('routes to the Circle tab, same destination as contact_opted_out', () => {
    expect(routeForNotificationType('contact_left')).toBe('/(tabs)/circle')
    expect(routeForNotificationType('contact_opted_out')).toBe(
      '/(tabs)/circle'
    )
  })
})
