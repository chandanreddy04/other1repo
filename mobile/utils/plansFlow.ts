/**
 * Pure step-selection for `app/plans.tsx` (the merged paywall / subscribe /
 * subscribed screen — 2026-09-23 owner decision: one plans page, one
 * subscription page). Kept separate from the screen so the initial-step
 * decision is unit-testable without React Native.
 *
 * Related: app/plans.tsx, utils/subscriptionDisplay.ts (subscriptionState).
 */

export type PlansStep = 'options' | 'picker' | 'confirming' | 'canceled'

export interface PlansParams {
  checkout?: string | string[]
}

/**
 * The step `/plans` opens on, from its route params:
 *   - `?checkout=success` (the Stripe success URL) → `confirming` (poll +
 *     AppState re-check for access to unlock). In-app, the screen moves to
 *     `confirming` itself (`setStep`) right after opening checkout.
 *   - `?checkout=canceled` → `canceled` (options view with a note)
 *   - anything else → `options`
 *
 * `picker` is never an initial step — it's only reached by tapping "I'll
 * subscribe" from `options`.
 */
export function plansStep(params: PlansParams): PlansStep {
  const checkout = Array.isArray(params.checkout)
    ? params.checkout[0]
    : params.checkout
  if (checkout === 'success') return 'confirming'
  if (checkout === 'canceled') return 'canceled'
  return 'options'
}
