/**
 * Shared StyleSheet for app/subscription.tsx and its state views
 * (components/subscription/{PlanCardState,GroupState}.tsx).
 */
import { StyleSheet, TextStyle } from 'react-native'
import { COLORS, SPACING, TYPOGRAPHY, RADIUS } from '../../constants'

export const subscriptionStyles = StyleSheet.create({
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
    borderBottomWidth: 1,
    borderBottomColor: COLORS.lightGray,
    backgroundColor: COLORS.white,
  },
  headerTitle: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
  },
  body: {
    padding: SPACING.lg,
    paddingBottom: SPACING['3xl'],
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: SPACING['3xl'],
    gap: SPACING.md,
  },
  emptyText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
  },
  planCard: {
    alignItems: 'center',
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.xl,
    paddingHorizontal: SPACING.lg,
    marginBottom: SPACING.xl,
    gap: SPACING.xs,
    borderWidth: 1,
    borderColor: COLORS.lightGray,
  },
  planLabel: {
    fontSize: TYPOGRAPHY.fontSize.xl,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
    marginTop: SPACING.sm,
  },
  planStatus: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
  },
  section: {
    backgroundColor: COLORS.white,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: COLORS.lightGray,
    marginBottom: SPACING.xl,
  },
  primaryButton: {
    backgroundColor: COLORS.primary,
    paddingVertical: 16,
    borderRadius: RADIUS.full,
    alignItems: 'center',
    marginBottom: SPACING.lg,
    paddingHorizontal: SPACING.xl,
  },
  primaryButtonText: {
    color: COLORS.white,
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
  },
  cancelButton: {
    paddingVertical: 15,
    borderRadius: RADIUS.full,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: COLORS.danger,
  },
  cancelButtonText: {
    color: COLORS.danger,
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
  },
  statusOnlyNote: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center',
    lineHeight: 24,
    paddingHorizontal: SPACING.md,
  },
  upgradeNote: {
    marginBottom: SPACING.lg,
  },
  // group
  planInfo: {
    alignItems: 'center',
    marginBottom: SPACING.xl,
  },
  planOwner: {
    fontSize: TYPOGRAPHY.fontSize['2xl'],
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
    marginBottom: SPACING.xs,
  },
  memberCount: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
  },
  sectionLabel: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
    color: COLORS.textLight,
    textTransform: 'uppercase',
    marginBottom: SPACING.sm,
  },
  membersList: {
    backgroundColor: COLORS.white,
    borderRadius: RADIUS.lg,
    overflow: 'hidden',
    marginBottom: SPACING.xl,
  },
  memberRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.lightGray,
  },
  memberInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
    gap: SPACING.sm,
  },
  memberText: {
    flex: 1,
  },
  memberName: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.medium as TextStyle['fontWeight'],
    color: COLORS.text,
  },
  ownerBadge: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.primary,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
  },
  memberDate: {
    fontSize: TYPOGRAPHY.fontSize.xs,
    color: COLORS.textLight,
    marginTop: 2,
  },
  ownerActions: {
    gap: SPACING.md,
    marginBottom: SPACING.xl,
  },
  shareButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACING.sm,
    backgroundColor: COLORS.primary,
    paddingVertical: 14,
    borderRadius: RADIUS.full,
  },
  shareButtonText: {
    color: COLORS.white,
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
  },
  regenerateButton: {
    alignItems: 'center',
    paddingVertical: SPACING.sm,
  },
  regenerateText: {
    color: COLORS.textLight,
    fontSize: TYPOGRAPHY.fontSize.sm,
    textDecorationLine: 'underline',
  },
  leaveButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACING.sm,
    borderWidth: 1,
    borderColor: COLORS.danger,
    paddingVertical: 14,
    borderRadius: RADIUS.full,
  },
  leaveButtonText: {
    color: COLORS.danger,
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
  },
})
