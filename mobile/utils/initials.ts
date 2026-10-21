/**
 * First letter of a name, uppercased — for avatar fallbacks. Returns '?' for a
 * null/empty/whitespace name so a missing name never crashes the render.
 *
 * Fixes a "Cannot read property 'charAt' of null" crash: a circle contact added
 * by phone only (no saved name) has a null name, and `name.charAt(0)` threw
 * when the card rendered after returning from the native SMS invite.
 */
export function getInitial(name?: string | null): string {
  const trimmed = name?.trim()
  return trimmed ? trimmed.charAt(0).toUpperCase() : '?'
}
