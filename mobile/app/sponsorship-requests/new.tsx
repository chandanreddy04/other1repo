import { useState } from 'react'
import { useAppConfig } from '../../store/useAppConfigStore'
import {
  View,
  Text,
  StyleSheet,
  TextStyle,
  SafeAreaView,
  TouchableOpacity,
  Alert,
  ActionSheetIOS,
  Platform,
} from 'react-native'
import { useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { LinearGradient } from 'expo-linear-gradient'
import { COLORS, SPACING, TYPOGRAPHY, RADIUS } from '../../constants'
import { useSubscriptionStore } from '../../store/useSubscriptionStore'
import { useCircleStore } from '../../store/useCircleStore'
import { useAuthStore } from '../../store/useAuthStore'
import { ContactSelector } from '../../components/ContactSelector'
import { ContactsPermissionModal } from '../../components/ContactsPermissionModal'
import { PhoneContact } from '../../services/contacts'
import { openSmsOrFallback } from '../../utils/sms'

type Step = 'privacy' | 'pick'

function showPhoneNumberPicker(
  phoneNumbers: string[],
  onSelect: (phone: string) => void
) {
  if (Platform.OS === 'ios') {
    ActionSheetIOS.showActionSheetWithOptions(
      {
        options: [...phoneNumbers, 'Cancel'],
        cancelButtonIndex: phoneNumbers.length,
        title: 'Select a phone number',
      },
      buttonIndex => {
        if (buttonIndex < phoneNumbers.length) {
          onSelect(phoneNumbers[buttonIndex])
        }
      }
    )
  } else {
    Alert.alert('Select a phone number', undefined, [
      ...phoneNumbers.map(phone => ({
        text: phone,
        onPress: () => onSelect(phone),
      })),
      { text: 'Cancel', style: 'cancel' as const },
    ])
  }
}

export default function RequestSponsorScreen() {
  const router = useRouter()
  const { recordGiftRequest } = useSubscriptionStore()
  const { user } = useAuthStore()
  const {
    phoneContacts,
    isLoadingPhoneContacts,
    hasContactsPermission,
    hasLimitedAccess,
    loadPhoneContacts,
    requestContactsPermission,
    updateContactAccess,
  } = useCircleStore()

  const [step, setStep] = useState<Step>('privacy')
  const [showPermissionModal, setShowPermissionModal] = useState(false)
  const appConfig = useAppConfig()

  const giftUrl = `${appConfig.shortDomain}/s/${user?.share_code}`
  const smsMessage = `Hey! I've been using Made It Home — a safety app that alerts my Circle if I miss a check-in. Would you sponsor my subscription? ${giftUrl}`

  const handleStartPick = async () => {
    if (!hasContactsPermission) {
      setShowPermissionModal(true)
      return
    }
    if (phoneContacts.length === 0) {
      await loadPhoneContacts()
    }
    setStep('pick')
  }

  const handleRequestPermission = async () => {
    const granted = await requestContactsPermission()
    if (granted) {
      setShowPermissionModal(false)
      await loadPhoneContacts()
      setStep('pick')
    }
  }

  const handleContactTap = async (contact: PhoneContact) => {
    if (contact.phoneNumbers.length === 0) {
      Alert.alert(`${contact.name} has no phone number saved.`)
      return
    }
    const send = async (phone: string) => {
      await openSmsOrFallback(phone, smsMessage)
      recordGiftRequest(phone)
      router.back()
    }
    if (contact.phoneNumbers.length === 1) {
      await send(contact.phoneNumbers[0])
    } else {
      showPhoneNumberPicker(contact.phoneNumbers, send)
    }
  }

  const handleBack = () => {
    if (step === 'pick') {
      setStep('privacy')
    } else {
      router.back()
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity onPress={handleBack}>
          <Ionicons name="arrow-back" size={24} color={COLORS.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Request Sponsorship</Text>
        <View style={{ width: 24 }} />
      </View>

      {step === 'privacy' && (
        <View style={styles.content}>
          <View style={styles.iconContainer}>
            <LinearGradient
              colors={COLORS.gradients.primary}
              style={styles.iconGradient}
            >
              <Ionicons name="gift" size={32} color={COLORS.white} />
            </LinearGradient>
          </View>

          <Text style={styles.privacyText}>
            Your sponsor won't have access to your check-in data or location.
            Only your Circle members will have access to that information
            if you miss your check-in.
          </Text>

          <TouchableOpacity
            style={styles.primaryButton}
            onPress={handleStartPick}
          >
            <LinearGradient
              colors={COLORS.gradients.primary}
              style={styles.primaryGradient}
            >
              <Ionicons name="people" size={18} color={COLORS.white} />
              <Text style={styles.primaryButtonText}>Choose a Contact</Text>
            </LinearGradient>
          </TouchableOpacity>
        </View>
      )}

      {step === 'pick' && (
        <ContactSelector
          contacts={phoneContacts}
          onContactTap={handleContactTap}
          isLoading={isLoadingPhoneContacts}
          hasLimitedAccess={hasLimitedAccess}
          onUpdateAccess={updateContactAccess}
        />
      )}

      <ContactsPermissionModal
        visible={showPermissionModal}
        onRequestPermission={handleRequestPermission}
        onSkip={() => setShowPermissionModal(false)}
        onClose={() => setShowPermissionModal(false)}
        description="We need access to your contacts so you can pick someone to send a sponsorship request to."
        items={[
          'Receive an SMS from you with a link to sponsor your subscription',
          "Your contacts won't be stored or contacted by us directly",
        ]}
      />
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.md,
  },
  headerTitle: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
    color: COLORS.text,
  },
  content: {
    flex: 1,
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.xl,
    alignItems: 'center',
  },
  iconContainer: {
    marginBottom: SPACING.xl,
  },
  iconGradient: {
    width: 80,
    height: 80,
    borderRadius: RADIUS.full,
    alignItems: 'center',
    justifyContent: 'center',
  },
  privacyText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center',
    lineHeight: 24,
    marginBottom: SPACING['2xl'],
    paddingHorizontal: SPACING.md,
  },
  primaryButton: {
    width: '100%',
    borderRadius: RADIUS.full,
    overflow: 'hidden',
  },
  primaryGradient: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACING.sm,
    paddingVertical: 16,
    borderRadius: RADIUS.full,
  },
  primaryButtonText: {
    color: COLORS.white,
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
  },
})
