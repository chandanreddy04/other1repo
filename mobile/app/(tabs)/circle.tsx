import React, { useEffect } from 'react'
import {
  View,
  Text,
  StyleSheet,
  TextStyle,
  ScrollView,
  TouchableOpacity,
  SafeAreaView,
  RefreshControl,
} from 'react-native'
import { LinearGradient } from 'expo-linear-gradient'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, SPACING, RADIUS, TYPOGRAPHY, SHADOWS } from '../../constants'
import { Button } from '../../components/ui'
import { ContactsPermissionModal } from '../../components/ContactsPermissionModal'
import { ContactSelector } from '../../components/ContactSelector'
import { ModalHeader } from '../../components/ModalHeader'
import { CircleMemberCard } from '../../components/CircleMemberCard'
import { TrustCircleIcon } from '../../components/icons/TrustCircleIcon'
import { ShareReferralButton } from '../../components/ShareReferralButton'
import { PermissionRequirements } from '../../components/PermissionRequirements'
import { useCircleScreen } from '../../hooks/useCircleScreen'
import { useNavigation } from 'expo-router'

export default function CircleScreen() {
  const {
    viewMode,
    showPermissionModal,
    isRefreshing,
    circleOfTrust,
    circleSettings,
    phoneContacts,
    isLoading,
    isLoadingPhoneContacts,
    hasLimitedAccess,
    contactsRequirement,
    refreshContactsRequirement,

    setShowPermissionModal,

    handleRefresh,
    handleRequestPermission,
    handleAddContacts,
    handleContactTap,
    handleRemoveFromCircle,
    handleNudgeMember,
    handleRefreshContacts,
    handleUpdateContactAccess,
    handleBackFromAddContacts,
  } = useCircleScreen()

  const navigation = useNavigation()

  useEffect(() => {
    navigation.setOptions({
      tabBarStyle:
        viewMode === 'add_contacts' ? { display: 'none' } : undefined,
    })
  }, [viewMode, navigation])

  const renderOverview = () => (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.scrollContent}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          onRefresh={handleRefresh}
          tintColor={COLORS.primary}
        />
      }
    >
      {/* Header Section */}
      <View style={styles.header}>
        <Text style={styles.greeting}>Circle of Trust</Text>
        <ShareReferralButton />
      </View>

      {/* Persistent contacts-access nudge — only when there's room in the
          circle and no visible contact could grow it (see useCircleScreen). */}
      {contactsRequirement && (
        <PermissionRequirements
          items={[contactsRequirement]}
          onChanged={refreshContactsRequirement}
          testID="contacts-permission-requirements"
        />
      )}

      {/* My Circle Section */}
      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>My Circle</Text>
          <Text style={styles.sectionCount}>
            {circleOfTrust.length} of {circleSettings.max_contacts || 3}
          </Text>
        </View>
        {circleOfTrust.length === 0 ? (
          <View style={styles.emptyState}>
            <LinearGradient
              colors={[COLORS.glass.light, COLORS.glass.white]}
              style={styles.emptyCard}
            >
              <View style={styles.emptyIconContainer}>
                <TrustCircleIcon
                  size={80}
                  color={COLORS.primary}
                  focused={false}
                />
              </View>
              <Text style={styles.emptyText}>
                Add up to 3 trusted friends and family who will be notified if:
              </Text>
              <View style={styles.featureList}>
                <View style={styles.featureItem}>
                  <Ionicons
                    name="checkmark-circle"
                    size={20}
                    color={COLORS.primary}
                  />
                  <Text style={styles.featureText}>You activate SOS</Text>
                </View>
                <View style={styles.featureItem}>
                  <Ionicons
                    name="checkmark-circle"
                    size={20}
                    color={COLORS.primary}
                  />
                  <Text style={styles.featureText}>Your timer expires</Text>
                </View>
              </View>
              <Button
                title="Import Contacts"
                onPress={handleAddContacts}
                variant="primary"
                size="medium"
                icon="people"
              />
            </LinearGradient>
          </View>
        ) : (
          <>
            {circleOfTrust.map(member => (
              <CircleMemberCard
                key={member.id}
                member={member}
                onRemove={handleRemoveFromCircle}
                onNudge={handleNudgeMember}
              />
            ))}
            {circleOfTrust.length < (circleSettings.max_contacts || 3) && (
              <View style={styles.addMoreContainer}>
                <TouchableOpacity
                  style={styles.addMoreButton}
                  onPress={handleAddContacts}
                >
                  <Ionicons
                    name="add-circle-outline"
                    size={24}
                    color={COLORS.primary}
                  />
                  <View style={styles.addMoreContent}>
                    <Text style={styles.addMoreText}>Add more contacts</Text>
                    <Text style={styles.addMoreSubtext}>
                      {(circleSettings.max_contacts || 3) -
                        circleOfTrust.length}{' '}
                      spot
                      {(circleSettings.max_contacts || 3) -
                        circleOfTrust.length !==
                      1
                        ? 's'
                        : ''}{' '}
                      remaining
                    </Text>
                  </View>
                  <Ionicons
                    name="chevron-forward"
                    size={20}
                    color={COLORS.textLight}
                  />
                </TouchableOpacity>
              </View>
            )}
          </>
        )}
      </View>
    </ScrollView>
  )

  const renderAddContacts = () => (
    <View style={styles.container}>
      <ModalHeader
        title="Add to Circle"
        onBack={handleBackFromAddContacts}
        rightAction={
          <TouchableOpacity
            style={styles.headerActionButton}
            onPress={handleRefreshContacts}
          >
            <Ionicons name="refresh" size={24} color={COLORS.primary} />
          </TouchableOpacity>
        }
      />

      <ContactSelector
        contacts={phoneContacts}
        onContactTap={handleContactTap}
        isLoading={isLoading || isLoadingPhoneContacts}
        hasLimitedAccess={hasLimitedAccess}
        onUpdateAccess={handleUpdateContactAccess}
      />
    </View>
  )

  const renderContent = () => {
    switch (viewMode) {
      case 'add_contacts':
        return renderAddContacts()
      default:
        return renderOverview()
    }
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      {renderContent()}

      <ContactsPermissionModal
        visible={showPermissionModal}
        onRequestPermission={handleRequestPermission}
        onSkip={() => setShowPermissionModal(false)}
        onClose={() => setShowPermissionModal(false)}
        isLoading={isLoading}
      />
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: COLORS.background,
  },

  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },

  scrollContent: {
    paddingBottom: SPACING['2xl'],
  },

  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: SPACING.lg,
    marginBottom: SPACING.xl,
    paddingTop: SPACING.xl,
  },

  greeting: {
    fontSize: TYPOGRAPHY.fontSize['3xl'],
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
  },

  section: {
    marginBottom: SPACING.lg,
  },

  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: SPACING.lg,
    marginBottom: SPACING.md,
  },

  sectionTitle: {
    fontSize: TYPOGRAPHY.fontSize.xl,
    fontWeight: TYPOGRAPHY.fontWeight.bold,
    color: COLORS.text,
  },

  sectionCount: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
    color: COLORS.textLight,
  },

  emptyState: {
    paddingHorizontal: SPACING.lg,
  },

  emptyCard: {
    borderRadius: RADIUS.xl,
    padding: SPACING.xl,
    alignItems: 'center',
    ...SHADOWS.md,
  },

  emptyIconContainer: {
    marginBottom: SPACING.lg,
  },

  emptyText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center',
    lineHeight: TYPOGRAPHY.lineHeight.relaxed * TYPOGRAPHY.fontSize.base,
    marginBottom: SPACING.lg,
    paddingHorizontal: SPACING.md,
  },

  featureList: {
    alignItems: 'flex-start',
    marginBottom: SPACING.xl,
  },

  featureItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    marginBottom: SPACING.sm,
  },

  featureText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
  },

  addMoreContainer: {
    paddingHorizontal: SPACING.lg,
    marginTop: SPACING.md,
    marginBottom: SPACING.md,
  },

  addMoreButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.white,
    padding: SPACING.md,
    borderRadius: RADIUS.xl,
    borderWidth: 1,
    borderColor: COLORS.neutral[200],
    borderStyle: 'dashed',
    ...SHADOWS.sm,
  },

  addMoreContent: {
    flex: 1,
    marginLeft: SPACING.md,
  },

  addMoreText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.medium,
    color: COLORS.primary,
    marginBottom: 2,
  },

  addMoreSubtext: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
  },

  headerActionButton: {
    padding: SPACING.xs,
  },
})
