import { create } from 'zustand'
import AsyncStorage from '@react-native-async-storage/async-storage'
import api from '../services/api'
import { STORAGE_KEYS } from '../constants'
import {
  setUser as setErrorReportingUser,
  notify,
} from '../services/errorReporting'
import notificationService from '../services/notifications'
import { clearPendingRoute } from '../utils/authRedirect'
import { useSubscriptionStore } from './useSubscriptionStore'

interface User {
  id: string
  phone_number: string
  full_name: string
  profile_photo_url?: string
  share_code?: string
  circle_invite_code?: string
  referrals_remaining?: number
  // True when the user's own phone has texted STOP to our Twilio
  // number. Surfaces the management banner + profile callout.
  sms_unsubscribed?: boolean
}

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  setUser: (user: User | null) => void
  logout: () => Promise<void>
  checkAuth: () => Promise<void>
}

export const useAuthStore = create<AuthState>(set => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  setUser: user => {
    set({ user, isAuthenticated: !!user })
    if (user) {
      setErrorReportingUser(user.id)
      // Device-local marker: the welcome carousel only shows before the
      // first-ever login on this device (flow-review D4). Best-effort.
      AsyncStorage.setItem(STORAGE_KEYS.HAS_EVER_LOGGED_IN, 'true').catch(
        () => {
          // benign: a best-effort first-login marker
        }
      )
      // A just-logged-in user may have an SOS queued from an auth failure —
      // deliver it now via the store-aware runner rather than waiting for the
      // retry tick. Dynamic import avoids a static cross-store cycle.
      import('./useSessionStore')
        .then(m => m.useSessionStore.getState().flushSOSQueue())
        .catch(err => notify(err, 'auth.flush-sos-queue'))
    }
  },

  logout: async () => {
    await api.logout()
    useSubscriptionStore.getState().reset()
    setErrorReportingUser('')
    await clearPendingRoute()
    set({ user: null, isAuthenticated: false })
  },

  checkAuth: async () => {
    set({ isLoading: true })
    try {
      await api.init()
      const user = await api.getCurrentUser()
      setErrorReportingUser(user.id)
      AsyncStorage.setItem(STORAGE_KEYS.HAS_EVER_LOGGED_IN, 'true').catch(
        () => {
          // benign: a best-effort first-login marker
        }
      )
      set({ user, isAuthenticated: true, isLoading: false })

      await notificationService.initialize()

      // Check subscription status
      await useSubscriptionStore.getState().checkSubscription()
    } catch (err) {
      // notify() itself skips the 401 of a normal expired session.
      notify(err, 'auth.check')
      set({ user: null, isAuthenticated: false, isLoading: false })
    }
  },
}))
