import React, { useState, useRef } from 'react'
import {
  View,
  TouchableOpacity,
  Text,
  StyleSheet,
  Animated,
  Vibration,
  Platform,
  Alert,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Ionicons } from '@expo/vector-icons'
import { LinearGradient } from 'expo-linear-gradient'
import type { BottomTabBarProps } from '@react-navigation/bottom-tabs'
import { COLORS, TYPOGRAPHY, SPACING, RADIUS, SHADOWS } from '../../constants'
import { TrustCircleIcon } from '../icons/TrustCircleIcon'
import { useCircleStore } from '../../store/useCircleStore'

// SOS press-and-hold: a 3-2-1 countdown that COMMITS at "1" (1s remaining),
// because most people release around "1" and a release must never cancel an
// SOS they meant to send.
const EMERGENCY_DURATION_MS = 3000
const EMERGENCY_TICK_MS = 50
const EMERGENCY_SECONDS = EMERGENCY_DURATION_MS / 1000 // 3
const EMERGENCY_INCREMENT = (EMERGENCY_TICK_MS / EMERGENCY_DURATION_MS) * 100
// Progress (0-100) at which 1s remains — i.e. the countdown shows "1".
const EMERGENCY_ACTIVATE_AT = 100 - (1000 / EMERGENCY_DURATION_MS) * 100 // ≈66.7

