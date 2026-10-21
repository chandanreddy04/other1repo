import * as Contacts from 'expo-contacts'
import toast from '../utils/toast'
import { requestPermission as requestPermissionCentral } from './permissions'
import { notify } from './errorReporting'

export interface PhoneContact {
  id: string
  name: string
  phoneNumbers: string[]
  emails: string[]
  imageAvailable: boolean
  image?: { uri: string }
}

export interface ContactsPermissionStatus {
  status: 'granted' | 'denied' | 'undetermined'
  canAskAgain: boolean
}

class ContactsService {
  private static instance: ContactsService

  private constructor() {}

  static getInstance(): ContactsService {
    if (!ContactsService.instance) {
      ContactsService.instance = new ContactsService()
    }
    return ContactsService.instance
  }

  /**
   * Check current permission status for contacts
   */
  async getPermissionStatus(): Promise<ContactsPermissionStatus> {
    try {
      const { status, canAskAgain } = await Contacts.getPermissionsAsync()
      return {
        status:
          status === Contacts.PermissionStatus.GRANTED
            ? 'granted'
            : status === Contacts.PermissionStatus.DENIED
              ? 'denied'
              : 'undetermined',
        canAskAgain,
      }
    } catch (error) {
      notify(error, 'contacts.check-permission')
      return { status: 'denied', canAskAgain: false }
    }
  }

  /**
   * Request permission to access contacts. The native request is delegated to
   * the central permission module (the only place request* runs); we re-read
   * the status here for the {status, canAskAgain} shape callers expect.
   */
  async requestPermission(): Promise<ContactsPermissionStatus> {
    try {
      await requestPermissionCentral('contacts')
      return this.getPermissionStatus()
    } catch (error) {
      notify(error, 'contacts.request-permission')
      return { status: 'denied', canAskAgain: false }
    }
  }

  /**
   * Request contacts permission - always shows the system picker on iOS
   * This allows users to change their contact selection
   */
  async requestContactsPermission(): Promise<boolean> {
    try {
      const status = await requestPermissionCentral('contacts')
      return status.sufficient
    } catch (error) {
      notify(error, 'contacts.request-permission-sufficient')
      return false
    }
  }

  /**
   * Check and request permission if needed
   */
  async ensurePermission(): Promise<boolean> {
    const currentStatus = await this.getPermissionStatus()

    if (currentStatus.status === 'granted') {
      return true
    }

    if (currentStatus.status === 'denied' && !currentStatus.canAskAgain) {
      toast.info(
        'Please enable contacts access in your device settings to import contacts'
      )
      return false
    }

    const requestResult = await this.requestPermission()
    return requestResult.status === 'granted'
  }

  /**
   * Fetch contacts from device, but ONLY if access is already granted — never
   * triggers a permission request. Used by point-of-use checks (e.g. deciding
   * whether to nudge for contacts access) that must not surprise the user with
   * a cold dialog. Returns [] when access isn't granted.
   */
  async getContactsIfPermitted(): Promise<PhoneContact[]> {
    const current = await this.getPermissionStatus()
    if (current.status !== 'granted') return []
    return this.fetchContacts()
  }

  /**
   * Fetch contacts from device, requesting permission first if needed (guided
   * flows only).
   */
  async getContacts(): Promise<PhoneContact[]> {
    const hasPermission = await this.ensurePermission()
    if (!hasPermission) {
      return []
    }
    return this.fetchContacts()
  }

  /** Read + normalize device contacts. Caller must ensure permission first. */
  private async fetchContacts(): Promise<PhoneContact[]> {
    try {
      const { data } = await Contacts.getContactsAsync({
        fields: [
          Contacts.Fields.Name,
          Contacts.Fields.PhoneNumbers,
          Contacts.Fields.Emails,
          Contacts.Fields.Image,
        ],
        sort: Contacts.SortTypes.FirstName,
      })

      return data
        .filter(
          contact =>
            // Filter out contacts without names or contact info
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
              ?.map(phone => this.normalizePhoneNumber(phone.number || ''))
              .filter(Boolean) || [],
          emails:
            contact.emails
              ?.map(email => email.email?.toLowerCase() || '')
              .filter(Boolean) || [],
          imageAvailable: contact.imageAvailable || false,
          image: contact.image?.uri ? { uri: contact.image.uri } : undefined,
        }))
        .sort((a, b) => a.name.localeCompare(b.name))
    } catch (error) {
      notify(error, 'contacts.fetch')
      toast.error('Failed to load contacts from your phone')
      return []
    }
  }

  /**
   * Search contacts by name, phone, or email
   */
  async searchContacts(query: string): Promise<PhoneContact[]> {
    const contacts = await this.getContacts()
    const searchQuery = query.toLowerCase().trim()

    if (!searchQuery) {
      return contacts
    }

    return contacts.filter(
      contact =>
        contact.name.toLowerCase().includes(searchQuery) ||
        contact.phoneNumbers.some(phone => phone.includes(searchQuery)) ||
        contact.emails.some(email => email.includes(searchQuery))
    )
  }

  /**
   * Normalize phone number for consistent formatting
   */
  normalizePhoneNumber(phoneNumber: string): string {
    // Remove all non-digit characters except +
    const cleaned = phoneNumber.replace(/[^\d+]/g, '')

    // If it starts with +1, keep it as is
    if (cleaned.startsWith('+1')) {
      return cleaned
    }

    // If it's a 10-digit US number, add +1
    if (cleaned.length === 10 && !cleaned.startsWith('+')) {
      return `+1${cleaned}`
    }

    // If it's an 11-digit number starting with 1, add +
    if (cleaned.length === 11 && cleaned.startsWith('1')) {
      return `+${cleaned}`
    }

    return cleaned
  }

  /**
   * Find contacts by phone number or email
   */
  async findContactsByInfo(
    phoneNumber?: string,
    email?: string
  ): Promise<PhoneContact[]> {
    const contacts = await this.getContacts()

    return contacts.filter(contact => {
      if (phoneNumber) {
        const normalizedSearch = this.normalizePhoneNumber(phoneNumber)
        return contact.phoneNumbers.some(phone => phone === normalizedSearch)
      }

      if (email) {
        return contact.emails.some(
          contactEmail => contactEmail.toLowerCase() === email.toLowerCase()
        )
      }

      return false
    })
  }

  /**
   * Get display name for contact info
   */
  getDisplayName(phoneNumber?: string, email?: string, name?: string): string {
    if (name) return name
    if (phoneNumber) return phoneNumber
    if (email) return email
    return 'Unknown Contact'
  }
}

export default ContactsService.getInstance()
