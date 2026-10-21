import { useCallback } from 'react'
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Alert,
  Linking,
  SafeAreaView,
  Image,
} from 'react-native'
import { useFocusEffect, useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { useAuthStore } from '../../store/useAuthStore'
import { useSubscriptionStore } from '../../store/useSubscriptionStore'
import { COLORS, SPACING, resolveUrl } from '../../constants'
import { ShareReferralButton } from '../../components/ShareReferralButton'
import { formatPhoneNumber } from '../../utils/validation'
import { SettingRow } from '../../components/SettingRow'
import { SMS_UNSUBSCRIBE_GRACE_DAYS } from '../../constants/config'
import { useAppConfig } from '../../store/useAppConfigStore'
import {
  getManageRoute,
  getSubscriptionStatusLine,
} from '../../utils/subscriptionDisplay'

export default function AccountScreen() {
  const router = useRouter()
  const appConfig = useAppConfig()
  const user = useAuthStore(state => state.user)
  const logout = useAuthStore(state => state.logout)
  const subscriptionStatus = useSubscriptionStore(state => state.status)
  const checkSubscription = useSubscriptionStore(
    state => state.checkSubscription
  )

  // Refresh on focus so the plan row reflects a cancel/reactivate or a change
  // made in the Stripe portal after returning from the manage screen.
  useFocusEffect(
    useCallback(() => {
      checkSubscription()
    }, [checkSubscription])
  )

  const handleLogout = () => {
    Alert.alert('Logout', 'Are you sure you want to logout?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Logout',
        style: 'destructive',
        onPress: async () => {
          await logout()
          router.replace('/(auth)/login')
        },
      },
    ])
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={styles.scrollContent}
      >
        <TouchableOpacity
          style={styles.header}
          activeOpacity={0.7}
          onPress={() => router.push('/account/profile')}
        >
          <View style={styles.headerShareButton}>
            <ShareReferralButton />
          </View>
          <View style={styles.avatar}>
            {user?.profile_photo_url ? (
              <Image
                source={{ uri: resolveUrl(user.profile_photo_url) }}
                style={styles.avatarImage}
              />
            ) : (
              <Ionicons name="person-circle" size={90} color={COLORS.primary} />
            )}
            <View style={styles.editBadge}>
              <Ionicons name="pencil" size={12} color={COLORS.white} />
            </View>
          </View>
          <Text style={styles.name}>{user?.full_name || 'User'}</Text>
          <Text style={styles.phoneNumber}>
            {user?.phone_number ? formatPhoneNumber(user.phone_number) : ''}
          </Text>
        </TouchableOpacity>

        {user?.sms_unsubscribed ? (
          <ProfileSection title="You unsubscribed from texts">
            <Text style={styles.smsUnsubscribedExplainer}>
              You won't get sign-in codes or alerts via SMS. In{' '}
              {SMS_UNSUBSCRIBE_GRACE_DAYS} days from when you texted STOP,
              we'll cancel your subscription at the next billing date
              unless you re-enable.
            </Text>
            {appConfig.smsNumber ? (
              <SettingRow
                icon="chatbubble-ellipses-outline"
                label={`Text START to ${appConfig.smsNumber}`}
                showArrow
                onPress={() => {
                  Linking.openURL(
                    `sms:${appConfig.smsNumber}?body=START`
                  )
                }}
              />
            ) : null}
            <SettingRow
              icon="card-outline"
              label="Cancel subscription now"
              showArrow
              onPress={() => router.push(getManageRoute(subscriptionStatus))}
            />
          </ProfileSection>
        ) : null}

        <ProfileSection title="Subscription">
          <SettingRow
            icon="card-outline"
            label="Manage Subscription"
            description={getSubscriptionStatusLine(subscriptionStatus)}
            showArrow
            onPress={() => router.push(getManageRoute(subscriptionStatus))}
          />
          {user?.share_code && (
            <SettingRow
              icon="gift-outline"
              label={
                user.referrals_remaining
                  ? `Get ${user.referrals_remaining} free month${user.referrals_remaining === 1 ? '' : 's'}`
                  : 'Refer a Friend'
              }
              showArrow
              onPress={() => router.push('/referrals')}
            />
          )}
        </ProfileSection>

        <ProfileSection title="Sessions">
          <SettingRow
            icon="time-outline"
            label="Session History"
            showArrow
            onPress={() => router.push('/sessions')}
          />
        </ProfileSection>

        <ProfileSection title="About">
          <SettingRow
            icon="help-circle-outline"
            label="Contact Support"
            showArrow
            onPress={() => Linking.openURL(`mailto:${appConfig.supportEmail}`)}
          />
          <SettingRow
            icon="document-text-outline"
            label="Terms and Conditions"
            showArrow
            onPress={() => Linking.openURL(appConfig.termsUrl)}
          />
          <SettingRow
            icon="shield-checkmark-outline"
            label="Privacy Policy"
            showArrow
            onPress={() => Linking.openURL(appConfig.privacyUrl)}
          />
          <SettingRow
            icon="information-circle-outline"
            label="Version"
            value="1.0.0"
          />
          <Text style={styles.smsHelperText}>
            Heads up: replying STOP to our number turns off all texts from
            Made It Home, including the sign-in code we send you. You can
            turn them back on by replying START.
          </Text>
        </ProfileSection>

        <ProfileSection title="Danger Zone">
          <SettingRow
            icon="trash-outline"
            label="Delete account"
            showArrow
            tint="danger"
            onPress={() => router.push('/account/delete')}
          />
        </ProfileSection>

        <TouchableOpacity style={styles.logoutButton} onPress={handleLogout}>
          <Ionicons name="log-out-outline" size={24} color={COLORS.danger} />
          <Text style={styles.logoutText}>Logout</Text>
        </TouchableOpacity>

        <View style={styles.footer} />
      </ScrollView>
    </SafeAreaView>
  )
}

