/**
 * Pure contact ↔ circle matching for the "add contacts" permission indicator —
 * no React or native imports, so it's directly unit-testable.
 *
 * The indicator's job is to nudge the user to widen contacts access ONLY when
 * that would actually help: there's still room in the circle, and nothing we
 * can currently see on the phone could grow it. See `shouldPromptContacts`.
 *
 * Match rule (agreed exactly): strip a contact number to digits; it's a valid
 * candidate only when it reduces to 10 or 11 digits; it MATCHES a circle member
 * when that digit string is CONTAINED in the circle number's digits (a national
 * "4155550101" is a substring of E164 "14155550101"). Not a last-N compare.
 *
 * Related: services/permissions.ts, hooks/useCircleScreen.ts (accessible
 * contacts + circle numbers feed this).
 */

/** Everything that isn't a digit, removed. */
export function digitsOnly(value: string): string {
  return (value || '').replace(/\D/g, '')
}

/** A contact number can only match if it reduces to 10 or 11 digits. */
export function isValidMatchNumber(value: string): boolean {
  const d = digitsOnly(value)
  return d.length === 10 || d.length === 11
}

/**
 * A single contact number MATCHES the circle when its (valid 10–11 digit)
 * digit string is contained within any circle member's digit string.
 */
export function numberMatchesCircle(
  contactNumber: string,
  circleNumbers: string[]
): boolean {
  const c = digitsOnly(contactNumber)
  if (c.length !== 10 && c.length !== 11) return false
  return circleNumbers.some(circle => digitsOnly(circle).includes(c))
}

/**
 * A contact is "addable" when it has at least one valid number and NONE of its
 * numbers already match someone in the circle — i.e. adding it would grow the
 * circle. A contact with only junk/short numbers isn't addable (can't invite).
 */
export function isAddableContact(
  contactNumbers: string[],
  circleNumbers: string[]
): boolean {
  const valid = contactNumbers.filter(isValidMatchNumber)
  if (valid.length === 0) return false
  return !valid.some(n => numberMatchesCircle(n, circleNumbers))
}

/**
 * Show the contacts permission indicator iff there is room in the circle AND no
 * accessible contact is addable — meaning the phone contacts we can see can't
 * grow the circle even though there's space, so widening access is the fix
 * (contacts denied, iOS "Limited" hiding people, or every visible contact is
 * already in the circle). A full circle, or any visible non-circle contact,
 * suppresses it.
 */
export function shouldPromptContacts(params: {
  memberCount: number
  maxMembers: number
  circleNumbers: string[]
  accessibleContacts: { phoneNumbers: string[] }[]
}): boolean {
  const { memberCount, maxMembers, circleNumbers, accessibleContacts } = params
  if (memberCount >= maxMembers) return false
  const anyAddable = accessibleContacts.some(c =>
    isAddableContact(c.phoneNumbers, circleNumbers)
  )
  return !anyAddable
}
