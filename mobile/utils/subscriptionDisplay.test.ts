import type { SubscriptionStatus } from '../store/useSubscriptionStore'
import {
  getManageRoute,
  getPlanLabel,
  getSubscriptionStatusLine,
  isSelfPaidRecurring,
  planCardMode,
  subscriptionState,
} from './subscriptionDisplay'

function makeStatus(
  over: Partial<SubscriptionStatus> = {}
): SubscriptionStatus {
  return {
    has_access: true,
    reason: 'subscription',
    expires_at: '2027-03-03T00:00:00Z',
    sessions_remaining: null,
    plan_type: 'annual',
    group_plan_id: null,
    group_plan_owner_name: null,
    source: 'stripe_web',
    cancel_at_period_end: false,
    ...over,
  }
}

describe('subscriptionState', () => {
  it('is "none" without access', () => {
    expect(subscriptionState(null)).toBe('none')
    expect(
      subscriptionState(makeStatus({ has_access: false, reason: 'none' }))
    ).toBe('none')
  })

  it('is "none" for a lapsed plan that still carries a plan_type', () => {
    expect(
      subscriptionState(
        makeStatus({ has_access: false, reason: 'none', plan_type: 'annual' })
      )
    ).toBe('none')
    expect(
      subscriptionState(
        makeStatus({
          has_access: false,
          reason: 'none',
          plan_type: 'group_monthly',
        })
      )
    ).toBe('none')
  })

  it('collapses trial / promo / referral into "individual"', () => {
    for (const reason of [
      'free_trial',
      'promotion',
      'referral_credit',
    ] as const) {
      expect(subscriptionState(makeStatus({ reason }))).toBe('individual')
    }
  })

  it('is "individual" for a self-paid individual plan', () => {
    expect(subscriptionState(makeStatus({ plan_type: 'monthly' }))).toBe(
      'individual'
    )
  })

  it('is "sponsored" for gift / comp', () => {
    expect(subscriptionState(makeStatus({ source: 'stripe_gift' }))).toBe(
      'sponsored'
    )
    expect(subscriptionState(makeStatus({ source: 'comp' }))).toBe('sponsored')
  })

  it('is "day_pass" for a day pass', () => {
    expect(subscriptionState(makeStatus({ plan_type: 'day_pass' }))).toBe(
      'day_pass'
    )
  })

  it('is "group_owner" for a self-paid group plan', () => {
    expect(subscriptionState(makeStatus({ plan_type: 'group_annual' }))).toBe(
      'group_owner'
    )
  })

  it('is "group_member" when covered by someone else\'s group plan', () => {
    expect(
      subscriptionState(
        makeStatus({ reason: 'group_plan', group_plan_owner_name: 'Sam' })
      )
    ).toBe('group_member')
  })
})

describe('getManageRoute', () => {
  it('routes an unsubscribed user to /plans', () => {
    expect(getManageRoute(null)).toBe('/plans')
    expect(
      getManageRoute(makeStatus({ has_access: false, reason: 'none' }))
    ).toBe('/plans')
  })

  it('routes every has-access reason to /subscription', () => {
    for (const reason of [
      'free_trial',
      'promotion',
      'referral_credit',
    ] as const) {
      expect(getManageRoute(makeStatus({ reason }))).toBe('/subscription')
    }
  })

  it('routes an individual self-paid subscriber to /subscription', () => {
    expect(getManageRoute(makeStatus({ plan_type: 'monthly' }))).toBe(
      '/subscription'
    )
  })

  it('routes gift / comp to /subscription (status-only)', () => {
    expect(getManageRoute(makeStatus({ source: 'stripe_gift' }))).toBe(
      '/subscription'
    )
    expect(getManageRoute(makeStatus({ source: 'comp' }))).toBe('/subscription')
  })

  it('routes a day pass to /subscription', () => {
    expect(getManageRoute(makeStatus({ plan_type: 'day_pass' }))).toBe(
      '/subscription'
    )
  })

  it('routes group owner and member to /subscription', () => {
    expect(getManageRoute(makeStatus({ plan_type: 'group_annual' }))).toBe(
      '/subscription'
    )
    expect(
      getManageRoute(
        makeStatus({ reason: 'group_plan', group_plan_owner_name: 'Sam' })
      )
    ).toBe('/subscription')
  })
})

