/**
 * Which state the merged account profile screen (`app/account/profile.tsx`)
 * renders — replacing the old standalone in-app editor screen and the
 * auth-flow name-capture screen (Commit 13, owner decision).
 *
 * 'required': the user has no name yet — mandatory name capture, no back
 * button, no photo picker. Driven by the `?required=1` route param (set by
 * the two callers that know a name is missing: the home screen's 428
 * handler and login's `is_new_user` branch) so the screen doesn't have to
 * wait on `user` loading to decide its own chrome. Falls back to the
 * user's own `full_name` so a user who lands on the plain `/account/profile`
 * URL with no param but genuinely has no name yet still gets the mandatory
 * flow rather than a bare editor with an empty field.
 *
 * 'edit': the normal in-app photo + name editor, Save -> router.back().
 *
 * Related: app/account/profile.tsx, app/(tabs)/index.tsx (428 redirect),
 * app/(auth)/login.tsx (is_new_user redirect).
 */
export function profileScreenMode(
  user: { full_name?: string | null } | null | undefined,
  requiredParam?: string | string[]
): 'required' | 'edit' {
  const param = Array.isArray(requiredParam) ? requiredParam[0] : requiredParam
  if (param === '1') return 'required'
  if (!user?.full_name?.trim()) return 'required'
  return 'edit'
}
