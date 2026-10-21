import { useState, useRef, useEffect } from 'react'
import { Linking } from 'react-native'
import { notify } from '../../services/errorReporting'
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TextStyle,
  TouchableOpacity,
  ActivityIndicator,
  Keyboard,
  Image,
} from 'react-native'
import { useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { AsYouType } from 'libphonenumber-js'
import { useAuthStore } from '../../store/useAuthStore'
import { Button } from '../../components/ui'
import AsyncStorage from '@react-native-async-storage/async-storage'
import {
  COLORS,
  TYPOGRAPHY,
  SPACING,
  RADIUS,
  STORAGE_KEYS,
} from '../../constants'
import { SMS_CONSENT_COPY } from '../../constants/config'
import { useAppConfig } from '../../store/useAppConfigStore'
import { AuthScreenWrapper } from '../../components/AuthScreenWrapper'
import api, { ApiError } from '../../services/api'
import toast from '../../utils/toast'
import {
  clearPendingRoute,
  consumeLandingRoute,
} from '../../utils/authRedirect'

export default function LoginScreen() {
  const router = useRouter()
  const setUser = useAuthStore(state => state.setUser)
  const appConfig = useAppConfig()

  // Phone number state - US only
  const [phoneNumber, setPhoneNumber] = useState('') // Raw digits only
  const [formattedPhone, setFormattedPhone] = useState('') // Formatted display

  // OTP state
  const [otpSent, setOtpSent] = useState(false)
  const [otpCode, setOtpCode] = useState('')
  const [resendTimer, setResendTimer] = useState(0)
  const [codeAlreadySent, setCodeAlreadySent] = useState(false)

  // SMS consent — unchecked by default. Send Code stays disabled until the
  // user actively checks this (Twilio A2P 10DLC requires explicit opt-in).
  const [smsConsent, setSmsConsent] = useState(false)

  // Loading states
  const [loading, setLoading] = useState(false)
  const [verifying, setVerifying] = useState(false)

  // Inline validation
  const [phoneError, setPhoneError] = useState('')
  const [otpError, setOtpError] = useState('')

  // Set when /auth/request-otp returns `phone_opted_out` — the phone
  // texted STOP earlier and we can't send a code until they text START.
  // `supportNumber` is the Made It Home Twilio number for the deep link.
  const [optedOutSupportNumber, setOptedOutSupportNumber] = useState<
    string | null
  >(null)

  // OTP input refs
  const otpRef = useRef<TextInput | null>(null)

  // No longer needed - US only

  // Timer for resend OTP
  useEffect(() => {
    if (resendTimer > 0) {
      const timer = setTimeout(() => setResendTimer(resendTimer - 1), 1000)
      return () => clearTimeout(timer)
    }
  }, [resendTimer])

  // Get full E164 formatted phone number (US only)
  const getE164PhoneNumber = () => {
    const cleaned = phoneNumber.replace(/\D/g, '')
    return `+1${cleaned}`
  }

  const handlePhoneChange = (value: string) => {
    if (phoneError) setPhoneError('')
    if (optedOutSupportNumber !== null) setOptedOutSupportNumber(null)
    // Get current digits and new value's digits
    const currentDigits = phoneNumber
    const newValueDigits = value.replace(/\D/g, '')

    // Determine if user is deleting
    const isDeleting = value.length < formattedPhone.length

    if (isDeleting) {
      // When deleting, check if digits actually changed
      if (newValueDigits === currentDigits) {
        // No digit was deleted, only formatting char - remove last digit manually
        const updatedDigits = currentDigits.slice(0, -1)
        setPhoneNumber(updatedDigits)

        if (updatedDigits === '') {
          setFormattedPhone('')
        } else {
          const formatter = new AsYouType('US')
          const formatted = formatter.input(updatedDigits)
          setFormattedPhone(formatted)
        }
      } else {
        // Digit was deleted normally
        setPhoneNumber(newValueDigits)

        if (newValueDigits === '') {
          setFormattedPhone('')
        } else {
          const formatter = new AsYouType('US')
          const formatted = formatter.input(newValueDigits)
          setFormattedPhone(formatted)
        }
      }
    } else {
      // Adding characters - US phone numbers are max 10 digits
      if (newValueDigits.length > 10) {
        return
      }

      setPhoneNumber(newValueDigits)

      if (newValueDigits === '') {
        setFormattedPhone('')
      } else {
        const formatter = new AsYouType('US')
        const formatted = formatter.input(newValueDigits)
        setFormattedPhone(formatted)
      }
    }
  }

  const handleRequestOTP = async () => {
    if (phoneNumber.length < 7) {
      setPhoneError('Please enter a valid phone number')
      return
    }

    const e164Phone = getE164PhoneNumber()

    setLoading(true)
    try {
      const response = await api.requestOTP(e164Phone)

      if (response.success) {
        setOtpSent(true)
        setCodeAlreadySent(false)
        setResendTimer(60)
        toast.success('Code sent')
        setTimeout(() => otpRef.current?.focus(), 500)
      } else {
        throw new Error(response.message || 'Failed to send verification code')
      }
    } catch (error) {
      const apiError = error as ApiError
      if (apiError.statusCode === 429 && apiError.retryAfter) {
        setOtpSent(true)
        setCodeAlreadySent(true)
        setResendTimer(apiError.retryAfter)
        setTimeout(() => otpRef.current?.focus(), 500)
      } else if (
        apiError.code === 'phone_opted_out' &&
        apiError.details?.code === 'phone_opted_out'
      ) {
        // 5b: inline message above the phone input + a tap-to-text-
        // START button. The inline block carries the actionable button
        // so we don't double up with a redundant toast.
        // Branch-narrowed: details.support_number is typed `string`.
        setOptedOutSupportNumber(apiError.details.support_number)
      } else {
        notify(
          error instanceof Error ? error : new Error(String(error)),
          'request-otp'
        )
        toast.error(
          error instanceof Error
            ? error.message
            : 'Failed to send verification code'
        )
      }
    } finally {
      setLoading(false)
    }
  }

  const autoVerifyScheduledRef = useRef(false)
  const handleOtpChange = (value: string) => {
    if (otpError) setOtpError('')
    // Single input (mirrors the web one-time-code field). SMS autofill and
    // paste deliver the whole code in one onChangeText — strip any non-digits
    // (formatting/spaces) and cap at 6. Auto-verify once complete.
    const digits = value.replace(/\D/g, '').slice(0, 6)
    setOtpCode(digits)
    if (digits.length < 6) {
      autoVerifyScheduledRef.current = false
      return
    }
    if (!autoVerifyScheduledRef.current) {
      autoVerifyScheduledRef.current = true
      // Defer out of this onChangeText tick. iOS SMS autofill keeps mutating
      // the native field right after this fires; navigating away synchronously
      // (which unmounts the input) mid-autofill white-screens the app. A
      // macrotask lets the field settle and this render commit before we
      // verify + navigate. The ref guards against autofill firing twice.
      setTimeout(() => handleVerifyOTP(digits), 0)
    }
  }

  const handleVerifyOTP = async (code?: string) => {
    const otpToVerify = code || otpCode

    if (otpToVerify.length !== 6) {
      setOtpError('Please enter the complete 6-digit code')
      return
    }

    setVerifying(true)
    Keyboard.dismiss()

    try {
      const e164Phone = getE164PhoneNumber()
      const data = await api.verifyOTP(e164Phone, otpToVerify)

      if (data.deletion_pending) {
        // Soft-deleted within grace — show the restore screen. The issued
        // tokens authenticate only /me/restore until the user calls
        // it, so we must NOT setUser or land in /(tabs) where every
        // other endpoint will 403. Restoring an account is a different
        // intent than the deep link that may have sent them here, so
        // discard any pending destination.
        void clearPendingRoute()
        router.replace({
          pathname: '/account/restore',
          params: data.scheduled_deletion_at
            ? { scheduled_deletion_at: data.scheduled_deletion_at }
            : undefined,
        })
      } else if (data.is_new_user) {
        // New user - go to profile setup. Any pending deep-link
        // destination persists and is replayed once they finish
        // onboarding (see onboarding.tsx).
        router.replace({
          pathname: '/account/profile',
          params: { required: '1' },
        })
      } else {
        // Existing user - set user data.
        if (data.user) {
          await setUser(data.user)
        }
        // A fresh install wipes ONBOARDING_COMPLETED (AsyncStorage), and the
        // OS permissions are genuinely reset with it — so run the permissions
        // onboarding before landing them home instead of jumping straight
        // there (which used to skip it entirely on a clean reinstall).
        // Onboarding consumes the landing route on completion, so a deep-link
        // destination is preserved.
        const onboarded =
          (await AsyncStorage.getItem(STORAGE_KEYS.ONBOARDING_COMPLETED).catch(
            () =>
              /* benign: a missing onboarding flag routes to onboarding */ null
          )) === 'true'
        if (!onboarded) {
          router.replace('/(auth)/onboarding')
        } else {
          const { href } = await consumeLandingRoute()
          router.replace(href)
        }
      }
    } catch (error) {
      // A wrong or expired code is a 400 here by design — the one expected
      // 400 in the app, so this screen opts it out of reporting itself.
      if ((error as ApiError).statusCode !== 400) {
        notify(
          error instanceof Error ? error : new Error(String(error)),
          'verify-otp'
        )
      }
      toast.error(error instanceof Error ? error.message : 'Invalid code')
      // Clear the code so the user can re-enter
      setOtpCode('')
      otpRef.current?.focus()
    } finally {
      setVerifying(false)
    }
  }

  const handleResendOTP = async () => {
    if (resendTimer > 0) return

    setLoading(true)
    try {
      const e164Phone = getE164PhoneNumber()
      const response = await api.resendOTP(e164Phone)

      if (response.success) {
        setCodeAlreadySent(false)
        setResendTimer(60)
        toast.success('Code resent')
      } else {
        throw new Error(response.message || 'Failed to resend code')
      }
    } catch (error) {
      notify(
        error instanceof Error ? error : new Error(String(error)),
        'resend-otp'
      )
      toast.error(
        error instanceof Error ? error.message : 'Failed to resend code'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthScreenWrapper withKeyboard scrollable>
      {/* Main Content */}
      <View style={styles.mainContent}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.logoContainer}>
            <Image
              // eslint-disable-next-line @typescript-eslint/no-require-imports
              source={require('../../assets/images/icon.png')}
              style={styles.logo}
            />
          </View>
          <Text style={styles.title}>{!otpSent ? 'Welcome' : 'Verify'}</Text>
          {!otpSent && (
            <Text style={styles.subtitle}>
              Please enter your phone number to get started
            </Text>
          )}
          {otpSent && (
            <Text style={styles.subtitle}>
              Code sent to {formattedPhone || getE164PhoneNumber()}
            </Text>
          )}
        </View>

        {/* Form Elements */}
        <View style={styles.formContainer}>
          {!otpSent ? (
            // Phone Number Input
            <>
              <View style={styles.inputContainer}>
                <View
                  style={[
                    styles.phoneInputWrapper,
                    phoneError ? styles.phoneInputError : null,
                  ]}
                >
                  <View style={styles.countryCode}>
                    <Text style={styles.flagEmoji}>🇺🇸</Text>
                    <Text style={styles.countryCodeText}>+1</Text>
                  </View>
                  <TextInput
                    style={styles.phoneInput}
                    value={formattedPhone}
                    onChangeText={handlePhoneChange}
                    placeholder="(555) 123-4567"
                    placeholderTextColor={COLORS.gray}
                    keyboardType="phone-pad"
                    autoFocus
                  />
                </View>
                {phoneError ? (
                  <Text style={styles.errorText}>{phoneError}</Text>
                ) : null}
                {optedOutSupportNumber !== null ? (
                  <View style={styles.optedOutBlock}>
                    <Text style={styles.optedOutText}>
                      {optedOutSupportNumber
                        ? `This number is unsubscribed from texts. Text START to ${optedOutSupportNumber} and try again.`
                        : 'This number is unsubscribed from Made It Home texts. Reply START to our number from this phone to re-enable them.'}
                    </Text>
                    {optedOutSupportNumber ? (
                      <Button
                        title="Text START"
                        variant="secondary"
                        onPress={() => {
                          Linking.openURL(
                            `sms:${optedOutSupportNumber}?body=START`
                          )
                        }}
                        style={styles.optedOutButton}
                      />
                    ) : null}
                  </View>
                ) : null}
              </View>

              <View style={styles.promiseRow}>
                <Ionicons
                  name="shield-checkmark"
                  size={18}
                  color={COLORS.primary}
                  style={styles.promiseIcon}
                />
                <Text style={styles.promiseText}>
                  {SMS_CONSENT_COPY.promise}
                </Text>
              </View>

              <TouchableOpacity
                style={styles.consentRow}
                onPress={() => setSmsConsent(prev => !prev)}
                activeOpacity={0.7}
                accessibilityRole="checkbox"
                accessibilityState={{ checked: smsConsent }}
              >
                <Ionicons
                  name={smsConsent ? 'checkbox' : 'square-outline'}
                  size={24}
                  color={smsConsent ? COLORS.primary : COLORS.gray}
                  style={styles.consentBox}
                />
                <Text style={styles.consentLabel}>
                  {SMS_CONSENT_COPY.agreement}
                </Text>
              </TouchableOpacity>

              <Button
                title="Send Code"
                onPress={handleRequestOTP}
                loading={loading}
                disabled={!smsConsent}
                style={styles.button}
              />

              <Text style={styles.termsText}>{SMS_CONSENT_COPY.help}</Text>
              <Text style={styles.termsText}>
                By continuing, you agree to our{' '}
                <Text
                  style={styles.link}
                  onPress={() => Linking.openURL(appConfig.termsUrl)}
                >
                  Terms
                </Text>{' '}
                and{' '}
                <Text
                  style={styles.link}
                  onPress={() => Linking.openURL(appConfig.privacyUrl)}
                >
                  Privacy Policy
                </Text>
              </Text>
            </>
          ) : (
            // OTP Input
            <>
              <View style={styles.otpContainer}>
                {/* Single one-time-code field — mirrors the web login input.
                    A single field is what makes OS SMS autofill reliably drop
                    the WHOLE code in (segmented per-digit boxes only get the
                    first digit on iOS). textContentType/autoComplete tag it as
                    the OTP field for the above-keyboard suggestion. */}
                <TextInput
                  ref={otpRef}
                  style={[
                    styles.otpInput,
                    otpError ? styles.otpInputError : null,
                  ]}
                  value={otpCode}
                  onChangeText={handleOtpChange}
                  keyboardType="number-pad"
                  textContentType="oneTimeCode"
                  autoComplete="sms-otp"
                  maxLength={6}
                  selectTextOnFocus
                  autoFocus
                  placeholder="––––––"
                  placeholderTextColor={COLORS.lightGray}
                />
                {otpError ? (
                  <Text style={styles.errorText}>{otpError}</Text>
                ) : null}
              </View>

              {verifying ? (
                <View style={styles.verifyingContainer}>
                  <ActivityIndicator size="large" color={COLORS.primary} />
                  <Text style={styles.verifyingText}>Verifying...</Text>
                </View>
              ) : (
                <>
                  <Button
                    title="Verify Code"
                    onPress={() => handleVerifyOTP()}
                    style={styles.button}
                    disabled={otpCode.length !== 6}
                  />

                  <TouchableOpacity
                    onPress={() => {
                      setOtpSent(false)
                      setOtpCode('')
                    }}
                    style={styles.changeNumberButton}
                  >
                    <Text style={styles.changeNumberText}>
                      Change phone number
                    </Text>
                  </TouchableOpacity>
                </>
              )}

              {/* Resend OTP */}
              <View style={styles.resendContainer}>
                {resendTimer > 0 ? (
                  <Text style={styles.resendText}>
                    {codeAlreadySent
                      ? `A code was recently sent — enter it below, or request a new one in `
                      : `Resend code in `}
                    <Text style={styles.resendTimerCount}>{resendTimer}s</Text>
                  </Text>
                ) : (
                  <TouchableOpacity
                    onPress={handleResendOTP}
                    disabled={loading}
                  >
                    <Text style={styles.resendText}>
                      Didn't receive the code?{' '}
                      <Text style={styles.link}>Resend</Text>
                    </Text>
                  </TouchableOpacity>
                )}
              </View>
            </>
          )}
        </View>
      </View>
    </AuthScreenWrapper>
  )
}

const styles = StyleSheet.create({
  mainContent: {
    width: '100%',
    maxWidth: 400,
    alignSelf: 'center',
  },
  header: {
    alignItems: 'center',
    marginBottom: SPACING.xl,
  },
  logoContainer: {
    marginBottom: SPACING.lg,
  },
  logo: {
    width: 80,
    height: 80,
    borderRadius: 20,
  },
  title: {
    fontSize: TYPOGRAPHY.fontSize['2xl'],
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
    textAlign: 'center',
    marginBottom: SPACING.xs,
  },
  subtitle: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center',
    paddingHorizontal: SPACING.lg,
  },
  formContainer: {
    marginBottom: SPACING.lg,
  },
  inputContainer: {
    marginBottom: SPACING.lg,
  },
  phoneInputWrapper: {
    flexDirection: 'row',
    borderWidth: 2,
    borderColor: COLORS.primary,
    borderRadius: RADIUS.full,
    overflow: 'hidden',
    backgroundColor: COLORS.white,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  countryCode: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingLeft: SPACING.md,
    paddingRight: SPACING.sm,
    backgroundColor: COLORS.background,
    borderRightWidth: 1,
    borderRightColor: COLORS.lightGray,
    gap: 6,
  },
  flagEmoji: {
    fontSize: 18,
  },
  countryCodeText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.medium as TextStyle['fontWeight'],
    color: COLORS.text,
  },
  phoneInput: {
    flex: 1,
    paddingLeft: SPACING.sm,
    paddingRight: SPACING.md,
    paddingVertical: SPACING.lg,
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.medium as TextStyle['fontWeight'],
    color: COLORS.text,
  },
  otpContainer: {
    marginBottom: SPACING.lg,
  },
  otpInput: {
    height: 64,
    borderWidth: 2,
    borderColor: COLORS.lightGray,
    borderRadius: RADIUS.lg,
    textAlign: 'center',
    fontSize: TYPOGRAPHY.fontSize['2xl'],
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
    letterSpacing: 12,
    color: COLORS.text,
    backgroundColor: COLORS.white,
    marginTop: SPACING.md,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.03,
    shadowRadius: 4,
    elevation: 1,
  },
  otpInputError: {
    borderColor: COLORS.danger,
  },
  phoneInputError: {
    borderColor: COLORS.danger,
  },
  errorText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.danger,
    marginTop: SPACING.sm,
    marginLeft: SPACING.md,
  },
  optedOutBlock: {
    marginTop: SPACING.md,
    paddingHorizontal: SPACING.md,
  },
  optedOutText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.text,
    lineHeight: 20,
  },
  optedOutButton: {
    marginTop: SPACING.sm,
    alignSelf: 'flex-start',
  },
  button: {
    marginTop: SPACING.md,
  },
  promiseRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: COLORS.background,
    borderRadius: RADIUS.md,
    paddingVertical: SPACING.sm,
    paddingHorizontal: SPACING.md,
    marginTop: SPACING.lg,
  },
  promiseIcon: {
    marginRight: SPACING.sm,
    marginTop: 1,
  },
  promiseText: {
    flex: 1,
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.text,
    fontWeight: TYPOGRAPHY.fontWeight.medium as TextStyle['fontWeight'],
    lineHeight: 20,
  },
  consentRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginTop: SPACING.md,
    paddingHorizontal: SPACING.xs,
  },
  consentBox: {
    marginRight: SPACING.sm,
    marginTop: 1,
  },
  consentLabel: {
    flex: 1,
    fontSize: TYPOGRAPHY.fontSize.xs,
    color: COLORS.textLight,
    lineHeight: 18,
  },
  termsText: {
    fontSize: TYPOGRAPHY.fontSize.xs,
    color: COLORS.textLight,
    textAlign: 'center',
    marginTop: SPACING.lg,
    lineHeight: 18,
  },
  link: {
    color: COLORS.primary,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
  },
  resendContainer: {
    alignItems: 'center',
    marginTop: SPACING.lg,
  },
  resendTimerCount: {
    color: COLORS.primary,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
  },
  resendText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
  },
  changeNumberButton: {
    alignItems: 'center',
    marginTop: SPACING.md,
  },
  changeNumberText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.primary,
    fontWeight: TYPOGRAPHY.fontWeight.medium as TextStyle['fontWeight'],
  },
  verifyingContainer: {
    alignItems: 'center',
    paddingVertical: SPACING.xl,
  },
  verifyingText: {
    marginTop: SPACING.md,
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
  },
})