describe('getSubscriptionStatusLine', () => {
  it('is "Not subscribed" without access (constant, never empty)', () => {
    expect(getSubscriptionStatusLine(null)).toBe('Not subscribed')
    expect(
      getSubscriptionStatusLine(
        makeStatus({ has_access: false, reason: 'none' })
      )
    ).toBe('Not subscribed')
  })

  it('shows Renews vs Cancels for a self-paid recurring sub', () => {
    expect(getSubscriptionStatusLine(makeStatus())).toContain(
      'Individual Annual'
    )
    expect(getSubscriptionStatusLine(makeStatus())).toContain('Renews')
    expect(
      getSubscriptionStatusLine(makeStatus({ cancel_at_period_end: true }))
    ).toContain('Cancels')
  })

  it('labels sponsored and comp distinctly', () => {
    expect(
      getSubscriptionStatusLine(makeStatus({ source: 'stripe_gift' }))
    ).toContain('Sponsored')
    expect(getSubscriptionStatusLine(makeStatus({ source: 'comp' }))).toContain(
      'Complimentary'
    )
  })

  it('describes group membership by owner', () => {
    expect(
      getSubscriptionStatusLine(
        makeStatus({ reason: 'group_plan', group_plan_owner_name: 'Sam' })
      )
    ).toBe('Covered by Sam')
  })

  it('names the trial', () => {
    expect(
      getSubscriptionStatusLine(makeStatus({ reason: 'free_trial' }))
    ).toBe('Free trial')
  })
})

describe('isSelfPaidRecurring', () => {
  it('is true for a self-paid recurring plan', () => {
    expect(isSelfPaidRecurring(makeStatus())).toBe(true)
    expect(isSelfPaidRecurring(makeStatus({ plan_type: 'group_annual' }))).toBe(
      true
    )
  })

  it('is false for gift, comp, day pass, and non-subscription reasons', () => {
    expect(isSelfPaidRecurring(makeStatus({ source: 'stripe_gift' }))).toBe(
      false
    )
    expect(isSelfPaidRecurring(makeStatus({ source: 'comp' }))).toBe(false)
    expect(isSelfPaidRecurring(makeStatus({ plan_type: 'day_pass' }))).toBe(
      false
    )
    expect(isSelfPaidRecurring(makeStatus({ reason: 'group_plan' }))).toBe(
      false
    )
    expect(isSelfPaidRecurring(null)).toBe(false)
  })
})

describe('getPlanLabel', () => {
  it('maps known plan types and returns null otherwise', () => {
    expect(getPlanLabel(makeStatus({ plan_type: 'monthly' }))).toBe(
      'Individual Monthly'
    )
    expect(getPlanLabel(makeStatus({ plan_type: 'group_monthly' }))).toBe(
      'Group Monthly'
    )
    expect(getPlanLabel(makeStatus({ plan_type: null }))).toBeNull()
  })
})

describe('planCardMode', () => {
  it('manages a self-paid recurring plan (individual or group owner)', () => {
    expect(planCardMode(makeStatus({ plan_type: 'monthly' }))).toBe('manage')
    expect(planCardMode(makeStatus({ plan_type: 'group_annual' }))).toBe(
      'manage'
    )
  })

  it('gives a group owner on a non-self-paid source no billing controls', () => {
    for (const source of ['admin', 'promotion', 'referral', 'comp']) {
      const status = makeStatus({ plan_type: 'group_annual', source })
      expect(subscriptionState(status)).toBe('group_owner')
      expect(isSelfPaidRecurring(status)).toBe(false)
      expect(planCardMode(status)).toBe('provided')
    }
  })

  it('offers plans for trial / promo / referral credit / day pass', () => {
    for (const reason of [
      'free_trial',
      'promotion',
      'referral_credit',
    ] as const) {
      expect(
        planCardMode(makeStatus({ reason, plan_type: null, source: null }))
      ).toBe('upgrade')
    }
    expect(planCardMode(makeStatus({ plan_type: 'day_pass' }))).toBe('upgrade')
    expect(planCardMode(null)).toBe('upgrade')
  })

  it('shows "provided for you" for other subscription sources', () => {
    for (const source of [
      'stripe_gift',
      'comp',
      'admin',
      'referral',
      'promotion',
    ]) {
      expect(planCardMode(makeStatus({ plan_type: 'monthly', source }))).toBe(
        'provided'
      )
    }
  })
})
