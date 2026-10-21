import { create } from 'zustand'
import api from '../services/api'
import type { SubscriptionStatus } from '../types'
import { notify } from '../services/errorReporting'

// Re-exported so existing importers (utils/subscriptionDisplay, screens) keep
// their `from '../store/useSubscriptionStore'` path; the canonical definition
// lives in types/index.ts (the shape the API returns).
export type { SubscriptionStatus }

interface SubscriptionState {
  status: SubscriptionStatus | null
  isLoading: boolean
  error: string | null

  checkSubscription: () => Promise<void>
  applyReferralCode: (code: string) => Promise<void>
  setAutoRenew: (renew: boolean) => Promise<void>
  recordGiftRequest: (targetPhone: string) => void
  reset: () => void
}

export const useSubscriptionStore = create<SubscriptionState>((set, get) => ({
  status: null,
  isLoading: false,
  error: null,

  checkSubscription: async () => {
    set({ isLoading: true, error: null })
    try {
      const status = await api.getSubscriptionStatus()
      set({ status, isLoading: false })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to check subscription'
      set({ error: message, isLoading: false })
    }
  },

  applyReferralCode: async (code: string) => {
    set({ isLoading: true, error: null })
    try {
      await api.applyReferralCode(code)
      await get().checkSubscription()
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to apply referral code'
      set({ error: message, isLoading: false })
      throw error
    }
  },

  setAutoRenew: async (renew: boolean) => {
    // renew=false cancels at period end; renew=true reactivates a pending
    // cancel. The endpoint returns the fresh status, so adopt it directly.
    set({ isLoading: true, error: null })
    try {
      const status = await api.updateSubscription(!renew)
      set({ status, isLoading: false })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to update subscription'
      set({ error: message, isLoading: false })
      throw error
    }
  },

  recordGiftRequest: (targetPhone: string) => {
    // Fire-and-forget analytics: records that user asked someone to gift them
    api
      .recordGiftRequest(targetPhone)
      .catch(err => notify(err, 'subscription.record-gift-request'))
  },

  reset: () => set({ status: null, isLoading: false, error: null }),
}))
