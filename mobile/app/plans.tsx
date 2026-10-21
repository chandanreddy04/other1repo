import { useState } from 'react'
import { SafeAreaView, Linking, View, ActivityIndicator } from 'react-native'
import { useLocalSearchParams, useRouter } from 'expo-router'
import api from '../services/api'
import { COLORS } from '../constants'
import { useRequireAuth } from '../hooks/useRequireAuth'
import { validateStripeUrl } from '../utils/validateStripeUrl'
import toast from '../utils/toast'
import { plansStep, type PlansStep } from '../utils/plansFlow'
import { OptionsView } from '../components/plans/OptionsView'
import { PickerView } from '../components/plans/PickerView'
import { ConfirmingView } from '../components/plans/ConfirmingView'
import { plansStyles as styles } from '../components/plans/styles'

// One plans page (2026-09-23 owner decision), merging the old paywall,
// subscribe and confirming screens into steps of ONE modal:
//   options    — day-pass card + "I'll subscribe" / "Ask someone I trust" /
//                "I have a code"
//   picker     — Individual/Group × monthly/annual → Stripe checkout
//   confirming — poll + AppState re-check for access to unlock, entered
//                after opening checkout and when opened with
//                ?checkout=success
//   canceled   — ?checkout=canceled → the options view with a note
//
// Plan selection lives entirely in the app on both platforms; only the
// final Stripe checkout page opens in the external browser. On iOS this
// external checkout link relies on the US external-purchase carve-out
// (post-Epic 2025), replacing the older web-only-no-CTA posture (was
// decision 4.4.3). The web checkout is the transaction boundary — the app
// never invokes a payment sheet.
// Step views live in components/plans/.

export default function PlansScreen() {
  const router = useRouter()
  // A universal link (/plans, /sub, the Stripe return) can cold-open this
  // screen signed out — gate it and replay the route after login.
  const authed = useRequireAuth()
  const params = useLocalSearchParams<{ checkout?: string }>()
  const [step, setStep] = useState<PlansStep>(() => plansStep(params))
  const [dayPassLoading, setDayPassLoading] = useState(false)

  const openCheckout = async (checkoutUrl: string) => {
    await Linking.openURL(validateStripeUrl(checkoutUrl))
    setStep('confirming')
  }

  const handleDayPass = async () => {
    setDayPassLoading(true)
    try {
      const { checkout_url } = await api.createDayPassCheckout()
      await openCheckout(checkout_url)
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to open checkout'
      )
    } finally {
      setDayPassLoading(false)
    }
  }

  if (!authed) {
    return (
      <SafeAreaView style={styles.container}>
        <View
          style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}
        >
          <ActivityIndicator size="large" color={COLORS.primary} />
        </View>
      </SafeAreaView>
    )
  }

  return (
    <SafeAreaView style={styles.container}>
      {step === 'options' || step === 'canceled' ? (
        <OptionsView
          note={
            step === 'canceled' ? 'Checkout canceled — no charge made.' : null
          }
          dayPassLoading={dayPassLoading}
          onDayPass={handleDayPass}
          onSubscribe={() => setStep('picker')}
          onClose={() => router.back()}
        />
      ) : step === 'picker' ? (
        <PickerView
          onBack={() => setStep('options')}
          openCheckout={openCheckout}
        />
      ) : (
        <ConfirmingView onBackToPlans={() => setStep('options')} />
      )}
    </SafeAreaView>
  )
}
