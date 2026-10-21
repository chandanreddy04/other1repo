import { useEffect, useRef, useState } from 'react'
import { notify } from '../../services/errorReporting'
import {
  View,
  Text,
  StyleSheet,
  TextStyle,
  SafeAreaView,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from 'react-native'
import { useLocalSearchParams, useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, SPACING, TYPOGRAPHY, RADIUS } from '../../constants'
import { useSubscriptionStore } from '../../store/useSubscriptionStore'
import toast from '../../utils/toast'

export default function RedeemCodeScreen() {
  const router = useRouter()
  // Deep-link entrypoint (e.g. madeitho.me/r/{code}) sets these so the
  // user lands on a confirmation toast rather than an empty form.
  const params = useLocalSearchParams<{ code?: string; autoApply?: string }>()
  const { applyReferralCode, isLoading } = useSubscriptionStore()
  const [code, setCode] = useState((params.code ?? '').toUpperCase())
  const [codeError, setCodeError] = useState('')
  const autoAppliedRef = useRef(false)

  useEffect(() => {
    // Auto-apply when arriving via /r/{code} short link. The ref guard
    // prevents re-running on subsequent renders (e.g. when the user
    // edits the code and re-submits manually).
    if (autoAppliedRef.current) return
    if (params.autoApply !== '1') return
    if (!params.code || params.code.length !== 8) return
    autoAppliedRef.current = true
    handleApply()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.autoApply, params.code])

  const handleApply = async () => {
    if (code.length !== 8) {
      setCodeError('Codes are 8 characters')
      return
    }
    try {
      await applyReferralCode(code)
      toast.success('30 days free — enjoy!')
      router.dismiss(2)
    } catch (error) {
      notify(
        error instanceof Error ? error : new Error(String(error)),
        'referrals.redeem'
      )
      toast.error(error instanceof Error ? error.message : 'Invalid code')
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.flex}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()}>
            <Ionicons name="arrow-back" size={24} color={COLORS.text} />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Redeem Code</Text>
          <View style={{ width: 24 }} />
        </View>

        <View style={styles.content}>
          <View style={styles.iconContainer}>
            <View style={styles.iconCircle}>
              <Ionicons name="key" size={32} color={COLORS.primary} />
            </View>
          </View>

          <Text style={styles.description}>
            Enter your 8-character referral or promo code
          </Text>

          <TextInput
            style={[styles.input, codeError ? styles.inputError : null]}
            placeholder="ABCD1234"
            value={code}
            onChangeText={text => {
              setCode(text.toUpperCase())
              if (codeError) setCodeError('')
            }}
            maxLength={8}
            autoCapitalize="characters"
            autoCorrect={false}
            autoFocus
          />
          {codeError ? <Text style={styles.errorText}>{codeError}</Text> : null}

          <TouchableOpacity
            style={[
              styles.applyButton,
              code.length < 8 && styles.applyButtonDisabled,
            ]}
            onPress={handleApply}
            disabled={isLoading || code.length < 8}
            activeOpacity={0.9}
          >
            {isLoading ? (
              <ActivityIndicator color={COLORS.white} />
            ) : (
              <Text style={styles.applyText}>Apply</Text>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  flex: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.md,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.lightGray,
    backgroundColor: COLORS.white,
  },
  headerTitle: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
  },
  content: {
    flex: 1,
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING['2xl'],
    alignItems: 'center',
  },
  iconContainer: {
    marginBottom: SPACING.lg,
  },
  iconCircle: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: COLORS.primary + '12',
    alignItems: 'center',
    justifyContent: 'center',
  },
  description: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center' as const,
    marginBottom: SPACING.xl,
  },
  input: {
    width: '100%',
    borderWidth: 2,
    borderColor: COLORS.lightGray,
    borderRadius: RADIUS.lg,
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.md,
    fontSize: TYPOGRAPHY.fontSize['2xl'],
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    textAlign: 'center' as const,
    letterSpacing: 4,
    color: COLORS.text,
    marginBottom: SPACING.xl,
  },
  inputError: {
    borderColor: COLORS.danger,
  },
  errorText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.danger,
    textAlign: 'center' as const,
    marginTop: -SPACING.lg,
    marginBottom: SPACING.lg,
  },
  applyButton: {
    width: '100%',
    backgroundColor: COLORS.primary,
    paddingVertical: 16,
    borderRadius: RADIUS.full,
    alignItems: 'center',
  },
  applyButtonDisabled: {
    opacity: 0.4,
  },
  applyText: {
    color: COLORS.white,
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
  },
})