function ProfileSection({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  scrollContent: {
    paddingBottom: SPACING['2xl'], // Match home page bottom spacing
  },
  header: {
    alignItems: 'center',
    paddingTop: SPACING.xl,
    paddingHorizontal: 20,
    paddingBottom: SPACING.xl,
    backgroundColor: COLORS.white,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.lightGray,
  },
  headerShareButton: {
    position: 'absolute',
    top: SPACING.xl,
    right: 20,
    zIndex: 1,
  },
  avatar: {
    marginBottom: SPACING.md,
  },
  editBadge: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    backgroundColor: COLORS.primary,
    borderRadius: 12,
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: COLORS.white,
  },
  avatarImage: {
    width: 90,
    height: 90,
    borderRadius: 45,
    borderWidth: 3,
    borderColor: COLORS.primary,
  },
  name: {
    fontSize: 24,
    fontWeight: 'bold',
    color: COLORS.text,
    marginBottom: 8,
  },
  smsUnsubscribedExplainer: {
    fontSize: 14,
    color: COLORS.text,
    lineHeight: 20,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
  },
  smsHelperText: {
    fontSize: 13,
    color: COLORS.textLight,
    lineHeight: 18,
    paddingHorizontal: SPACING.md,
    paddingTop: SPACING.sm,
    paddingBottom: SPACING.xs,
  },
  phoneNumber: {
    fontSize: 16,
    color: COLORS.textLight,
    fontWeight: '500',
  },
  section: {
    marginTop: 20,
    backgroundColor: COLORS.white,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: COLORS.lightGray,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: COLORS.textLight,
    textTransform: 'uppercase',
    paddingHorizontal: 20,
    paddingTop: 15,
    paddingBottom: 10,
  },
  logoutButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    backgroundColor: COLORS.white,
    marginTop: 30,
    marginHorizontal: 20,
    padding: 15,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: COLORS.danger,
  },
  logoutText: {
    fontSize: 16,
    fontWeight: '600',
    color: COLORS.danger,
  },
  footer: {
    height: 50,
  },
})
