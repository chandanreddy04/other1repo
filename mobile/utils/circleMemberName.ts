/**
 * The name to show for a Circle of Trust member.
 *
 * The backend renamed the old `contact_name` field to `nickname` and now also
 * returns a resolved `display_name` (nickname ?? the contact's own app-account
 * name). Rendering the old `contact_name` shows BLANK — that's the "contact
 * with no name" bug. Prefer display_name, then the raw nickname / account
 * name, then a neutral fallback so a card is never nameless.
 */
export function getCircleMemberDisplayName(member: {
  display_name?: string | null
  nickname?: string | null
  contact_full_name?: string | null
}): string {
  return (
    member.display_name ||
    member.nickname ||
    member.contact_full_name ||
    'Contact'
  )
}
