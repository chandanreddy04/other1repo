/**
 * One profile page, two states (Commit 13, owner decision — merge of the
 * old standalone in-app editor screen and the auth-flow name-capture
 * screen it replaces):
 *
 *   'required' — post-signup / a 428 "name missing" redirect. Name is
 *     mandatory, there's no back button and no photo picker. Save ->
 *     POST the name -> `router.replace('/(auth)/onboarding')`, exactly
 *     as the old auth-flow screen did.
 *
 *   'edit' — the normal in-app editor, reached from the Account tab.
 *     Photo picker + name, read-only phone. Save -> upload the photo (if
 *     changed) then update the user -> `router.back()`.
 *
 * `profileScreenMode()` (utils/profileScreenMode.ts) decides which state
 * renders, from the `?required=1` param or the user's own `full_name`.
 *
 * Related: app/account/_layout.tsx, app/(tabs)/index.tsx (428 redirect),
 * app/(auth)/login.tsx (is_new_user redirect), app/(auth)/onboarding.tsx.
 */
import { useState } from 'react'
import { notify } from '../../services/errorReporting'
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ScrollView,
  SafeAreaView,
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  TextStyle,
} from 'react-native'
import { Stack, useLocalSearchParams, useRouter } from 'expo-router'
import { Ionicons } from '@expo/vector-icons'
import { LinearGradient } from 'expo-linear-gradient'
import {
  COLORS,
  SPACING,
  RADIUS,
  TYPOGRAPHY,
  resolveUrl,
} from '../../constants'
import { useAuthStore } from '../../store/useAuthStore'
import { formatPhoneNumber } from '../../utils/validation'
import api from '../../services/api'
import { useImagePicker } from '../../hooks/useImagePicker'
import { settingsScreenOptions } from '../../utils/screenOptions'
import { profileScreenMode } from '../../utils/profileScreenMode'
import { AuthScreenWrapper } from '../../components/AuthScreenWrapper'
import { Button } from '../../components/ui'
import toast from '../../utils/toast'

