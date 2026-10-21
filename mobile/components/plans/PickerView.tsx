/**
 * /plans `picker` step — Individual/Group × monthly/annual → Stripe checkout
 * (`createCheckoutSession(planType)`; the parent's `openCheckout` validates
 * the URL, opens it and moves to `confirming`). Related: app/plans.tsx.
 */
import { useState } from 'react'
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { notify } from '../../services/errorReporting'
import { COLORS } from '../../constants'
import { SUBSCRIPTION_CONFIG, PlanType } from '../../constants/config'
import { useSubscriptionStore } from '../../store/useSubscriptionStore'
import api from '../../services/api'
import toast from '../../utils/toast'
import { plansStyles as styles } from './styles'

type PlanCategory = 'individual' | 'group'
type PlanPeriod = 'monthly' | 'annual'

const PLANS = {
  individual: {
    label: 'Individual',
    icon: 'person' as const,
    monthly: SUBSCRIPTION_CONFIG.MONTHLY_PRICE,
    annualPerMonth: SUBSCRIPTION_CONFIG.ANNUAL_MONTHLY_PRICE,
    annualTotal: SUBSCRIPTION_CONFIG.ANNUAL_PRICE,
    tagline: 'from $4/mo',
    features: [
      'Unlimited sessions',
      'Circle of Trust alerts',
      'Location sharing on alert',
    ],
    planTypes: {
      monthly: 'monthly' as PlanType,
      annual: 'annual' as PlanType,
    },
  },
  group: {
    label: 'Group',
    icon: 'people' as const,
    monthly: SUBSCRIPTION_CONFIG.GROUP_MONTHLY_PRICE,
    annualPerMonth: SUBSCRIPTION_CONFIG.GROUP_ANNUAL_MONTHLY_PRICE,
    annualTotal: SUBSCRIPTION_CONFIG.GROUP_ANNUAL_PRICE,
    tagline: 'from $8/mo',
    features: [
      `Up to ${SUBSCRIPTION_CONFIG.GROUP_MAX_MEMBERS} people — family, roommates, or friends`,
      'Everyone gets full access',
      'One bill, shared protection',
    ],
    planTypes: {
      monthly: 'group_monthly' as PlanType,
      annual: 'group_annual' as PlanType,
    },
  },
}

export function PickerView({
  onBack,
  openCheckout,
}: {
  onBack: () => void
  openCheckout: (checkoutUrl: string) => Promise<void>
}) {
  const { isLoading } = useSubscriptionStore()
  const [selectedCategory, setSelectedCategory] =
    useState<PlanCategory>('individual')
  const [selectedPeriod, setSelectedPeriod] = useState<PlanPeriod>('annual')
  const [purchasing, setPurchasing] = useState(false)

  const plan = PLANS[selectedCategory]
  const isAnnual = selectedPeriod === 'annual'
  const displayPrice = isAnnual ? plan.annualPerMonth : plan.monthly
  const billingDetail = isAnnual
    ? `${plan.annualTotal} billed annually`
    : `${plan.monthly} billed monthly`

  const handlePurchase = async () => {
    setPurchasing(true)
    try {
      const planType = plan.planTypes[selectedPeriod]
      const { checkout_url } = await api.createCheckoutSession(planType)
      await openCheckout(checkout_url)
    } catch (error) {
      const err = error as { statusCode?: number }
      if (err.statusCode === 409) {
        toast.info('You already have an active subscription')
      } else if (err.statusCode === 503) {
        toast.info('Please try again in a moment')
      } else {
        notify(
          error instanceof Error ? error : new Error(String(error)),
          'checkout'
        )
        toast.error('Something went wrong. Please try again.')
      }
    } finally {
      setPurchasing(false)
    }
  }

  return (
    <>
      <View style={styles.pickerHeader}>
        <TouchableOpacity onPress={onBack}>
          <Ionicons name="arrow-back" size={24} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.pickerHeaderTitle}>Subscribe</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView
        style={styles.bodyScroll}
        contentContainerStyle={styles.body}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.categoryTabs}>
          {(Object.keys(PLANS) as PlanCategory[]).map(key => {
            const p = PLANS[key]
            const isSelected = selectedCategory === key
            return (
              <TouchableOpacity
                key={key}
                style={[
                  styles.categoryTab,
                  isSelected && styles.categoryTabActive,
                ]}
                onPress={() => setSelectedCategory(key)}
                activeOpacity={0.7}
              >
                <Ionicons
                  name={p.icon}
                  size={18}
                  color={isSelected ? COLORS.primary : COLORS.textLight}
                />
                <Text
                  style={[
                    styles.categoryTabLabel,
                    isSelected && styles.categoryTabLabelActive,
                  ]}
                >
                  {p.label}
                </Text>
                <Text
                  style={[
                    styles.categoryTabPrice,
                    isSelected && styles.categoryTabPriceActive,
                  ]}
                >
                  {p.tagline}
                </Text>
              </TouchableOpacity>
            )
          })}
        </View>

        <View style={styles.toggleContainer}>
          <TouchableOpacity
            style={[
              styles.toggleOption,
              !isAnnual && styles.toggleOptionActive,
            ]}
            onPress={() => setSelectedPeriod('monthly')}
          >
            <Text
              style={[styles.toggleText, !isAnnual && styles.toggleTextActive]}
            >
              Monthly
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.toggleOption, isAnnual && styles.toggleOptionActive]}
            onPress={() => setSelectedPeriod('annual')}
          >
            <Text
              style={[styles.toggleText, isAnnual && styles.toggleTextActive]}
            >
              Annual
            </Text>
            <View style={styles.savingsBadge}>
              <Text style={styles.savingsText}>Save 20%</Text>
            </View>
          </TouchableOpacity>
        </View>

        <View style={styles.priceSection}>
          <View style={styles.priceRow}>
            <Text style={styles.priceAmount}>{displayPrice}</Text>
            <Text style={styles.pricePeriod}>/mo</Text>
          </View>
          <Text style={styles.billingDetail}>{billingDetail}</Text>
        </View>

        <View style={styles.features}>
          {plan.features.map((feature, i) => (
            <View key={i} style={styles.featureRow}>
              <Ionicons
                name="checkmark-circle"
                size={20}
                color={COLORS.primary}
              />
              <Text style={styles.featureText}>{feature}</Text>
            </View>
          ))}
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <TouchableOpacity
          style={styles.subscribeButton}
          onPress={handlePurchase}
          disabled={purchasing || isLoading}
          activeOpacity={0.9}
        >
          {purchasing ? (
            <ActivityIndicator color={COLORS.white} />
          ) : (
            <Text style={styles.subscribeText}>Subscribe Now</Text>
          )}
        </TouchableOpacity>
      </View>
    </>
  )
}
