import { useMemo, useRef, useState } from 'react'
import {
  View,
  Text,
  StyleSheet,
  TextStyle,
  TouchableOpacity,
} from 'react-native'
import { useLocalSearchParams, useRouter } from 'expo-router'
import { LinearGradient } from 'expo-linear-gradient'
import { Ionicons } from '@expo/vector-icons'
import type { ComponentProps } from 'react'
import AsyncStorage from '@react-native-async-storage/async-storage'
import { Button } from '../../components/ui'
import { AuthScreenWrapper } from '../../components/AuthScreenWrapper'
import { COLORS, TYPOGRAPHY, SPACING, STORAGE_KEYS } from '../../constants'
import notificationService from '../../services/notifications'
import locationTracking from '../../services/locationTracking'
import { requestPermission } from '../../services/permissions'
import toast from '../../utils/toast'
import { promptEnableInSettings } from '../../utils/permissionSettings'
import { consumeLandingRoute } from '../../utils/authRedirect'
import { notify } from '../../services/errorReporting'

type IoniconsName = ComponentProps<typeof Ionicons>['name']
type OnboardingStep = 'contacts' | 'notifications' | 'location'

const DEFAULT_STEPS: OnboardingStep[] = [
  'contacts',
  'notifications',
  'location',
]

export default function OnboardingScreen() {
  const router = useRouter()
  // When opened from the Home "finish setup" card, `steps` names only the
  // permissions still missing — jump to those and skip already-granted ones.
  // No param = the full first-run flow.
  const { steps } = useLocalSearchParams<{ steps?: string }>()
  const [currentStepIndex, setCurrentStepIndex] = useState(0)
  const [loading, setLoading] = useState(false)

  const STEPS = useMemo<OnboardingStep[]>(() => {
    if (!steps) return DEFAULT_STEPS
    const requested = steps.split(',')
    const filtered = DEFAULT_STEPS.filter(s => requested.includes(s))
    return filtered.length > 0 ? filtered : DEFAULT_STEPS
  }, [steps])

  const currentStep = STEPS[currentStepIndex]
  const isLastStep = currentStepIndex === STEPS.length - 1

  // Terminal funnel into the app for new users. If a deep link sent them
  // through signup, return them to it; otherwise go home. Idempotent —
  // a double-tap (the contacts step's button isn't loading-gated) must
  // not double-consume the landing route and clobber the destination.
  // Returns 'pending' (honored a deep link), 'home' (normal landing), or
  // 'noop' (re-entry) so callers can decide on follow-on navigation.
  const completing = useRef(false)
  const completeOnboarding = async (): Promise<'pending' | 'home' | 'noop'> => {
    if (completing.current) return 'noop'
    completing.current = true
    await AsyncStorage.setItem(STORAGE_KEYS.ONBOARDING_COMPLETED, 'true')
    const { href, wasPending } = await consumeLandingRoute()
    router.replace(href)
    return wasPending ? 'pending' : 'home'
  }

  const handleNext = () => {
    if (isLastStep) {
      completeOnboarding()
    } else {
      setCurrentStepIndex(currentStepIndex + 1)
    }
  }

  const handleSkip = () => {
    handleNext()
  }

  const handleContactsAction = () => {
    // Navigate to contacts tab where they can add contacts — but only on
    // a normal 'home' landing. If a deep link was honored ('pending') or
    // this is a re-entrant double-tap ('noop'), don't push contacts over
    // the destination.
    completeOnboarding().then(result => {
      if (result !== 'home') return
      // Small delay to let the tab navigator mount
      setTimeout(() => router.push('/(tabs)/circle'), 100)
    })
  }

  const handleNotificationsAction = async () => {
    setLoading(true)
    try {
      // Guided request via the central module, then pick up the push token.
      const status = await requestPermission('notifications')
      if (status.sufficient) {
        await notificationService.registerAndSaveToken()
      } else {
        // Denied (or already denied — iOS won't re-prompt). Never a wall
        // (Apple 5.1.2(i)); point them at the exact toggle so re-enabling is a
        // no-brainer. The Home "finish setup" card keeps the path visible.
        promptEnableInSettings({
          title: 'Turn on notifications',
          target: 'notifications',
          instructions:
            'Open Settings → Made It Home → Notifications, and turn on Allow ' +
            'Notifications — so we can remind you before a check-in and reach ' +
            'you the moment something needs your attention.',
        })
      }
      handleNext()
    } catch (err) {
      notify(err, 'onboarding.enable-notifications')
      toast.error('Failed to enable notifications')
    } finally {
      setLoading(false)
    }
  }

  const handleLocationAction = async () => {
    setLoading(true)
    try {
      const granted = await locationTracking.requestPermissions()
      if (granted) {
        await AsyncStorage.setItem(STORAGE_KEYS.LOCATION_PERMISSION, 'granted')
      } else {
        promptEnableInSettings({
          title: 'Set location to Always',
          instructions:
            'Open Settings → Made It Home → Location, and choose Always — so ' +
            'your Circle of Trust can find you even while the app is in the ' +
            'background during a session. We only track it during a session or SOS.',
        })
      }
      handleNext()
    } catch (err) {
      notify(err, 'onboarding.enable-location')
      toast.error('Failed to enable location')
    } finally {
      setLoading(false)
    }
  }

  const stepConfig: Record<
    OnboardingStep,
    {
      icon: IoniconsName
      title: string
      description: string
      actionLabel: string
      onAction: () => void
    }
  > = {
    contacts: {
      icon: 'people',
      title: 'Add your Circle of Trust',
      description:
        'These are the people who will be notified if you miss your check-in. You can always add more later.',
      actionLabel: 'Add Contacts',
      onAction: handleContactsAction,
    },
    notifications: {
      icon: 'notifications',
      title: 'Enable notifications',
      description:
        'Get reminded when your check-in time is approaching and stay updated on your Circle of Trust.',
      actionLabel: 'Enable Notifications',
      onAction: handleNotificationsAction,
    },
    location: {
      icon: 'location',
      title: 'Share location during sessions',
      description:
        'On the next screen, choose "Always" — that lets your Circle of Trust find you even while the app is in the background during a session. Your location is captured ONLY during an active session or SOS, never any other time. It stays private and is shared with your Circle only if you miss a check-in or press SOS, and it\'s deleted 7 days after your session ends.',
      actionLabel: 'Enable Location',
      onAction: handleLocationAction,
    },
  }

  const config = stepConfig[currentStep]

  return (
    <AuthScreenWrapper centered={false}>
      {/* Progress indicator */}
      <View style={styles.progressContainer}>
        {STEPS.map((_, index) => (
          <View
            key={index}
            style={[
              styles.progressDot,
              index <= currentStepIndex && styles.progressDotActive,
            ]}
          />
        ))}
      </View>

      {/* Icon + text — fills available space, centered */}
      <View style={styles.mainContent}>
        <View style={styles.header}>
          <View style={styles.iconContainer}>
            <LinearGradient
              colors={COLORS.gradients.primary}
              style={styles.iconBackground}
            >
              <Ionicons name={config.icon} size={48} color="white" />
            </LinearGradient>
          </View>
          <Text style={styles.title}>{config.title}</Text>
          <Text style={styles.description}>{config.description}</Text>
        </View>
      </View>

      {/* Buttons — pinned to bottom */}
      <View style={styles.footer}>
        <Button
          title={config.actionLabel}
          onPress={config.onAction}
          loading={loading}
          style={styles.actionButton}
        />

        <TouchableOpacity onPress={handleSkip} style={styles.skipButton}>
          <Text style={styles.skipText}>
            {isLastStep ? 'Skip for now' : 'Skip'}
          </Text>
        </TouchableOpacity>
      </View>
    </AuthScreenWrapper>
  )
}