export default function AccountProfileScreen() {
  const router = useRouter()
  const { required } = useLocalSearchParams<{ required?: string }>()
  const user = useAuthStore(state => state.user)
  const setUser = useAuthStore(state => state.setUser)
  // Decided once at mount: `setUser` after a required-mode save gives the
  // user a name, and a recomputed mode would flash the edit layout for a
  // render before the replace into onboarding lands.
  const [mode] = useState(() => profileScreenMode(user, required))

  const [saving, setSaving] = useState(false)
  const { photo: pickedPhoto, showPicker: handlePhotoOptions } = useImagePicker(
    { aspect: [1, 1] }
  )
  const profilePhoto =
    pickedPhoto?.uri ||
    (user?.profile_photo_url ? resolveUrl(user.profile_photo_url) : null)
  const [fullName, setFullName] = useState(user?.full_name || '')
  const [error, setError] = useState('')

  const validate = () => {
    if (!fullName.trim()) {
      setError(
        mode === 'required' ? 'Please enter your name' : 'Full name is required'
      )
      return false
    }
    setError('')
    return true
  }

  const handleSave = async () => {
    if (!validate()) return

    setSaving(true)
    try {
      let updatedUser
      if (mode === 'edit' && pickedPhoto?.uri) {
        updatedUser = await api.uploadProfilePhoto(pickedPhoto.uri)
      }
      updatedUser = await api.updateUser({ full_name: fullName })
      setUser(updatedUser)

      if (mode === 'required') {
        router.replace('/(auth)/onboarding')
      } else {
        router.back()
      }
    } catch (err) {
      notify(
        err instanceof Error ? err : new Error(String(err)),
        'account-profile'
      )
      toast.error(
        err instanceof Error ? err.message : 'Failed to update profile'
      )
    } finally {
      setSaving(false)
    }
  }

  if (mode === 'required') {
    return (
      <>
        {/* No back button — the user must finish naming themselves before
            continuing into onboarding, same as the old auth-flow screen. */}
        <Stack.Screen options={{ headerShown: false }} />
        <AuthScreenWrapper withKeyboard scrollable>
          <View style={styles.mainContent}>
            <View style={styles.header}>
              <View style={styles.logoContainer}>
                <LinearGradient
                  colors={COLORS.gradients.primary}
                  style={styles.logo}
                >
                  <Ionicons name="heart" size={40} color="white" />
                </LinearGradient>
              </View>
              <Text style={styles.title}>What do your friends call you?</Text>
            </View>

            <View style={styles.formContainer}>
              <TextInput
                style={[
                  styles.requiredInput,
                  error && styles.requiredInputError,
                ]}
                value={fullName}
                onChangeText={text => {
                  setFullName(text)
                  if (error) setError('')
                }}
                placeholder="Enter your name"
                placeholderTextColor={COLORS.gray}
                autoFocus
                autoCapitalize="words"
                autoCorrect={false}
              />
              {error && <Text style={styles.errorText}>{error}</Text>}
            </View>

            <Button
              title="Continue"
              onPress={handleSave}
              loading={saving}
              style={styles.button}
            />

            <View style={styles.infoSection}>
              <View style={styles.infoItem}>
                <Ionicons
                  name="shield-checkmark"
                  size={20}
                  color={COLORS.primary}
                />
                <Text style={styles.infoText}>
                  Your information is secure and only shared with your Circle
                  of Trust
                </Text>
              </View>
            </View>
          </View>
        </AuthScreenWrapper>
      </>
    )
  }

  return (
    <SafeAreaView style={styles.editContainer}>
      <Stack.Screen options={settingsScreenOptions('Edit Profile', router)} />

      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={{ flex: 1 }}
      >
        <ScrollView
          showsVerticalScrollIndicator={false}
          contentContainerStyle={styles.editScrollContent}
        >
          <View style={styles.photoSection}>
            <TouchableOpacity
              onPress={handlePhotoOptions}
              style={styles.photoContainer}
            >
              {profilePhoto ? (
                <Image
                  source={{ uri: profilePhoto }}
                  style={styles.profilePhoto}
                />
              ) : (
                <View style={styles.photoPlaceholder}>
                  <Ionicons name="person" size={50} color={COLORS.gray} />
                </View>
              )}
              <View style={styles.photoEditBadge}>
                <Ionicons name="camera" size={16} color={COLORS.white} />
              </View>
            </TouchableOpacity>
            <Text style={styles.photoHint}>Tap to change photo</Text>
            <Text style={styles.photoDisclosure}>
              Your photo will be visible to your Circle of Trust
            </Text>
          </View>

          <View style={styles.formSection}>
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Full Name</Text>
              <TextInput
                style={[styles.editInput, error && styles.editInputError]}
                value={fullName}
                onChangeText={text => {
                  setFullName(text)
                  if (error) setError('')
                }}
                placeholder="Enter your full name"
                placeholderTextColor={COLORS.gray}
              />
              {error && <Text style={styles.errorText}>{error}</Text>}
            </View>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Phone Number</Text>
              <View style={styles.readOnlyField}>
                <Text style={styles.readOnlyText}>
                  {user?.phone_number
                    ? formatPhoneNumber(user.phone_number)
                    : ''}
                </Text>
                <Ionicons name="lock-closed" size={16} color={COLORS.gray} />
              </View>
              <Text style={styles.hintText}>
                Log in with a different number to change
              </Text>
            </View>
          </View>

          <View style={styles.buttonContainer}>
            <TouchableOpacity
              style={[styles.saveButton, saving && styles.buttonDisabled]}
              onPress={handleSave}
              disabled={saving}
            >
              {saving ? (
                <ActivityIndicator color={COLORS.white} />
              ) : (
                <Text style={styles.saveButtonText}>Save Changes</Text>
              )}
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.cancelButton}
              onPress={() => router.back()}
            >
              <Text style={styles.cancelButtonText}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  errorText: {
    fontSize: 12,
    color: COLORS.danger,
    marginTop: SPACING.xs,
  },

  // 'required' state (from the old auth-flow name-capture screen)
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
    justifyContent: 'center',
    alignItems: 'center',
  },
  title: {
    fontSize: TYPOGRAPHY.fontSize['2xl'],
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
    textAlign: 'center',
    paddingHorizontal: SPACING.lg,
  },
  formContainer: {
    marginBottom: SPACING.lg,
  },
  requiredInput: {
    borderWidth: 2,
    borderColor: COLORS.primary,
    borderRadius: RADIUS.full,
    paddingHorizontal: SPACING.xl,
    paddingVertical: SPACING.lg,
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.medium as TextStyle['fontWeight'],
    color: COLORS.text,
    backgroundColor: COLORS.white,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  requiredInputError: {
    borderColor: COLORS.danger,
    backgroundColor: '#FFF5F5',
  },
  button: {
    marginBottom: SPACING.lg,
  },
  infoSection: {
    marginTop: SPACING.xs,
  },
  infoItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  infoText: {
    marginLeft: SPACING.sm,
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    lineHeight: 20,
    textAlign: 'center',
  },

  // 'edit' state (from the old standalone in-app editor screen)
  editContainer: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  editScrollContent: {
    paddingBottom: SPACING['2xl'],
  },
  photoSection: {
    alignItems: 'center',
    paddingVertical: SPACING.xl,
    backgroundColor: COLORS.white,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.lightGray,
  },
  photoContainer: {
    position: 'relative',
    marginBottom: SPACING.sm,
  },
  profilePhoto: {
    width: 120,
    height: 120,
    borderRadius: 60,
    borderWidth: 3,
    borderColor: COLORS.primary,
  },
  photoPlaceholder: {
    width: 120,
    height: 120,
    borderRadius: 60,
    backgroundColor: COLORS.lightGray,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 3,
    borderColor: COLORS.primary,
  },
  photoEditBadge: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    backgroundColor: COLORS.primary,
    width: 36,
    height: 36,
    borderRadius: 18,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 3,
    borderColor: COLORS.white,
  },
  photoHint: {
    fontSize: 14,
    color: COLORS.textLight,
  },
  photoDisclosure: {
    fontSize: 12,
    color: COLORS.gray,
    marginTop: SPACING.xs,
  },
  formSection: {
    backgroundColor: COLORS.white,
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.xl,
    marginTop: SPACING.md,
  },
  inputGroup: {
    marginBottom: SPACING.lg,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: COLORS.text,
    marginBottom: SPACING.xs,
  },
  editInput: {
    backgroundColor: COLORS.background,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    fontSize: 16,
    color: COLORS.text,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  editInputError: {
    borderColor: COLORS.danger,
  },
  readOnlyField: {
    backgroundColor: COLORS.lightGray,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  readOnlyText: {
    fontSize: 16,
    color: COLORS.textLight,
  },
  hintText: {
    fontSize: 12,
    color: COLORS.gray,
    marginTop: SPACING.xs,
  },
  buttonContainer: {
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.xl,
  },
  saveButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.full,
    paddingVertical: SPACING.md,
    alignItems: 'center',
    marginBottom: SPACING.md,
  },
  saveButtonText: {
    color: COLORS.white,
    fontSize: 16,
    fontWeight: '700',
  },
  cancelButton: {
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.full,
    paddingVertical: SPACING.md,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: COLORS.lightGray,
  },
  cancelButtonText: {
    color: COLORS.textLight,
    fontSize: 16,
    fontWeight: '600',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
})
