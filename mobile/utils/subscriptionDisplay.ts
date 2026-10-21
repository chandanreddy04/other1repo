/**
 * Presentation helpers for subscription state — the single source of truth for
 * how the Account "Manage Subscription" row and the /subscription screen
 * describe a plan and decide where a tap goes.
 *
 * One plans page, one subscription page (2026-09-23 owner decision):
 *   - no access → native /plans sheet (day pass, subscribe, sponsor, code)
 *   - has access → native /subscription screen, one of six states
 *     (`subscriptionState`): none is unreachable here (no access already
 *     routed to /plans) — individual, group_owner, group_member, sponsored,
 *     day_pass
 *
 * Related: app/(tabs)/account.tsx, app/plans.tsx, app/subscription.tsx,
 * store/useSubscriptionStore.ts.
 */
import type { SubscriptionStatus } from '../store/useSubscriptionStore'

const GROUP_PLAN_TYPES = new Set(['group_monthly', 'group_annual'])

const PLAN_LABELS: Record<string, string> = {
  monthly: 'Individual Monthly',
  annual: 'Individual Annual',
  group_monthly: 'Group Monthly',
  group_annual: 'Group Annual',
  day_pass: 'Day Pass',
}

/** A self-paid recurring Stripe plan — the only kind cancelable in-app. */
export function isSelfPaidRecurring(status: SubscriptionStatus | null): boolean {
  return (
    !!status &&
    status.reason === 'subscription' &&
    status.source === 'stripe_web' &&
    status.plan_type !== 'day_pass' &&
    status.plan_type != null
  )
}

function isGiftOrComp(status: SubscriptionStatus): boolean {
  return status.source === 'stripe_gift' || status.source === 'comp'
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString()
}

/** Human label for the plan itself, e.g. "Individual Annual". */
export function getPlanLabel(status: SubscriptionStatus | null): string | null {
  if (!status?.plan_type) return null
  return PLAN_LABELS[status.plan_type] ?? null
}

/**
 * The always-present status line shown under "Manage Subscription" (keeps the
 * row a constant height regardless of state).
 */
export function getSubscriptionStatusLine(
  status: SubscriptionStatus | null
): string {
  if (!status || !status.has_access) return 'Not subscribed'

  switch (status.reason) {
    case 'free_trial':
      return 'Free trial'
    case 'promotion':
      return 'Promotion'
    case 'referral_credit':
      return status.expires_at
        ? `Referral credit · until ${formatDate(status.expires_at)}`
        : 'Referral credit'
    case 'group_plan':
      return `Covered by ${status.group_plan_owner_name || 'your group'}`
    case 'subscription': {
      const label = getPlanLabel(status) ?? 'Active'
      if (isGiftOrComp(status)) {
        const kind = status.source === 'comp' ? 'Complimentary' : 'Sponsored'
        return status.expires_at
          ? `${kind} · active until ${formatDate(status.expires_at)}`
          : kind
      }
      if (status.plan_type === 'day_pass') {
        return status.expires_at
          ? `Day Pass · until ${formatDate(status.expires_at)}`
          : 'Day Pass'
      }
      const verb = status.cancel_at_period_end ? 'Cancels' : 'Renews'
      return status.expires_at
        ? `${label} · ${verb} ${formatDate(status.expires_at)}`
        : label
    }
    default:
      return 'Not subscribed'
  }
}

/** The six states `app/subscription.tsx` renders — one page, driven by status. */
export type SubscriptionScreenState =
  | 'none'
  | 'individual'
  | 'group_owner'
  | 'group_member'
  | 'sponsored'
  | 'day_pass'

/**
 * Which of the six `/subscription` states a status maps to.
 *
 * `free_trial` / `promotion` / `referral_credit` have access but nothing
 * plan-shaped to manage — they collapse into `individual`; `planCardMode`
 * then decides whether that state shows cancel/reactivate/portal controls,
 * a "See plans" CTA, or a status-only note.
 */
export function subscriptionState(
  status: SubscriptionStatus | null
): SubscriptionScreenState {
  if (!status || !status.has_access) return 'none'

  if (status.reason === 'group_plan') return 'group_member'

  if (status.reason === 'subscription') {
    if (status.plan_type && GROUP_PLAN_TYPES.has(status.plan_type)) {
      return 'group_owner'
    }
    if (status.plan_type === 'day_pass') return 'day_pass'
    if (isGiftOrComp(status)) return 'sponsored'
    return 'individual'
  }

  // free_trial, promotion, referral_credit.
  return 'individual'
}

/**
 * What the `/subscription` page offers below the plan card (and whether the
 * group-owner billing block renders):
 *   - `manage`   — self-paid recurring Stripe plan: cancel/reactivate + portal
 *   - `upgrade`  — day pass, free trial, promotion, referral credit (or no
 *                  access): a "See plans" CTA → /plans, since there's nothing
 *                  to manage but a plan to buy
 *   - `provided` — any other `reason === 'subscription'` source (gift, comp,
 *                  admin, promotion/referral-granted rows): status-only
 *                  "provided for you" note, no billing controls
 */
export type PlanCardMode = 'manage' | 'upgrade' | 'provided'

export function planCardMode(status: SubscriptionStatus | null): PlanCardMode {
  if (isSelfPaidRecurring(status)) return 'manage'
  if (!status || !status.has_access) return 'upgrade'
  if (status.reason === 'subscription' && status.plan_type !== 'day_pass') {
    return 'provided'
  }
  return 'upgrade'
}

export type ManageRoute = '/plans' | '/subscription'

/** Where the "Manage Subscription" row navigates for the given status. */
export function getManageRoute(status: SubscriptionStatus | null): ManageRoute {
  return subscriptionState(status) === 'none' ? '/plans' : '/subscription'
}