const styles = StyleSheet.create({
  progressContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: SPACING.sm,
    marginBottom: SPACING['2xl'],
  },
  progressDot: {
    width: 32,
    height: 4,
    borderRadius: 2,
    backgroundColor: COLORS.lightGray,
  },
  progressDotActive: {
    backgroundColor: COLORS.primary,
  },
  mainContent: {
    flex: 1,
    justifyContent: 'center',
    width: '100%',
    maxWidth: 400,
    alignSelf: 'center',
  },
  header: {
    alignItems: 'center',
  },
  footer: {
    width: '100%',
    maxWidth: 400,
    alignSelf: 'center',
    paddingBottom: SPACING.lg,
  },
  iconContainer: {
    marginBottom: SPACING.xl,
  },
  iconBackground: {
    width: 96,
    height: 96,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
  },
  title: {
    fontSize: TYPOGRAPHY.fontSize['2xl'],
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
    textAlign: 'center',
    marginBottom: SPACING.md,
  },
  description: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center',
    lineHeight: 22,
    paddingHorizontal: SPACING.md,
  },
  actionButton: {
    marginBottom: SPACING.md,
  },
  skipButton: {
    alignItems: 'center',
    paddingVertical: SPACING.md,
  },
  skipText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    fontWeight: TYPOGRAPHY.fontWeight.medium as TextStyle['fontWeight'],
  },
})
