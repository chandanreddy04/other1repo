import { useState, useEffect, useCallback } from 'react'
import { Alert, Platform, ActionSheetIOS } from 'react-native'
import { useFocusEffect } from 'expo-router'
import { useCircleStore } from '../store/useCircleStore'
import { useAuthStore } from '../store/useAuthStore'
import contactsService, { PhoneContact } from '../services/contacts'
import { ExtendedCircleOfTrustMember } from '../store/useCircleStore'
import toast from '../utils/toast'
import { openSmsOrFallback } from '../utils/sms'
import { APP_INFO, CONTACT_CONFIG } from '../constants/config'
import { ApiError } from '../services/api'
import { usePermissionRequirements } from './usePermissionRequirements'
import { shouldPromptContacts } from '../utils/contactMatch'
import type { RequirementItem } from '../utils/permissionUi'
import { notify } from '../services/errorReporting'
import { getAppConfigSnapshot } from '../store/useAppConfigStore'

type ViewMode = 'overview' | 'add_contacts'

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

export function useCircleScreen() {
  const [viewMode, setViewMode] = useState<ViewMode>('overview')
  const [showPermissionModal, setShowPermissionModal] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const { user } = useAuthStore()

  const {
    circleOfTrust,
    circleSettings,
    phoneContacts,
    isLoading,
    isLoadingPhoneContacts,
    error,
    hasContactsPermission,

    loadCircleOfTrust,
    loadCircleSettings,
    loadPhoneContacts,
    addToCircle,
    removeFromCircle,
    checkContactsPermission,
    requestContactsPermission,
    refreshContactsPermission,
    updateContactAccess,
    hasLimitedAccess,
    clearError,
  } = useCircleStore()

  // Persistent "add contacts" nudge — shown ONLY when it would actually help:
  // there's still room in the circle AND nothing we can see on the phone could
  // grow it (contacts denied, iOS "Limited" hiding people, or every visible
  // contact is already added). Reads accessible contacts WITHOUT ever
  // requesting (getContactsIfPermitted), so it never triggers a cold dialog.
  const { statuses: contactsStatuses, refresh: refreshContactsStatus } =
    usePermissionRequirements(['contacts'])
  const [accessibleContacts, setAccessibleContacts] = useState<PhoneContact[]>(
    []
  )
  const refreshAccessibleContacts = useCallback(async () => {
    try {
      setAccessibleContacts(await contactsService.getContactsIfPermitted())
    } catch (err) {
      notify(err, 'contacts.load-accessible')
      setAccessibleContacts([])
    }
  }, [])
  useFocusEffect(
    useCallback(() => {
      void refreshAccessibleContacts()
    }, [refreshAccessibleContacts])
  )

  const contactsStatus = contactsStatuses[0]
  const circleNumbers = circleOfTrust
    .map(m => m.contact_phone || m.contact_phone_number || '')
    .filter(Boolean)
  const promptContacts = shouldPromptContacts({
    memberCount: circleOfTrust.length,
    maxMembers: CONTACT_CONFIG.MAX_TRUSTED_CONTACTS,
    circleNumbers,
    accessibleContacts: accessibleContacts.map(c => ({
      phoneNumbers: c.phoneNumbers,
    })),
  })
  // An empty circle is a safety gap (no backup at all) → loud; otherwise it's a
  // gentle "you could add more" → quiet.
  const contactsRequirement: RequirementItem | null =
    contactsStatus && promptContacts
      ? {
          status: contactsStatus,
          severity: circleOfTrust.length === 0 ? 'warning' : 'info',
        }
      : null
  const refreshContactsRequirement = useCallback(() => {
    void refreshContactsStatus()
    void refreshAccessibleContacts()
  }, [refreshContactsStatus, refreshAccessibleContacts])

  useEffect(() => {
    initializeScreen()
  }, [])

  const initializeScreen = async () => {
    try {
      await loadCircleSettings()
      await loadCircleOfTrust()
      await checkContactsPermission()
    } catch (error: any) {
      notify(error, 'contacts.init')
    }
  }

  const handleRefresh = async () => {
    setIsRefreshing(true)
    try {
      await loadCircleSettings()
      await loadCircleOfTrust()
      if (hasContactsPermission) {
        await loadPhoneContacts()
      }
    } catch (err) {
      notify(err, 'contacts.refresh')
      toast.error('Failed to refresh data')
    } finally {
      setIsRefreshing(false)
    }
  }

  const handleRequestPermission = async () => {
    try {
      const granted = await requestContactsPermission()
      if (granted) {
        setShowPermissionModal(false)
        await loadPhoneContacts()
        setViewMode('add_contacts')
      }
    } catch (err) {
      notify(err, 'contacts.request-permission')
      toast.error('Failed to request permissions')
    }
  }

  const handleAddContacts = () => {
    if (!hasContactsPermission) {
      setShowPermissionModal(true)
      return
    }

    if (phoneContacts.length === 0) {
      loadPhoneContacts()
    }
    setViewMode('add_contacts')
  }

  const addContactAndShare = async (
    contact: PhoneContact,
    phoneNumber: string
  ) => {
    try {
      await addToCircle({
        nickname: contact.name,
        contact_phone: phoneNumber,
      })
      setViewMode('overview')

      if (!user?.circle_invite_code) {
        toast.error(
          "We couldn't create your invite link — please reopen the app and try again."
        )
        return
      }
      const inviteUrl = `${getAppConfigSnapshot().shortDomain}/c/${user.circle_invite_code}`
      const message = `Hey! Can you join my Circle of Trust on Made It Home? I check in when I'm out — if I miss one, it texts you. Accept here: ${inviteUrl}`

      await openSmsOrFallback(phoneNumber, message)
    } catch (error: any) {
      const apiError = error as ApiError
      if (apiError.code === 'blocked_opt_out') {
        showOptedOutAddDialog(contact, phoneNumber, apiError)
        return
      }
      toast.error(error.message || 'Failed to add contact')
    }
  }

  // 4a inline state — backend says this phone previously texted STOP,
  // so the invite SMS would silently fail. Offer to text them from the
  // owner's phone with a START prefill instead.
  const showOptedOutAddDialog = (
    contact: PhoneContact,
    phoneNumber: string,
    apiError: ApiError
  ) => {
    // Backend deliberately omits the opt-out timestamp; we phrase the
    // body without a date.
    // Without SMS_NUMBER configured, the "Text them" prefill would
    // tell the contact to text START to "our number" — useless — so
    // we collapse to a Cancel-only dialog in that case.
    const support = APP_INFO.SMS_NUMBER
    const body = support
      ? `${contact.name} asked us to stop texting them. They'll need to text START to ${support} before we can reach them.`
      : `${contact.name} asked us to stop texting them, so they can't be added until they opt back in.`

    const buttons: Parameters<typeof Alert.alert>[2] = [
      { text: 'Cancel', style: 'cancel' },
    ]
    if (support) {
      buttons.push({
        text: `Text ${contact.name}`,
        onPress: () => {
          const prefill = `Hey, I want to add you to my Made It Home Circle of Trust. Can you text START to ${support} so they can reach you?`
          openSmsOrFallback(phoneNumber, prefill)
        },
      })
    }
    Alert.alert(`${contact.name} opted out`, body, buttons)
  }

  const handleContactTap = (contact: PhoneContact) => {
    if (contact.phoneNumbers.length === 0) {
      toast.info(`${contact.name} doesn't have a phone number`)
      return
    }

    if (contact.phoneNumbers.length === 1) {
      addContactAndShare(contact, contact.phoneNumbers[0])
      return
    }

    showPhoneNumberPicker(contact.phoneNumbers, phone => {
      addContactAndShare(contact, phone)
    })
  }

  const handleRemoveFromCircle = async (memberId: string) => {
    try {
      await removeFromCircle(memberId)
    } catch (error: any) {
      toast.error(error.message || 'Failed to remove from Circle')
    }
  }

  const handleNudgeMember = async (member: ExtendedCircleOfTrustMember) => {
    const phone = member.contact_phone || member.contact_phone_number
    if (!user?.circle_invite_code) {
      toast.error(
        "We couldn't create your invite link — please reopen the app and try again."
      )
      return
    }
    const inviteUrl = `${getAppConfigSnapshot().shortDomain}/c/${user.circle_invite_code}`
    const message = `Hey! Still hoping you'll join my Circle of Trust — it takes a few seconds to accept: ${inviteUrl}`

    await openSmsOrFallback(phone, message)
  }

  const handleRefreshContacts = async () => {
    const success = await refreshContactsPermission()
    if (!success) {
      toast.info('Please allow access to contacts to continue')
    }
  }

  const handleUpdateContactAccess = async () => {
    await updateContactAccess()
  }

  const handleBackFromAddContacts = () => {
    setViewMode('overview')
  }

  return {
    // State
    viewMode,
    showPermissionModal,
    isRefreshing,
    user,
    circleOfTrust,
    circleSettings,
    phoneContacts,
    isLoading,
    isLoadingPhoneContacts,
    error,
    hasLimitedAccess,

    // Persistent contacts permission nudge (null when not warranted)
    contactsRequirement,
    refreshContactsRequirement,

    // Modal controls
    setShowPermissionModal,

    // Handlers
    handleRefresh,
    handleRequestPermission,
    handleAddContacts,
    handleContactTap,
    handleRemoveFromCircle,
    handleNudgeMember,
    handleRefreshContacts,
    handleUpdateContactAccess,
    handleBackFromAddContacts,
  }
}
