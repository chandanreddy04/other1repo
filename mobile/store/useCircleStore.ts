import { create } from 'zustand'
import { Linking } from 'react-native'
import * as Contacts from 'expo-contacts'
import api from '../services/api'
import contactsService, { PhoneContact } from '../services/contacts'
import { CircleOfTrustSettings, CircleOfTrustMember } from '../types'
import { notify } from '../services/errorReporting'

// Extended interface for the store to include phone contact association
export interface ExtendedCircleOfTrustMember extends CircleOfTrustMember {
  phone_contact?: PhoneContact // Associated phone contact if imported
}

interface CircleState {
  // Circle of Trust
  circleOfTrust: ExtendedCircleOfTrustMember[]
  circleSettings: CircleOfTrustSettings

  // Phone contacts
  phoneContacts: PhoneContact[]

  // UI state
  isLoading: boolean
  isLoadingPhoneContacts: boolean
  // True once the circle has been fetched at least once — an empty list is
  // only meaningful ("your circle IS empty") after a real load, never on the
  // initial [] state (e.g. a cold deep-link into the live session screen).
  circleLoaded: boolean
  error: string | null
  hasContactsPermission: boolean
  hasLimitedAccess: boolean

  // Actions
  loadCircleOfTrust: () => Promise<void>
  loadCircleSettings: () => Promise<void>
  loadPhoneContacts: () => Promise<void>

  // Circle of Trust actions
  addToCircle: (member: {
    nickname: string
    contact_phone?: string
    contact_email?: string
  }) => Promise<CircleOfTrustMember>

  removeFromCircle: (memberId: string) => Promise<void>
  updateCircleSettings: (
    settings: Partial<CircleOfTrustSettings>
  ) => Promise<void>

  // Permission actions
  checkContactsPermission: () => Promise<boolean>
  requestContactsPermission: () => Promise<boolean>
  refreshContactsPermission: () => Promise<boolean>
  updateContactAccess: () => Promise<void>

  // Utility actions
  findPhoneContactByInfo: (
    phone?: string,
    email?: string
  ) => PhoneContact | null
  clearError: () => void
  reset: () => void
}

const initialCircleSettings: CircleOfTrustSettings = {
  enabled: true,
  auto_invite_enabled: false,
  max_contacts: 3, // Match backend configuration
  require_mutual_trust: false,
}

