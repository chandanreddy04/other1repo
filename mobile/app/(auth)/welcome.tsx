import { useState, useRef } from 'react'
import {
  View,
  Text,
  StyleSheet,
  TextStyle,
  Dimensions,
  FlatList,
  ViewToken,
  Image,
} from 'react-native'
import { useRouter } from 'expo-router'
import { LinearGradient } from 'expo-linear-gradient'
import { Ionicons } from '@expo/vector-icons'
import { Button } from '../../components/ui'
import { AuthScreenWrapper } from '../../components/AuthScreenWrapper'
import { COLORS, TYPOGRAPHY, SPACING } from '../../constants'

const { width: SCREEN_WIDTH } = Dimensions.get('window')

const PAGES = [
  {
    key: 'identity',
    icon: 'shield-checkmark' as const,
    title: 'Made It Home',
    tagline: 'Privacy-first personal safety',
    body: 'Your location, your data, your control. We built this so you can feel safe without giving up your privacy.',
  },
  {
    key: 'how-it-works',
    icon: 'bulb-outline' as const,
    title: 'How It Works',
    tagline: null,
    steps: [
      { number: '1', text: 'Set a check-in time' },
      {
        number: '2',
        text: "If you miss your check-in, your Circle of Trust is alerted",
      },
      {
        number: '3',
        text: "That's it - no tracking, no social features, no surveillance",
      },
    ],
  },
  {
    key: 'data-promise',
    icon: 'lock-closed-outline' as const,
    title: 'Our Promise',
    tagline: null,
    promises: [
      {
        icon: 'location-outline' as const,
        text: 'Location is only captured during active sessions',
      },
      {
        icon: 'trash-outline' as const,
        text: 'Session data is deleted 7 days after sessions end',
      },
      {
        icon: 'eye-off-outline' as const,
        text: 'We never sell or share your information',
      },
      {
        icon: 'people-outline' as const,
        text: 'Your contacts only see what you choose to share',
      },
    ],
  },
]

export default function WelcomeScreen() {
  const router = useRouter()
  const [currentPage, setCurrentPage] = useState(0)
  const flatListRef = useRef<FlatList>(null)

  const isLastPage = currentPage === PAGES.length - 1

  const handleNext = () => {
    if (isLastPage) {
      router.replace('/(auth)/login')
    } else {
      flatListRef.current?.scrollToIndex({
        index: currentPage + 1,
        animated: true,
      })
    }
  }

  const onViewableItemsChanged = useRef(
    ({ viewableItems }: { viewableItems: ViewToken[] }) => {
      if (viewableItems.length > 0 && viewableItems[0].index != null) {
        setCurrentPage(viewableItems[0].index)
      }
    }
  ).current

  const renderPage = ({ item }: { item: (typeof PAGES)[number] }) => (
    <View style={styles.page}>
      <View style={styles.pageContent}>
        {item.key === 'identity' ? (
          <Image
            // eslint-disable-next-line @typescript-eslint/no-require-imports
            source={require('../../assets/images/icon.png')}
            style={styles.logoImage}
          />
        ) : (
          <LinearGradient
            colors={COLORS.gradients.primary}
            style={styles.iconCircle}
          >
            <Ionicons name={item.icon} size={40} color={COLORS.white} />
          </LinearGradient>
        )}

        <Text style={styles.title}>{item.title}</Text>

        {item.tagline && <Text style={styles.tagline}>{item.tagline}</Text>}

        {'body' in item && item.body && (
          <Text style={styles.body}>{item.body}</Text>
        )}

        {'steps' in item && item.steps && (
          <View style={styles.stepsList}>
            {item.steps.map(step => (
              <View key={step.number} style={styles.stepRow}>
                <View style={styles.stepNumber}>
                  <Text style={styles.stepNumberText}>{step.number}</Text>
                </View>
                <Text style={styles.stepText}>{step.text}</Text>
              </View>
            ))}
          </View>
        )}

        {'promises' in item && item.promises && (
          <View style={styles.promisesList}>
            {item.promises.map(promise => (
              <View key={promise.text} style={styles.promiseRow}>
                <Ionicons
                  name={promise.icon}
                  size={22}
                  color={COLORS.primary}
                />
                <Text style={styles.promiseText}>{promise.text}</Text>
              </View>
            ))}
          </View>
        )}
      </View>
    </View>
  )

  return (
    <AuthScreenWrapper centered={false}>
      <View style={styles.container}>
        <FlatList
          ref={flatListRef}
          data={PAGES}
          renderItem={renderPage}
          keyExtractor={item => item.key}
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          onViewableItemsChanged={onViewableItemsChanged}
          viewabilityConfig={{ viewAreaCoveragePercentThreshold: 50 }}
          scrollEventThrottle={16}
          bounces={false}
        />

        <View style={styles.footer}>
          <View style={styles.dots}>
            {PAGES.map((_, i) => (
              <View
                key={i}
                style={[styles.dot, i === currentPage && styles.dotActive]}
              />
            ))}
          </View>

          <Button
            title={isLastPage ? 'Get Started' : 'Next'}
            onPress={handleNext}
            icon={isLastPage ? undefined : 'arrow-forward'}
            iconPosition="right"
          />

          {!isLastPage && (
            <Button
              title="Skip"
              variant="ghost"
              size="small"
              onPress={() => router.replace('/(auth)/login')}
              style={styles.skipButton}
            />
          )}
        </View>
      </View>
    </AuthScreenWrapper>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  page: {
    width: SCREEN_WIDTH - SPACING.xl * 2,
    justifyContent: 'center',
    paddingBottom: SPACING['3xl'],
  },
  pageContent: {
    alignItems: 'center',
  },
  iconCircle: {
    width: 88,
    height: 88,
    borderRadius: 44,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: SPACING.lg,
  },
  logoImage: {
    width: 88,
    height: 88,
    borderRadius: 22,
    marginBottom: SPACING.lg,
  },
  title: {
    fontSize: TYPOGRAPHY.fontSize['3xl'],
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
    textAlign: 'center' as const,
    marginBottom: SPACING.sm,
  },
  tagline: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.medium as TextStyle['fontWeight'],
    color: COLORS.primary,
    textAlign: 'center' as const,
    marginBottom: SPACING.md,
  },
  body: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center' as const,
    lineHeight: 24,
    paddingHorizontal: SPACING.md,
    marginTop: SPACING.sm,
  },
  stepsList: {
    width: '100%',
    marginTop: SPACING.xl,
    gap: SPACING.lg,
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
  },
  stepNumber: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: COLORS.primary + '15',
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepNumberText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.primary,
  },
  stepText: {
    flex: 1,
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.text,
    lineHeight: 22,
  },
  promisesList: {
    width: '100%',
    marginTop: SPACING.xl,
    gap: SPACING.lg,
  },
  promiseRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.md,
  },
  promiseText: {
    flex: 1,
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.text,
    lineHeight: 22,
  },
  footer: {
    paddingBottom: SPACING.lg,
    alignItems: 'center',
    gap: SPACING.md,
  },
  dots: {
    flexDirection: 'row',
    gap: SPACING.sm,
    marginBottom: SPACING.sm,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: COLORS.lightGray,
  },
  dotActive: {
    backgroundColor: COLORS.primary,
    width: 24,
  },
  skipButton: {
    borderWidth: 0,
    paddingVertical: 0,
    minHeight: 32,
  },
})