export const CustomTabBar: React.FC<Omit<BottomTabBarProps, 'insets'>> = ({
  state,
  descriptors,
  navigation,
}) => {
  const insets = useSafeAreaInsets()
  const circleOfTrust = useCircleStore(s => s.circleOfTrust)
  const hasActiveCircle = circleOfTrust.some(m => m.status === 'active')

  const [emergencyProgress, setEmergencyProgress] = useState(0)
  const emergencyTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const progressAnim = useRef(new Animated.Value(0)).current

  const handleEmergencyStart = () => {
    if (!hasActiveCircle) {
      // Per copy doc 3c: SOS without a Circle goes nowhere. Hard-block
      // with a modal that names the consequence and routes the owner to
      // the Circle tab instead of letting the press theatrically
      // activate an unreachable SOS.
      Alert.alert(
        'Your Circle is empty',
        'SOS alerts your Circle of Trust. Add at least one person to enable this functionality.',
        [
          { text: 'Not now', style: 'cancel' },
          {
            text: 'Add to Circle',
            onPress: () => navigation.navigate('circle'),
          },
        ]
      )
      return
    }

    // Show the overlay + countdown IMMEDIATELY, before any haptic — the UI must
    // lead the vibration. A tiny non-zero progress mounts the overlay this
    // frame; its opacity is instant (not tied to progress), so it's visible now.
    progressAnim.setValue(0)
    setEmergencyProgress(0.01)

    // Vibrate only AFTER the overlay has had a frame to paint.
    if (Platform.OS !== 'web') {
      requestAnimationFrame(() => Vibration.vibrate(150))
    }

    let progress = 0
    let secondsPassed = 0

    emergencyTimer.current = setInterval(() => {
      progress += EMERGENCY_INCREMENT
      setEmergencyProgress(progress)

      // One vibration pulse per elapsed second (shorter as it progresses).
      const currentSecond = Math.floor((progress / 100) * EMERGENCY_SECONDS)
      if (currentSecond > secondsPassed) {
        secondsPassed = currentSecond
        if (Platform.OS !== 'web') {
          Vibration.vibrate(Math.max(50, 150 - currentSecond * 20))
        }
      }

      Animated.timing(progressAnim, {
        toValue: progress / 100,
        duration: EMERGENCY_TICK_MS,
        useNativeDriver: false,
      }).start()

      // Commit at "1" (1s remaining), not at 0 — see EMERGENCY_ACTIVATE_AT.
      if (progress >= EMERGENCY_ACTIVATE_AT) {
        handleEmergencyRelease(true)
      }
    }, EMERGENCY_TICK_MS)
  }

  const handleEmergencyRelease = (completed: boolean = false) => {
    if (emergencyTimer.current) {
      clearInterval(emergencyTimer.current)
      emergencyTimer.current = null
    }

    if (Platform.OS !== 'web') {
      Vibration.cancel()
    }

    if (completed) {
      // Emergency activated - trigger alarm state in app
      // This would be handled by global state management in real app
      if (navigation) {
        navigation.navigate('index', { emergencyActivated: true })
      }
      // eslint-disable-next-line no-console
      console.log('Emergency SOS activated')
    }

    // Reset progress
    Animated.timing(progressAnim, {
      toValue: 0,
      duration: 200,
      useNativeDriver: false,
    }).start(() => {
      setEmergencyProgress(0)
    })
  }

  // Define icons for each route
  const getIconName = (routeName: string): keyof typeof Ionicons.glyphMap => {
    switch (routeName) {
      case 'index':
        return 'home'
      case 'circle':
        return 'shield-checkmark'
      case 'account':
        return 'settings-sharp'
      default:
        return 'ellipse'
    }
  }

  // Hide tab bar when a screen requests it (e.g. contact selector)
  const focusedRoute = state.routes[state.index]
  const focusedOptions = descriptors[focusedRoute.key]?.options
  if (
    (focusedOptions?.tabBarStyle as Record<string, unknown> | undefined)
      ?.display === 'none'
  )
    return null

  return (
    <>
      {/* Countdown Overlay with Ripples - Outside of container so it covers full screen */}
      {emergencyProgress > 0 && (
        <>
          {/* Dark background overlay */}
          <Animated.View
            style={[
              styles.backgroundOverlay,
              {
                // Instant — the overlay must appear the moment the button is
                // pressed, not fade in with progress.
                opacity: 0.8,
              },
            ]}
            pointerEvents="none"
          />

          <View style={styles.countdownOverlay} pointerEvents="none">
            {/* Ripple Effects from center - reversed so darker appears on top */}
            {[4, 3, 2, 1, 0].map(index => {
              const delay = index * 0.2
              const isActive = emergencyProgress > index * 20
              // Progress from deep yellow to orange
              const rippleColors = [
                '#FFB800', // Deep golden yellow
                '#FFA500', // Golden orange
                '#FF9500', // Orange
                '#FF8C00', // Darker orange
                '#FF6B00', // Deep orange/red-orange
              ]
              return isActive ? (
                <Animated.View
                  key={index}
                  style={[
                    styles.centerRipple,
                    {
                      backgroundColor: rippleColors[index],
                      opacity: progressAnim.interpolate({
                        inputRange: [delay, delay + 0.2, 1],
                        outputRange: [0, 0.4, 0],
                        extrapolate: 'clamp',
                      }),
                      transform: [
                        {
                          scale: progressAnim.interpolate({
                            inputRange: [delay, 1],
                            outputRange: [0.5, 30],
                            extrapolate: 'clamp',
                          }),
                        },
                      ],
                    },
                  ]}
                />
              ) : null
            })}

            <Animated.Text
              style={[
                styles.countdownLabel,
                { opacity: 1 },
              ]}
            >
              Notifying your Circle of Trust in
            </Animated.Text>
            <Animated.Text
              style={[
                styles.countdownText,
                {
                  // Instant + full-size from the first frame; a gentle grow as
                  // it counts down.
                  opacity: 1,
                  transform: [
                    {
                      scale: progressAnim.interpolate({
                        inputRange: [0, 1],
                        outputRange: [1, 1.15],
                      }),
                    },
                  ],
                },
              ]}
            >
              {Math.max(
                1,
                Math.ceil(((100 - emergencyProgress) * EMERGENCY_SECONDS) / 100)
              )}
            </Animated.Text>
          </View>
        </>
      )}

      <View style={[styles.container, { paddingBottom: insets.bottom }]}>
        <View style={styles.tabBar}>
          <View style={styles.leftTabs}>
            {state.routes
              .filter(r => r.name === 'index' || r.name === 'circle')
              .map(route => {
                const { options } = descriptors[route.key]
                const isFocused = state.index === state.routes.indexOf(route)

                const onPress = () => {
                  const event = navigation.emit({
                    type: 'tabPress',
                    target: route.key,
                    canPreventDefault: true,
                  })

                  if (!isFocused && !event.defaultPrevented) {
                    navigation.navigate(route.name)
                  }
                }

                const iconName = getIconName(route.name)

                return (
                  <TouchableOpacity
                    key={route.key}
                    accessibilityRole="button"
                    accessibilityState={isFocused ? { selected: true } : {}}
                    accessibilityLabel={options.tabBarAccessibilityLabel}
                    testID={
                      (options as Record<string, unknown>).tabBarTestID as
                        | string
                        | undefined
                    }
                    onPress={onPress}
                    style={styles.tab}
                  >
                    <View>
                      {route.name === 'circle' ? (
                        <TrustCircleIcon
                          size={26}
                          color={isFocused ? COLORS.primary : COLORS.gray}
                          focused={isFocused}
                        />
                      ) : (
                        <Ionicons
                          name={iconName}
                          size={26}
                          color={isFocused ? COLORS.primary : COLORS.gray}
                        />
                      )}
                    </View>
                  </TouchableOpacity>
                )
              })}
          </View>

          <View style={styles.centerSpace} />

          <View style={styles.rightTabs}>
            {state.routes
              .filter(r => r.name === 'account')
              .map(route => {
                const { options } = descriptors[route.key]
                const isFocused = state.index === state.routes.indexOf(route)

                const onPress = () => {
                  const event = navigation.emit({
                    type: 'tabPress',
                    target: route.key,
                    canPreventDefault: true,
                  })

                  if (!isFocused && !event.defaultPrevented) {
                    navigation.navigate(route.name)
                  }
                }

                const iconName = getIconName(route.name)

                return (
                  <TouchableOpacity
                    key={route.key}
                    accessibilityRole="button"
                    accessibilityState={isFocused ? { selected: true } : {}}
                    accessibilityLabel={options.tabBarAccessibilityLabel}
                    testID={
                      (options as Record<string, unknown>).tabBarTestID as
                        | string
                        | undefined
                    }
                    onPress={onPress}
                    style={styles.tab}
                  >
                    <View>
                      <Ionicons
                        name={iconName}
                        size={26}
                        color={isFocused ? COLORS.primary : COLORS.gray}
                      />
                    </View>
                  </TouchableOpacity>
                )
              })}
          </View>
        </View>

        {/* Emergency Button */}
        <View style={styles.emergencyContainer}>
          <TouchableOpacity
            onPressIn={handleEmergencyStart}
            onPressOut={() => handleEmergencyRelease(false)}
            activeOpacity={1}
            accessibilityRole="button"
            accessibilityLabel="SOS"
            accessibilityHint="Press and hold to send an SOS alert to your Circle of Trust"
            style={[
              styles.emergencyTouchable,
              emergencyProgress > 0 && styles.emergencyPressed,
            ]}
          >
            <LinearGradient
              colors={
                hasActiveCircle
                  ? ['#FFE066', '#FFD43B']
                  : ['#E8E8E8', '#D9D9D9']
              }
              style={styles.emergencyButton}
            >
              {emergencyProgress > 0 && (
                <>
                  <Animated.View
                    style={[
                      styles.progressRing,
                      {
                        opacity: progressAnim,
                        transform: [
                          {
                            scale: progressAnim.interpolate({
                              inputRange: [0, 1],
                              outputRange: [0.8, 1.1],
                            }),
                          },
                        ],
                      },
                    ]}
                  />
                  <Animated.View
                    style={[
                      styles.dangerOverlay,
                      {
                        opacity: progressAnim.interpolate({
                          inputRange: [0, 0.5, 1],
                          outputRange: [0, 0.3, 0.5],
                        }),
                      },
                    ]}
                  />
                </>
              )}
              <View style={styles.emergencyContent}>
                <Text
                  style={[
                    styles.sosText,
                    !hasActiveCircle && { color: COLORS.gray },
                  ]}
                >
                  SOS
                </Text>
              </View>
            </LinearGradient>
          </TouchableOpacity>
        </View>
      </View>
    </>
  )
}

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: COLORS.white,
    borderTopWidth: 1,
    borderTopColor: COLORS.lightGray,
    ...SHADOWS.sm,
  },
  tabBar: {
    flexDirection: 'row',
    height: 56,
    paddingHorizontal: SPACING.lg,
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  leftTabs: {
    flexDirection: 'row',
    flex: 1,
    justifyContent: 'space-around',
  },
  centerSpace: {
    width: 90, // Space for SOS button
  },
  rightTabs: {
    flexDirection: 'row',
    flex: 1,
    justifyContent: 'space-around',
  },
  tab: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.md,
  },
  emergencyContainer: {
    position: 'absolute',
    bottom: 35, // Raised higher so center aligns with top of tab bar
    left: '50%',
    transform: [{ translateX: -35 }],
    alignItems: 'center',
  },
  emergencyTouchable: {
    borderRadius: RADIUS.full,
    ...SHADOWS.lg,
  },
  emergencyPressed: {
    transform: [{ translateY: 2 }],
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.15,
    shadowRadius: 4,
    elevation: 2,
  },
  emergencyButton: {
    width: 70,
    height: 70,
    borderRadius: RADIUS.full,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 3,
    borderColor: COLORS.white,
  },
  emergencyContent: {
    alignItems: 'center',
  },
  sosText: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.bold,
    color: COLORS.text,
    letterSpacing: 1,
  },
  progressRing: {
    position: 'absolute',
    width: 64,
    height: 64,
    borderRadius: 32,
    borderWidth: 3,
    borderColor: COLORS.white,
    backgroundColor: 'rgba(255, 255, 255, 0.3)',
  },
  dangerOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: '#FF6B6B',
    borderRadius: 32,
  },
  backgroundOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.9)',
    zIndex: 99,
  },
  countdownOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 100,
  },
  centerRipple: {
    position: 'absolute',
    width: 100,
    height: 100,
    borderRadius: 50,
    top: '50%',
    left: '50%',
    marginTop: -50,
    marginLeft: -50,
  },
  countdownLabel: {
    fontSize: 24,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
    color: COLORS.white,
    textShadowColor: 'rgba(0, 0, 0, 0.7)',
    textShadowOffset: { width: 0, height: 2 },
    textShadowRadius: 8,
    marginBottom: SPACING.md,
    textAlign: 'center',
  },
  countdownText: {
    fontSize: 120,
    fontWeight: TYPOGRAPHY.fontWeight.bold,
    color: COLORS.white,
    textShadowColor: 'rgba(0, 0, 0, 0.7)',
    textShadowOffset: { width: 0, height: 3 },
    textShadowRadius: 12,
  },
})