export const useCircleStore = create<CircleState>((set, get) => ({
  // Initial state
  circleOfTrust: [],
  circleSettings: initialCircleSettings,
  phoneContacts: [],
  isLoading: false,
  isLoadingPhoneContacts: false,
  circleLoaded: false,
  error: null,
  hasContactsPermission: false,
  hasLimitedAccess: false,

  // Load Circle of Trust members
  loadCircleOfTrust: async () => {
    set({ isLoading: true, error: null })
    try {
      const circle = await api.getCircleOfTrust()
      // Map backend fields to frontend fields
      const mappedCircle = circle.map(member => ({
        ...member,
        trust_level:
          member.priority_level === 'primary'
            ? 'high'
            : member.priority_level === 'secondary'
              ? 'medium'
              : 'low',
        contact_phone: member.contact_phone_number,
        added_at: member.created_at || member.added_at,
      }))
      set({ circleOfTrust: mappedCircle, circleLoaded: true })
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : 'Failed to load Circle of Trust'
      set({ error: message })
    } finally {
      set({ isLoading: false })
    }
  },

  // Load Circle of Trust settings
  loadCircleSettings: async () => {
    try {
      const settings = await api.getCircleOfTrustSettings()
      set({ circleSettings: settings })
    } catch (error) {
      notify(error, 'contacts.load-settings')
      // Use default settings if loading fails
      set({ circleSettings: initialCircleSettings })
    }
  },

  // Load phone contacts
  loadPhoneContacts: async () => {
    set({ isLoadingPhoneContacts: true, error: null })
    try {
      const hasPermission = await get().checkContactsPermission()
      if (!hasPermission) {
        set({ phoneContacts: [], hasContactsPermission: false })
        return
      }

      const contacts = await contactsService.getContacts()
      set({ phoneContacts: contacts, hasContactsPermission: true })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to load phone contacts'
      set({ error: message })
    } finally {
      set({ isLoadingPhoneContacts: false })
    }
  },

  // Add member to Circle of Trust
  addToCircle: async member => {
    set({ isLoading: true, error: null })
    try {
      const created = await api.addToCircleOfTrust(member)
      await get().loadCircleOfTrust()
      return created
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : 'Failed to add to Circle of Trust'
      set({ error: message })
      throw error
    } finally {
      set({ isLoading: false })
    }
  },

  // Remove member from Circle of Trust
  removeFromCircle: async memberId => {
    set({ isLoading: true, error: null })
    try {
      await api.removeFromCircleOfTrust(memberId)
      await get().loadCircleOfTrust()
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : 'Failed to remove from Circle of Trust'
      set({ error: message })
      throw error
    } finally {
      set({ isLoading: false })
    }
  },

  // Update Circle of Trust settings
  updateCircleSettings: async settings => {
    set({ isLoading: true, error: null })
    try {
      const updatedSettings = await api.updateCircleOfTrustSettings(settings)
      set({ circleSettings: updatedSettings })
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : 'Failed to update Circle of Trust settings'
      set({ error: message })
      throw error
    } finally {
      set({ isLoading: false })
    }
  },

  // Check contacts permission
  checkContactsPermission: async () => {
    try {
      const permissionResponse = await Contacts.getPermissionsAsync()
      const hasPermission = permissionResponse.status === 'granted'
      const isLimited = permissionResponse.accessPrivileges === 'limited'
      set({ hasContactsPermission: hasPermission, hasLimitedAccess: isLimited })
      return hasPermission
    } catch (err) {
      notify(err, 'contacts.check-permission')
      set({ hasContactsPermission: false, hasLimitedAccess: false })
      return false
    }
  },

  // Request contacts permission
  requestContactsPermission: async () => {
    try {
      const hasPermission = await contactsService.ensurePermission()
      set({ hasContactsPermission: hasPermission })
      return hasPermission
    } catch (err) {
      notify(err, 'contacts.check-permission-quick')
      set({ hasContactsPermission: false })
      return false
    }
  },

  // Refresh contacts - reload the contact list from the device
  refreshContactsPermission: async () => {
    set({ error: null })
    try {
      const permissionResponse = await Contacts.getPermissionsAsync()

      if (permissionResponse.status !== 'granted') {
        set({ hasContactsPermission: false, hasLimitedAccess: false })
        return false
      }

      const isLimited = permissionResponse.accessPrivileges === 'limited'
      set({
        isLoadingPhoneContacts: true,
        hasLimitedAccess: isLimited,
      })
      const { data } = await Contacts.getContactsAsync({
        fields: [
          Contacts.Fields.Name,
          Contacts.Fields.PhoneNumbers,
          Contacts.Fields.Emails,
          Contacts.Fields.Image,
        ],
        sort: Contacts.SortTypes.FirstName,
      })

      // Process the contacts
      const processedContacts = data
        .filter(
          contact =>
            contact.id &&
            contact.name &&
            ((contact.phoneNumbers?.length ?? 0) > 0 ||
              (contact.emails?.length ?? 0) > 0)
        )
        .map(contact => ({
          id: contact.id!,
          name: contact.name || 'Unknown',
          phoneNumbers:
            contact.phoneNumbers
              ?.map(phone =>
                contactsService.normalizePhoneNumber(phone.number || '')
              )
              .filter(Boolean) || [],
          emails:
            contact.emails
              ?.map(email => email.email?.toLowerCase() || '')
              .filter(Boolean) || [],
          imageAvailable: contact.imageAvailable || false,
          image: contact.image?.uri ? { uri: contact.image.uri } : undefined,
        }))
        .sort((a, b) => a.name.localeCompare(b.name))

      set({
        phoneContacts: processedContacts,
        hasContactsPermission: true,
      })
      return true
    } catch (error) {
      notify(error, 'contacts.refresh')
      const message =
        error instanceof Error ? error.message : 'Failed to refresh contacts'
      set({ error: message })
      return false
    } finally {
      set({ isLoadingPhoneContacts: false })
    }
  },

  // Open app settings to update contact access.
  // presentAccessPickerAsync() renders blank on iOS 26 — use Settings instead.
  updateContactAccess: async () => {
    await Linking.openSettings()
  },

  // Find phone contact by info
  findPhoneContactByInfo: (phone, email) => {
    const { phoneContacts } = get()

    return (
      phoneContacts.find(contact => {
        if (phone) {
          return contact.phoneNumbers.some(
            contactPhone =>
              contactPhone.replace(/\D/g, '') === phone.replace(/\D/g, '')
          )
        }
        if (email) {
          return contact.emails.some(
            contactEmail => contactEmail.toLowerCase() === email.toLowerCase()
          )
        }
        return false
      }) || null
    )
  },

  // Clear error
  clearError: () => {
    set({ error: null })
  },

  // Reset store
  reset: () => {
    set({
      circleOfTrust: [],
      circleSettings: initialCircleSettings,
      phoneContacts: [],
      isLoading: false,
      isLoadingPhoneContacts: false,
      circleLoaded: false,
      error: null,
      hasContactsPermission: false,
    })
  },
}))
