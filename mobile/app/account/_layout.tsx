import { Stack } from 'expo-router'

/**
 * `/account` sub-pages (profile/delete/restore) are their own navigator
 * boundary (frontend-conventions.md "Register nested routes" — same
 * pattern as app/sessions/_layout.tsx). The root Stack references this
 * folder, not its individual files, so profile/delete/restore don't need
 * explicit declaration in app/_layout.tsx. The root DOES declare
 * `name="account"` with `headerShown: false` — this nested Stack's own
 * options can't hide the root Stack's header for the folder entry.
 *
 * Deliberately has NO account/index.tsx: `(tabs)/account.tsx` already owns
 * the bare `/account` URL (a route group's parens are invisible to the
 * URL, so the tab's URL is `/account` too) — an index route here would be
 * ambiguous with it. Verified via `npx expo export` + the generated route
 * manifest: `/account` resolves to the tab, `/account/profile` (etc.)
 * resolve to these folder routes — no collision.
 */
export default function AccountLayout() {
  return <Stack screenOptions={{ headerShown: false }} />
}
