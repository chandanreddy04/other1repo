import { View, StyleSheet } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { Tabs } from 'expo-router'
import { CustomTabBar } from '../../components/navigation/CustomTabBar'
import {
  CircleEmptyBanner,
  useShouldShowEmptyBanner,
} from '../../components/CircleEmptyBanner'
import {
  SmsUnsubscribedBanner,
  useShouldShowSmsUnsubscribedBanner,
} from '../../components/SmsUnsubscribedBanner'
import { COLORS } from '../../constants'

export default function TabLayout() {
  // The two banners are mutually exclusive in priority — the empty-
  // circle one trumps because functional outage > user-controlled
  // SMS opt-out. (If somehow both fire, the user sees just the red
  // one until they fix the circle, then the yellow one for the
  // SMS unsubscribe state.)
  //
  // Both hooks must be called unconditionally on every render — React
  // tracks state by call order, and gating one behind `&&` would
  // skip it whenever the other is true, corrupting the next hook's
  // state.
  const showCircleBanner = useShouldShowEmptyBanner()
  const wantsSmsBanner = useShouldShowSmsUnsubscribedBanner()
  const showSmsBanner = !showCircleBanner && wantsSmsBanner
  return (
    <View style={styles.container}>
      {showCircleBanner ? (
        <SafeAreaView edges={['top']} style={styles.bannerWrap}>
          <CircleEmptyBanner />
        </SafeAreaView>
      ) : null}
      {showSmsBanner ? (
        <SafeAreaView edges={['top']} style={styles.smsBannerWrap}>
          <SmsUnsubscribedBanner />
        </SafeAreaView>
      ) : null}
      <Tabs
        tabBar={props => <CustomTabBar {...props} />}
        screenOptions={{
          headerShown: false,
        }}
      >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Home',
          tabBarAccessibilityLabel: 'Home',
        }}
      />
      <Tabs.Screen
        name="circle"
        options={{
          title: 'Circle',
          tabBarAccessibilityLabel: 'Circle',
        }}
      />
      <Tabs.Screen
        name="account"
        options={{
          title: 'Account',
          tabBarAccessibilityLabel: 'Account',
        }}
      />
      </Tabs>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  // SafeAreaView wraps the banner so on a notched device the red
  // banner extends into the status-bar area rather than leaving a
  // white gap above it.
  bannerWrap: {
    backgroundColor: COLORS.danger,
  },
  smsBannerWrap: {
    backgroundColor: COLORS.accent.orange,
  },
})
