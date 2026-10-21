import React, { useState, useMemo, useCallback, useRef } from 'react'
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  TextInput,
  ActivityIndicator,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { COLORS, SPACING, RADIUS, TYPOGRAPHY, SHADOWS } from '../constants'
import { ContactListItem } from './ContactListItem'
import { PhoneContact } from '../services/contacts'

interface ContactSelectorProps {
  contacts: PhoneContact[]
  onContactTap: (contact: PhoneContact) => void
  isLoading?: boolean
  searchPlaceholder?: string
  hasLimitedAccess?: boolean
  onUpdateAccess?: () => void
}

export const ContactSelector: React.FC<ContactSelectorProps> = ({
  contacts,
  onContactTap,
  isLoading = false,
  searchPlaceholder = 'Search contacts...',
  hasLimitedAccess = false,
  onUpdateAccess,
}) => {
  const [searchQuery, setSearchQuery] = useState('')
  const searchInputRef = useRef<TextInput>(null)

  const filteredContacts = useMemo(() => {
    if (!searchQuery.trim()) {
      return contacts
    }

    const query = searchQuery.toLowerCase().trim()
    return contacts.filter(
      contact =>
        contact.name.toLowerCase().includes(query) ||
        contact.phoneNumbers.some(phone => phone.includes(query)) ||
        contact.emails.some(email => email.toLowerCase().includes(query))
    )
  }, [contacts, searchQuery])

  const renderContact = ({ item }: { item: PhoneContact }) => (
    <ContactListItem
      contact={item}
      onPress={() => onContactTap(item)}
      avatarSize={48}
      showEmail={true}
      showImage={true}
    />
  )

  const handleClearSearch = useCallback(() => {
    setSearchQuery('')
    searchInputRef.current?.focus()
  }, [])

  const renderEmpty = () => (
    <View style={styles.emptyContainer}>
      <Ionicons name="search" size={60} color={COLORS.lightGray} />
      <Text style={styles.emptyTitle}>No contacts found</Text>
      <Text style={styles.emptyText}>
        {searchQuery.trim()
          ? `No contacts match "${searchQuery}"`
          : 'No contacts available to select'}
      </Text>
    </View>
  )

  if (isLoading && contacts.length === 0) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={COLORS.primary} />
        <Text style={styles.loadingText}>Loading contacts...</Text>
      </View>
    )
  }

  return (
    <View style={styles.container}>
      {/* Fixed header with search */}
      <View style={styles.header}>
        <View style={styles.searchContainer}>
          <Ionicons
            name="search"
            size={20}
            color={COLORS.textLight}
            style={styles.searchIcon}
          />
          <TextInput
            ref={searchInputRef}
            style={styles.searchInput}
            placeholder={searchPlaceholder}
            placeholderTextColor={COLORS.textLight}
            value={searchQuery}
            onChangeText={setSearchQuery}
            autoCapitalize="none"
            autoCorrect={false}
            returnKeyType="search"
            blurOnSubmit={false}
          />
          {searchQuery.length > 0 && (
            <TouchableOpacity
              onPress={handleClearSearch}
              style={styles.clearButton}
            >
              <Ionicons
                name="close-circle"
                size={20}
                color={COLORS.textLight}
              />
            </TouchableOpacity>
          )}
        </View>
      </View>

      {hasLimitedAccess && onUpdateAccess && (
        <TouchableOpacity style={styles.limitedBanner} onPress={onUpdateAccess}>
          <Ionicons
            name="information-circle"
            size={18}
            color={COLORS.warning}
          />
          <Text style={styles.limitedBannerText}>
            Only showing contacts you've shared. Tap to update.
          </Text>
          <Ionicons name="chevron-forward" size={16} color={COLORS.textLight} />
        </TouchableOpacity>
      )}

      <FlatList
        data={filteredContacts}
        renderItem={renderContact}
        keyExtractor={item => item.id}
        ListEmptyComponent={renderEmpty}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        removeClippedSubviews={true}
        maxToRenderPerBatch={10}
        windowSize={10}
      />
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },

  listContent: {
    paddingTop: SPACING.md,
    paddingBottom: SPACING.xl,
    flexGrow: 1,
  },

  header: {
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.md,
    paddingBottom: SPACING.lg,
    backgroundColor: COLORS.background,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.lightGray,
  },

  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.lg,
    paddingHorizontal: SPACING.md,
    ...SHADOWS.sm,
  },

  searchIcon: {
    marginRight: SPACING.sm,
  },

  searchInput: {
    flex: 1,
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.text,
    paddingVertical: SPACING.md,
  },

  clearButton: {
    padding: SPACING.xs,
    marginLeft: SPACING.sm,
  },

  emptyContainer: {
    alignItems: 'center',
    paddingTop: SPACING['3xl'],
    paddingHorizontal: SPACING.lg,
  },

  emptyTitle: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.semibold,
    color: COLORS.text,
    marginTop: SPACING.lg,
    marginBottom: SPACING.sm,
  },

  emptyText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center',
    lineHeight: TYPOGRAPHY.lineHeight.relaxed * TYPOGRAPHY.fontSize.base,
  },

  limitedBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.dangerLight,
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.sm + 2,
    gap: SPACING.sm,
  },

  limitedBannerText: {
    flex: 1,
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.text,
  },

  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: COLORS.background,
  },

  loadingText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    marginTop: SPACING.md,
  },
})
