import { useEffect, useState } from 'react'
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  SafeAreaView,
  Share,
  ScrollView,
  ActivityIndicator,
  Image,
} from 'react-native'
import { useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import QRCode from 'react-native-qrcode-svg'
import { useAuthStore } from '../../store/useAuthStore'
import api from '../../services/api'
import {
  COLORS,
  SPACING,
  TYPOGRAPHY,
  RADIUS,
  SHADOWS,
  resolveUrl,
} from '../../constants'
import { useAppConfig } from '../../store/useAppConfigStore'
import { notify } from '../../services/errorReporting'

export default function ReferralScreen() {
  const router = useRouter()
  const user = useAuthStore(state => state.user)
  const appConfig = useAppConfig()
  const referralDomain = `${appConfig.shortDomain}/r`
  const [referralInfo, setReferralInfo] = useState<{
    referral_code: string
    can_refer: boolean
    referrals_used: number
    referrals_max: number
  } | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadReferralInfo()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadReferralInfo = async () => {
    try {
      const info = await api.getReferralInfo()
      setReferralInfo(info)
    } catch (err) {
      notify(err, 'referral.load')
      // Fall back to user's referral code if API fails
      if (user?.share_code) {
        setReferralInfo({
          referral_code: user.share_code,
          can_refer: true,
          referrals_used: 0,
          referrals_max: 6,
        })
      }
    } finally {
      setLoading(false)
    }
  }

  const referralUrl = referralInfo
    ? `${referralDomain}/${referralInfo.referral_code}`
    : ''

  const handleShare = async () => {
    if (!referralUrl) return
    await Share.share({
      message: `Stay safe with Made It Home! Register here for a free month: ${referralUrl}`,
    })
  }

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={COLORS.primary} />
        </View>
      </SafeAreaView>
    )
  }

  if (!referralInfo) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()}>
            <Ionicons name="chevron-back" size={24} color={COLORS.primary} />
          </TouchableOpacity>
        </View>
        <View style={styles.loadingContainer}>
          <Text style={styles.errorText}>Unable to load referral info</Text>
        </View>
      </SafeAreaView>
    )
  }

  const remaining = referralInfo.referrals_max - referralInfo.referrals_used

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.back()}
          style={styles.backButton}
        >
          <Ionicons name="chevron-back" size={24} color={COLORS.primary} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Refer a Friend</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <Text style={styles.headline}>
          {remaining > 0 ? 'Give 1 month, Get 1 month' : 'Give 1 month free'}
        </Text>
        <Text style={styles.subtitle}>
          {remaining > 0
            ? 'Share your code — you both get a free month'
            : 'Share your code — they get a free month'}
        </Text>

        {/* QR Card — LinkedIn/Venmo style */}
        <View style={styles.qrCard}>
          <View style={styles.profileSection}>
            {user?.profile_photo_url ? (
              <Image
                source={{ uri: resolveUrl(user.profile_photo_url) }}
                style={styles.profilePhoto}
              />
            ) : (
              <View style={styles.profilePhotoPlaceholder}>
                <Ionicons name="person" size={16} color={COLORS.white} />
              </View>
            )}
            <Text style={styles.profileName}>{user?.full_name || 'You'}</Text>
          </View>

          <View style={styles.qrContainer}>
            <QRCode
              value={referralUrl}
              size={200}
              color={COLORS.text}
              backgroundColor={COLORS.white}
            />
          </View>

          <Text style={styles.referralCode}>{referralInfo.referral_code}</Text>
        </View>

        {/* Actions */}
        <TouchableOpacity style={styles.shareButton} onPress={handleShare}>
          <Ionicons name="share-outline" size={20} color={COLORS.white} />
          <Text style={styles.shareButtonText}>Share</Text>
        </TouchableOpacity>

        {remaining > 0 && (
          <Text style={styles.remainingText}>
            {remaining} free month{remaining === 1 ? '' : 's'} left to earn
          </Text>
        )}
      </ScrollView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  errorText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.md,
    backgroundColor: COLORS.white,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.lightGray,
  },
  backButton: {
    marginLeft: -4,
  },
  headerTitle: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.bold,
    color: COLORS.text,
  },
  content: {
    alignItems: 'center',
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.xl,
    paddingBottom: SPACING['2xl'],
  },
  headline: {
    fontSize: TYPOGRAPHY.fontSize.xl,
    fontWeight: TYPOGRAPHY.fontWeight.bold,
    color: COLORS.text,
    textAlign: 'center',
    marginBottom: SPACING.xs,
  },
  subtitle: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    textAlign: 'center',
    marginBottom: SPACING.xl,
  },
  qrCard: {
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.xl,
    padding: SPACING.lg,
    alignItems: 'center',
    width: '100%',
    ...SHADOWS.md,
  },
  profileSection: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    marginBottom: SPACING.lg,
  },
  profilePhoto: {
    width: 32,
    height: 32,
    borderRadius: 16,
    borderWidth: 2,
    borderColor: COLORS.primary,
  },
  profilePhotoPlaceholder: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: COLORS.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  profileName: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
    color: COLORS.text,
  },
  qrContainer: {
    padding: SPACING.md,
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.lg,
    marginBottom: SPACING.md,
  },
  referralCode: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
    color: COLORS.textLight,
    letterSpacing: 2,
  },
  shareButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACING.sm,
    backgroundColor: COLORS.primary,
    marginTop: SPACING.xl,
    width: '100%',
    paddingVertical: 14,
    borderRadius: RADIUS.full,
  },
  shareButtonText: {
    color: COLORS.white,
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
  },
  remainingText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    marginTop: SPACING.sm,
  },
})
