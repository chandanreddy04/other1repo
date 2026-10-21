/**
 * Shared subscription billing actions for the individual and group-owner
 * states of `app/subscription.tsx` — so the Stripe-portal handoff and the
 * native cancel/reactivate call live in one place (each state keeps its own
 * confirm copy). Mirrors the "extract repeated async logic into a hook"
 * convention.
 *
 * Related: app/subscription.tsx, store/useSubscriptionStore.ts (setAutoRenew).
 */
import { useState } from 'react'
import { Linking } from 'react-native'
import { useSubscriptionStore } from '../store/useSubscriptionStore'
import api from '../services/api'
import { notify } from '../services/errorReporting'
import toast from '../utils/toast'
import { validateStripeUrl } from '../utils/validateStripeUrl'

export function useSubscriptionActions() {
  const setAutoRenew = useSubscriptionStore(state => state.setAutoRenew)
  const [busy, setBusy] = useState(false)
  const [openingPortal, setOpeningPortal] = useState(false)

  /**
   * Cancel (renew=false) or reactivate (renew=true) at period end. `successMsg`
   * is the toast to show on success — the caller owns the confirm copy.
   */
  const setRenew = async (renew: boolean, successMsg: string) => {
    setBusy(true)
    try {
      await setAutoRenew(renew)
      toast.success(successMsg)
    } catch (error) {
      notify(
        error instanceof Error ? error : new Error(String(error)),
        renew ? 'reactivate-subscription' : 'cancel-subscription'
      )
      toast.error(
        renew
          ? 'Could not reactivate. Please try again.'
          : 'Could not cancel. Please try again.'
      )
    } finally {
      setBusy(false)
    }
  }

  /** Open the Stripe Customer Portal (change plan / payment method) externally. */
  const openPortal = async () => {
    setOpeningPortal(true)
    try {
      const { portal_url } = await api.createPortalSession()
      await Linking.openURL(validateStripeUrl(portal_url))
    } catch (error) {
      const err = error as { statusCode?: number }
      if (err.statusCode === 503) {
        toast.info('Please try again in a moment')
      } else {
        notify(
          error instanceof Error ? error : new Error(String(error)),
          'portal'
        )
        toast.error('Could not open subscription management')
      }
    } finally {
      setOpeningPortal(false)
    }
  }

  return { busy, openingPortal, setRenew, openPortal }
}
