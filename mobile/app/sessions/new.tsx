import React from 'react'
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
  Switch,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { LinearGradient } from 'expo-linear-gradient'
import { COLORS, SPACING, RADIUS, TYPOGRAPHY, SHADOWS } from '../../constants'
import { formatTime } from '../../utils/dateFormatting'
import { getCircleMemberDisplayName } from '../../utils/circleMemberName'
import { ModalHeader } from '../../components/ModalHeader'
import { useCreateSession } from '../../hooks/useCreateSession'
import { loadNativeModule } from '../../services/nativeModules'
import { usePermissionRequirements } from '../../hooks/usePermissionRequirements'
import { PermissionRequirements } from '../../components/PermissionRequirements'
import { sessionRequirementItems } from '../../utils/permissionUi'

// Native OS time picker (rotary/spinner, like the alarm app). Lazy + cached:
// a build missing the native side degrades to the ± buttons alone.
function loadDateTimePicker() {
  return loadNativeModule<
    typeof import('@react-native-community/datetimepicker')
  >(
    '@react-native-community/datetimepicker',
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    () => require('@react-native-community/datetimepicker')
  )
}

export default function NewSessionScreen() {
  const {
    destination,
    expectedReturnTime,
    outfitPhoto,
    locationSharing,
    errors,
    inputFocused,
    isLoading,
    activeMembers,

    setDestination,
    setLocationSharing,
    setInputFocused,

    canAddTime,
    canSubtractTime,
    handleAddTime,
    handleSubtractTime,
    handleTimePicked,
    handlePickImage,
    handleCreateSession,
    handleBack,
  } = useCreateSession()

  // Tap-to-edit time: the OS rotary picker (alarm-app style). Android's
  // component IS a dialog (render → opens); iOS shows an inline spinner
  // toggled by tapping the time again.
  const [showTimePicker, setShowTimePicker] = React.useState(false)
  const dateTimePickerModule = loadDateTimePicker()
  const DateTimePicker = dateTimePickerModule?.default

  // Live, point-of-use permission sufficiency for the signals a session needs.
  // Non-blocking: we surface what's missing so the moment the user grants it —
  // here or in Settings — gathering can begin, but "Start Session" is never
  // gated on it.
  const { gaps, refresh: refreshPermissions } = usePermissionRequirements([
    'location',
    'notifications',
  ])
  const sessionGapItems = sessionRequirementItems(gaps)

  return (
    <>

      <SafeAreaView style={styles.container}>
        <ModalHeader title="Start Session" onBack={handleBack} />

        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={{ flex: 1 }}
        >
          <ScrollView
            contentContainerStyle={styles.scrollContent}
            showsVerticalScrollIndicator={false}
          >
            {/* Persistent, non-blocking permission guidance (Location +
                Notifications shown prominently — they're load-bearing for a
                session). */}
            <PermissionRequirements
              items={sessionGapItems}
              onChanged={refreshPermissions}
              testID="session-permission-requirements"
            />

            {/* Destination Input */}
            <View style={styles.section}>
              <Text style={styles.label}>Where are you going?</Text>
              <View
                style={[
                  styles.inputContainer,
                  inputFocused && styles.inputContainerFocused,
                  errors.destination && styles.inputContainerError,
                ]}
              >
                <Ionicons
                  name="location-outline"
                  size={20}
                  color={inputFocused ? COLORS.primary : COLORS.textLight}
                  style={styles.inputIcon}
                />
                <TextInput
                  style={styles.input}
                  placeholder="Central Park, Work, Gym..."
                  placeholderTextColor={COLORS.textLight}
                  value={destination}
                  onChangeText={setDestination}
                  onFocus={() => setInputFocused(true)}
                  onBlur={() => setInputFocused(false)}
                  autoCapitalize="words"
                  autoFocus={true}
                />
              </View>
              {errors.destination && (
                <Text style={styles.errorText}>{errors.destination}</Text>
              )}
            </View>

            {/* Return Time */}
            <View style={styles.section}>
              <Text style={styles.label}>When will you be back?</Text>

              <View style={styles.timeRow}>
                <TouchableOpacity
                  style={[
                    styles.timeButton,
                    !canSubtractTime && styles.timeButtonDisabled,
                  ]}
                  onPress={handleSubtractTime}
                  disabled={!canSubtractTime}
                >
                  <Ionicons name="remove" size={24} color={COLORS.text} />
                </TouchableOpacity>

                <TouchableOpacity
                  style={styles.timeDisplay}
                  onPress={() => {
                    if (DateTimePicker) setShowTimePicker(prev => !prev)
                  }}
                  activeOpacity={0.7}
                >
                  <Text style={styles.timeValue}>
                    {formatTime(expectedReturnTime)}
                  </Text>
                </TouchableOpacity>

                <TouchableOpacity
                  style={[
                    styles.timeButton,
                    !canAddTime && styles.timeButtonDisabled,
                  ]}
                  onPress={handleAddTime}
                  disabled={!canAddTime}
                >
                  <Ionicons name="add" size={24} color={COLORS.text} />
                </TouchableOpacity>
              </View>

              {errors.time && (
                <Text style={styles.errorText}>{errors.time}</Text>
              )}

              {showTimePicker && DateTimePicker && (
                <DateTimePicker
                  value={expectedReturnTime}
                  mode="time"
                  display="spinner"
                  onChange={(event, picked) => {
                    // Android's dialog closes itself — mirror that in state.
                    if (Platform.OS === 'android') setShowTimePicker(false)
                    if (event.type !== 'dismissed' && picked) {
                      handleTimePicked(picked)
                    }
                  }}
                />
              )}
            </View>

            {/* Outfit Photo */}
            <View style={styles.section}>
              <Text style={styles.label}>Outfit photo</Text>

              <TouchableOpacity
                style={styles.photoButton}
                onPress={handlePickImage}
              >
                {outfitPhoto ? (
                  <Image
                    source={{ uri: outfitPhoto.uri }}
                    style={styles.photoPreview}
                  />
                ) : (
                  <View style={styles.photoPlaceholder}>
                    <Ionicons
                      name="camera-outline"
                      size={32}
                      color={COLORS.textLight}
                    />
                    <Text style={styles.photoButtonText}>Add Photo</Text>
                  </View>
                )}
              </TouchableOpacity>
            </View>

            {/* Sharing Options */}
            <View style={styles.section}>
              <Text style={styles.label}>Sharing options</Text>
              <Text style={styles.hint}>
                Shared with your Circle if an alert triggers
              </Text>
              <View style={styles.toggleContainer}>
                <Ionicons
                  name="location-outline"
                  size={20}
                  color={COLORS.textLight}
                  style={styles.toggleIcon}
                />
                <Text style={styles.toggleText}>Location</Text>
                <Switch
                  value={locationSharing}
                  onValueChange={setLocationSharing}
                  trackColor={{
                    false: COLORS.neutral[300],
                    true: COLORS.primary,
                  }}
                  thumbColor={COLORS.white}
                  ios_backgroundColor={COLORS.neutral[300]}
                />
              </View>
              <Text style={styles.dataInfoText}>
                Session data is deleted 7 days after your session ends. Extend or review it anytime in Session History
              </Text>
            </View>

            {/* Notification List */}
            <View style={styles.section}>
              <Text style={styles.notificationTitle}>
                The following people will be notified if you don't check-in
                before {formatTime(expectedReturnTime)}:
              </Text>
              {activeMembers.length > 0 ? (
                <View style={styles.membersList}>
                  {activeMembers.map((member, index) => (
                    <View key={member.id || index} style={styles.memberItem}>
                      {activeMembers.length > 1 ? (
                        <Text style={styles.bulletPoint}>{'•'}</Text>
                      ) : null}
                      <Text style={styles.memberName}>
                        {getCircleMemberDisplayName(member)}
                      </Text>
                    </View>
                  ))}
                </View>
              ) : (
                <Text style={styles.noMembersText}>
                  No active members in your Circle of Trust yet. Add Circle
                  members or wait for pending invitations to be accepted.
                </Text>
              )}
            </View>

            {/* Create Button */}
            <TouchableOpacity
              style={[styles.createButton, isLoading && styles.buttonDisabled]}
              onPress={handleCreateSession}
              disabled={isLoading}
            >
              <LinearGradient
                colors={[COLORS.primary, '#0D9488']}
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 1 }}
                style={styles.gradientButton}
              >
                {isLoading ? (
                  <ActivityIndicator color="white" />
                ) : (
                  <>
                    <Text style={styles.createButtonText}>Start Session</Text>
                    <Ionicons name="arrow-forward" size={20} color="white" />
                  </>
                )}
              </LinearGradient>
            </TouchableOpacity>
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  scrollContent: {
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.xl,
    paddingBottom: SPACING['3xl'],
  },
  section: {
    marginBottom: SPACING.xl + SPACING.sm,
  },
  label: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
    color: COLORS.text,
    marginBottom: SPACING.sm,
  },
  hint: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.normal,
    color: COLORS.textLight,
    marginTop: -SPACING.xs,
    marginBottom: SPACING.md,
    lineHeight: 20,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.full,
    borderWidth: 1,
    borderColor: COLORS.neutral[200],
    paddingHorizontal: SPACING.lg,
    height: 52,
    ...SHADOWS.sm,
  },
  inputContainerFocused: {
    borderColor: COLORS.primary,
    borderWidth: 2,
  },
  inputContainerError: {
    borderColor: COLORS.danger,
    borderWidth: 2,
  },
  inputIcon: {
    marginRight: SPACING.sm,
  },
  input: {
    flex: 1,
    // No vertical padding: the fixed-height (52) container centers the text.
    // Padding + the font line exceeded the row height, so Android clipped
    // descenders (y/g/p) — the classic fixed-height TextInput squeeze.
    paddingVertical: 0,
    textAlignVertical: 'center',
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
    color: COLORS.text,
  },
  errorText: {
    color: COLORS.danger,
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
    marginTop: SPACING.xs,
    marginLeft: SPACING.xs,
  },
  timeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
  },
  timeDisplay: {
    flex: 1,
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.full,
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.sm + 2,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: COLORS.neutral[200],
    height: 52,
    // No shadow: a flat, borderless-feeling value reads as a read-only
    // display, not a tappable input. The ± buttons keep the elevation.
  },
  timeButtonDisabled: {
    opacity: 0.35,
  },
  timeButton: {
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.full,
    width: 52,
    height: 52,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: COLORS.neutral[200],
    ...SHADOWS.sm,
  },
  timeIcon: {
    marginRight: SPACING.sm,
  },
  timeValue: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
    color: COLORS.text,
  },
  photoButton: {
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.xl,
    overflow: 'hidden',
    height: 200,
    marginTop: SPACING.xs,
    ...SHADOWS.sm,
  },
  photoPlaceholder: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: COLORS.neutral[50],
    borderWidth: 1,
    borderColor: COLORS.neutral[200],
    borderStyle: 'dashed',
    borderRadius: RADIUS.xl,
  },
  photoButtonText: {
    color: COLORS.textLight,
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
    marginTop: SPACING.xs,
  },
  photoPreview: {
    width: '100%',
    height: '100%',
    resizeMode: 'cover',
  },
  toggleContainer: {
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.full,
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.xs,
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: COLORS.neutral[200],
    height: 52,
    ...SHADOWS.sm,
  },
  toggleIcon: {
    marginRight: SPACING.sm,
  },
  toggleText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
    color: COLORS.text,
    flex: 1,
  },
  dataInfoText: {
    fontSize: TYPOGRAPHY.fontSize.xs,
    fontWeight: TYPOGRAPHY.fontWeight.normal,
    color: COLORS.textLight,
    marginTop: SPACING.md,
    textAlign: 'center',
    lineHeight: 18,
  },
  createButton: {
    marginTop: SPACING['2xl'],
    marginBottom: SPACING.xl,
    ...SHADOWS.md,
    borderRadius: RADIUS.full,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  gradientButton: {
    borderRadius: RADIUS.full,
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.xl,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACING.sm,
    minHeight: 56,
  },
  createButtonText: {
    color: COLORS.white,
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.bold,
  },
  notificationTitle: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.normal,
    color: COLORS.textLight,
    lineHeight: 20,
    marginBottom: SPACING.md,
  },
  membersList: {
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.neutral[200],
    ...SHADOWS.sm,
  },
  memberItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: SPACING.xs,
  },
  bulletPoint: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    marginRight: SPACING.sm,
  },
  memberName: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
    color: COLORS.text,
  },
  noMembersText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.normal,
    color: COLORS.textLight,
    fontStyle: 'italic',
    textAlign: 'center',
    backgroundColor: COLORS.neutral[50],
    padding: SPACING.md,
    borderRadius: RADIUS.lg,
  },
})
