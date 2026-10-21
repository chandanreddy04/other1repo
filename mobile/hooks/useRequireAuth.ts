import { useEffect } from 'react'
import { useLocalSearchParams, usePathname, useRouter } from 'expo-router'
import { useAuthStore } from '../store/useAuthStore'
import { pathWithQuery, setPendingRoute } from '../utils/authRedirect'

/**
 * Auth gate for a screen that a universal link can cold-open (`/plans` —
 * also reached via the `/sub` lapse-SMS shim — and `/subscription`, the
 * Stripe return URLs). Same contract as `DeepLinkAcceptScreen`: wait for
 * the auth store to hydrate (redirecting on `!user` while it's still
 * loading would bounce a signed-in user to login on a cold start), then, if
 * there's still no user, stash where we were headed — query included, so
 * `/plans?checkout=success` replays onto the confirming step — and replace
 * to login, which replays it after sign-in.
 *
 * Returns true once the screen may render its signed-in content. Only for
 * routes without dynamic segments (see `pathWithQuery`).
 *
 * Related: utils/authRedirect.ts, components/DeepLinkAcceptScreen.tsx,
 * app/(auth)/login.tsx (consumeLandingRoute).
 */
export function useRequireAuth(): boolean {
  const router = useRouter()
  const pathname = usePathname()
  const params = useLocalSearchParams()
  const user = useAuthStore(state => state.user)
  const authLoading = useAuthStore(state => state.isLoading)
  const signedOut = !authLoading && !user
  const target = pathWithQuery(pathname, params)

  useEffect(() => {
    if (!signedOut) return
    // Fire-and-forget: the local write completes long before the user
    // finishes signing in, and a failed write must not block the redirect.
    void setPendingRoute(target)
    router.replace('/(auth)/login')
    // `router` is stable; re-run only when the signed-out decision or the
    // destination changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedOut, target])

  return !authLoading && !!user
}
