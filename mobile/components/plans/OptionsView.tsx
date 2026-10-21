/**
 * /plans `options` (and `canceled`) step — day-pass card + "I'll subscribe" /
 * "Ask someone I trust" / "I have a code". Related: app/plans.tsx.
 */
import { View, Text, ScrollView, TouchableOpacity } from 'react-native'
import { useRouter } from 'expo-router'
import { LinearGradient } from 'expo-linear-gradient'
import { Ionicons } from '@expo/vector-icons'
import { COLORS } from '../../constants'
import { plansStyles as styles } from './styles'

const ROUTE_OPTIONS = [
  {
    key: 'sponsor',
    icon: 'gift' as const,
    title: 'Ask someone I trust',
    subtitle: 'They sponsor, your data stays private',
    route: '/sponsorship-requests/new' as const,
  },
  {
    key: 'code',
    icon: 'key' as const,
    title: 'I have a code',
    subtitle: 'Referral or promo code',
    route: '/referrals/new' as const,
  },
]

export function OptionsView({
  note,
  dayPassLoading,
  onDayPass,
  onSubscribe,
  onClose,
}: {
  note: string | null
  dayPassLoading: boolean
  onDayPass: () => void
  onSubscribe: () => void
  onClose: () => void
}) {
  const router = useRouter()
  return (
    <>
      <TouchableOpacity style={styles.closeButton} onPress={onClose}>
        <Ionicons name="close" size={28} color={COLORS.text} />
      </TouchableOpacity>

      {/* Scrollable: on small screens / large accessibility text the plan
          options overflow the modal sheet and were unreachable. flexGrow (not
          flex) on the content keeps it vertically centered when it fits. */}
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.header}>
          <LinearGradient
            colors={COLORS.gradients.primary}
            style={styles.iconGradient}
          >
            <Ionicons name="shield-checkmark" size={40} color={COLORS.white} />
          </LinearGradient>
          <Text style={styles.title}>Stay Safe</Text>
          <Text style={styles.subtitle}>Subscribe for peace of mind</Text>
        </View>

        {note ? (
          <View style={styles.noteBanner}>
            <Ionicons
              name="information-circle-outline"
              size={18}
              color={COLORS.textLight}
            />
            <Text style={styles.noteText}>{note}</Text>
          </View>
        ) : null}

        <View style={styles.options}>
          <TouchableOpacity
            style={styles.optionCard}
            onPress={onDayPass}
            activeOpacity={0.7}
            disabled={dayPassLoading}
          >
            <View style={styles.optionIcon}>
              <Ionicons name="moon" size={24} color={COLORS.primary} />
            </View>
            <View style={styles.optionText}>
              <Text style={styles.optionTitle}>
                {dayPassLoading ? 'Opening checkout…' : 'Just tonight'}
              </Text>
              <Text style={styles.optionSubtitle}>
                $0.99 day pass — 24 hours of protection
              </Text>
            </View>
            <Ionicons name="chevron-forward" size={20} color={COLORS.gray} />
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.optionCard}
            onPress={onSubscribe}
            activeOpacity={0.7}
          >
            <View style={styles.optionIcon}>
              <Ionicons
                name="shield-checkmark"
                size={24}
                color={COLORS.primary}
              />
            </View>
            <View style={styles.optionText}>
              <Text style={styles.optionTitle}>I'll subscribe</Text>
              <Text style={styles.optionSubtitle}>Plans from $4/mo</Text>
            </View>
            <Ionicons name="chevron-forward" size={20} color={COLORS.gray} />
          </TouchableOpacity>

          {ROUTE_OPTIONS.map(option => (
            <TouchableOpacity
              key={option.key}
              style={styles.optionCard}
              onPress={() => router.push(option.route)}
              activeOpacity={0.7}
            >
              <View style={styles.optionIcon}>
                <Ionicons name={option.icon} size={24} color={COLORS.primary} />
              </View>
              <View style={styles.optionText}>
                <Text style={styles.optionTitle}>{option.title}</Text>
                <Text style={styles.optionSubtitle}>{option.subtitle}</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={COLORS.gray} />
            </TouchableOpacity>
          ))}
        </View>

        <Text style={styles.webNote}>
          Pick your plan here — you'll complete checkout securely in your
          browser, and access unlocks in the app automatically.
        </Text>
      </ScrollView>
    </>
  )
}
