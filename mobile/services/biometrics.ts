import * as LocalAuthentication from 'expo-local-authentication'
import * as SecureStore from 'expo-secure-store'
import AsyncStorage from '@react-native-async-storage/async-storage'
import { notify } from './errorReporting'

const BIOMETRIC_SETTINGS_KEY = 'biometric_auth_enabled'
const SECURE_CREDENTIALS_KEY = 'user_credentials'

class BiometricService {
  private static instance: BiometricService

  private constructor() {}

  static getInstance(): BiometricService {
    if (!BiometricService.instance) {
      BiometricService.instance = new BiometricService()
    }
    return BiometricService.instance
  }

  async isBiometricSupported(): Promise<boolean> {
    try {
      const compatible = await LocalAuthentication.hasHardwareAsync()
      if (!compatible) return false

      const enrolled = await LocalAuthentication.isEnrolledAsync()
      return enrolled
    } catch (error) {
      notify(error, 'biometrics.check-support')
      return false
    }
  }

  async getBiometricType(): Promise<string> {
    try {
      const types =
        await LocalAuthentication.supportedAuthenticationTypesAsync()

      if (
        types.includes(
          LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION
        )
      ) {
        return 'Face ID'
      } else if (
        types.includes(LocalAuthentication.AuthenticationType.FINGERPRINT)
      ) {
        return 'Touch ID'
      } else if (types.includes(LocalAuthentication.AuthenticationType.IRIS)) {
        return 'Iris Scanner'
      }

      return 'Biometric'
    } catch {
      // benign: label fallback
      return 'Biometric'
    }
  }

  async authenticate(reason?: string): Promise<boolean> {
    try {
      const biometricType = await this.getBiometricType()
      const result = await LocalAuthentication.authenticateAsync({
        promptMessage: reason || `Authenticate with ${biometricType}`,
        fallbackLabel: 'Use Passcode',
        disableDeviceFallback: false,
        cancelLabel: 'Cancel',
      })

      return result.success
    } catch (error) {
      notify(error, 'biometrics.authenticate')
      return false
    }
  }

  async isBiometricAuthEnabled(): Promise<boolean> {
    try {
      const enabled = await AsyncStorage.getItem(BIOMETRIC_SETTINGS_KEY)
      return enabled === 'true'
    } catch {
      // benign: an unreadable setting means disabled
      return false
    }
  }

  async setBiometricAuthEnabled(enabled: boolean): Promise<void> {
    try {
      await AsyncStorage.setItem(BIOMETRIC_SETTINGS_KEY, enabled.toString())
    } catch (error) {
      notify(error, 'biometrics.save-setting')
    }
  }

  async saveSecureCredentials(email: string, password: string): Promise<void> {
    try {
      const credentials = JSON.stringify({ email, password })
      await SecureStore.setItemAsync(SECURE_CREDENTIALS_KEY, credentials)
    } catch (error) {
      notify(error, 'biometrics.save-credentials')
      throw error
    }
  }

  async getSecureCredentials(): Promise<{
    email: string
    password: string
  } | null> {
    try {
      const credentials = await SecureStore.getItemAsync(SECURE_CREDENTIALS_KEY)
      if (credentials) {
        return JSON.parse(credentials)
      }
      return null
    } catch (error) {
      notify(error, 'biometrics.read-credentials')
      return null
    }
  }

  async clearSecureCredentials(): Promise<void> {
    try {
      await SecureStore.deleteItemAsync(SECURE_CREDENTIALS_KEY)
    } catch (error) {
      notify(error, 'biometrics.clear-credentials')
    }
  }

  async authenticateForQuickLogin(): Promise<{
    email: string
    password: string
  } | null> {
    try {
      // Check if biometric auth is enabled
      const isEnabled = await this.isBiometricAuthEnabled()
      if (!isEnabled) return null

      // Check if biometric is supported
      const isSupported = await this.isBiometricSupported()
      if (!isSupported) return null

      // Authenticate user
      const authenticated = await this.authenticate('Sign in to Made It Home')
      if (!authenticated) return null

      // Get stored credentials
      const credentials = await this.getSecureCredentials()
      return credentials
    } catch (error) {
      notify(error, 'biometrics.quick-login')
      return null
    }
  }

  async setupBiometricAuth(email: string, password: string): Promise<boolean> {
    try {
      // Check if biometric is supported
      const isSupported = await this.isBiometricSupported()
      if (!isSupported) {
        throw new Error(
          'Biometric authentication is not available on this device'
        )
      }

      // Authenticate to confirm
      const biometricType = await this.getBiometricType()
      const authenticated = await this.authenticate(
        `Enable ${biometricType} for quick login`
      )

      if (!authenticated) {
        return false
      }

      // Save credentials securely
      await this.saveSecureCredentials(email, password)
      await this.setBiometricAuthEnabled(true)

      return true
    } catch (error) {
      notify(error, 'biometrics.setup')
      throw error
    }
  }

  async disableBiometricAuth(): Promise<void> {
    try {
      await this.clearSecureCredentials()
      await this.setBiometricAuthEnabled(false)
    } catch (error) {
      notify(error, 'biometrics.disable')
      throw error
    }
  }
}

export default BiometricService.getInstance()
