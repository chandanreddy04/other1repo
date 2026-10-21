/**
 * Form validation utilities for consistent validation across the app
 * Supports phone number validation with E164 format
 */

import { parsePhoneNumber } from 'libphonenumber-js'

/**
 * Phone number validation patterns
 */
export const PHONE_PATTERNS = {
  E164: /^\+[1-9]\d{1,14}$/,
  US: /^(\+1)?[2-9]\d{2}[2-9]\d{2}\d{4}$/,
  DIGITS_ONLY: /^\d+$/,
}

/**
 * Common validation patterns
 */
export const PATTERNS = {
  EMAIL: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
  URL: /^https?:\/\/(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+.~#?&//=]*)$/,
  ALPHANUMERIC: /^[a-zA-Z0-9]+$/,
  ALPHA_ONLY: /^[a-zA-Z]+$/,
  NUMERIC_ONLY: /^\d+$/,
  NO_SPECIAL_CHARS: /^[a-zA-Z0-9\s]+$/,
  USERNAME: /^[a-zA-Z0-9_-]{3,16}$/,
  ZIP_CODE: /^\d{5}(-\d{4})?$/,
}

/**
 * Format phone number for display (from E164 to readable format)
 */
export function formatPhoneNumber(phone: string): string {
  if (!phone) return ''

  try {
    // Try to parse the phone number using libphonenumber-js
    const phoneNumber = parsePhoneNumber(phone)

    if (phoneNumber) {
      // Format in NATIONAL format for the number's country
      // This gives us the most natural format for that country
      // e.g., US: (555) 123-4567, UK: 020 1234 5678, etc.
      return phoneNumber.formatNational()
    }
  } catch (error) {
    // benign: If parsing fails, try basic formatting
  }

  // Fallback for US numbers if libphonenumber-js fails
  const cleaned = phone.replace(/[^\d+]/g, '')

  // Handle E164 format (+1XXXXXXXXXX)
  if (cleaned.startsWith('+1') && cleaned.length === 12) {
    const areaCode = cleaned.substring(2, 5)
    const middle = cleaned.substring(5, 8)
    const last = cleaned.substring(8)
    return `(${areaCode}) ${middle}-${last}`
  }

  // Handle 10-digit US number
  if (cleaned.length === 10) {
    const areaCode = cleaned.substring(0, 3)
    const middle = cleaned.substring(3, 6)
    const last = cleaned.substring(6)
    return `(${areaCode}) ${middle}-${last}`
  }

  // Return original if can't format
  return phone
}

/**
 * Convert phone number to E164 format for storage
 */
export function toE164Format(
  phone: string,
  defaultCountryCode: string = '+1'
): string {
  // Remove all non-digit characters
  const digits = phone.replace(/\D/g, '')

  // If already has country code (11 digits for US)
  if (digits.length === 11 && digits.startsWith('1')) {
    return `+${digits}`
  }

  // If 10 digits (US number without country code)
  if (digits.length === 10) {
    return `${defaultCountryCode}${digits}`
  }

  // If already in E164 format
  if (phone.startsWith('+') && PHONE_PATTERNS.E164.test(phone)) {
    return phone
  }

  // Return with default country code
  return `${defaultCountryCode}${digits}`
}

/**
 * Validate phone number
 */
export function validatePhoneNumber(phone: string): string | null {
  if (!phone || phone.trim() === '') {
    return 'Phone number is required'
  }

  // Remove formatting for validation
  const digits = phone.replace(/\D/g, '')

  // Check if it's a valid US phone number (10 or 11 digits)
  if (
    digits.length === 10 ||
    (digits.length === 11 && digits.startsWith('1'))
  ) {
    return null
  }

  // Check if it's already in E164 format
  if (PHONE_PATTERNS.E164.test(phone)) {
    return null
  }

  return 'Please enter a valid phone number'
}
