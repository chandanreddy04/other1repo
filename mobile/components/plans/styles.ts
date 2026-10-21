/**
 * Shared StyleSheet for app/plans.tsx and its step views
 * (components/plans/{OptionsView,PickerView,ConfirmingView}.tsx).
 */
import { StyleSheet, TextStyle } from 'react-native'
import { COLORS, SPACING, TYPOGRAPHY, RADIUS } from '../../constants'

export const plansStyles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  // options / canceled
  closeButton: {
    alignSelf: 'flex-end',
    padding: SPACING.lg,
  },
  scroll: {
    flex: 1,
  },
  content: {
    flexGrow: 1,
    paddingHorizontal: SPACING.lg,
    justifyContent: 'center',
    paddingBottom: SPACING['3xl'],
  },
  header: {
    alignItems: 'center',
    marginBottom: SPACING['2xl'],
  },
  iconGradient: {
    width: 88,
    height: 88,
    borderRadius: 44,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: SPACING.lg,
  },
  title: {
    fontSize: TYPOGRAPHY.fontSize['2xl'],
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
    textAlign: 'center' as const,
    marginBottom: SPACING.sm,
  },
  subtitle: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center' as const,
    lineHeight: 22,
  },
  noteBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
    backgroundColor: COLORS.lightGray,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    marginBottom: SPACING.lg,
  },
  noteText: {
    flex: 1,
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
  },
  options: {
    gap: SPACING.md,
  },
  webNote: {
    marginTop: SPACING.lg,
    textAlign: 'center' as const,
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
  },
  optionCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.white,
    padding: SPACING.lg,
    borderRadius: RADIUS.lg,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 1,
  },
  optionIcon: {
    width: 48,
    height: 48,
    borderRadius: RADIUS.lg,
    backgroundColor: COLORS.primary + '12',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: SPACING.md,
  },
  optionText: {
    flex: 1,
  },
  optionTitle: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
    color: COLORS.text,
    marginBottom: 2,
  },
  optionSubtitle: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
  },
  // picker
  pickerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SPACING.lg,
    paddingVertical: SPACING.md,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.lightGray,
    backgroundColor: COLORS.white,
  },
  pickerHeaderTitle: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
  },
  bodyScroll: {
    flex: 1,
  },
  body: {
    paddingHorizontal: SPACING.lg,
    paddingTop: SPACING.xl,
    paddingBottom: SPACING.xl,
  },
  categoryTabs: {
    flexDirection: 'row',
    gap: SPACING.sm,
    marginBottom: SPACING.lg,
  },
  categoryTab: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: SPACING.md,
    borderRadius: RADIUS.lg,
    borderWidth: 2,
    borderColor: COLORS.lightGray,
    backgroundColor: COLORS.white,
    gap: 4,
  },
  categoryTabActive: {
    borderColor: COLORS.primary,
    backgroundColor: COLORS.primary + '08',
  },
  categoryTabLabel: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
    color: COLORS.textLight,
  },
  categoryTabLabelActive: {
    color: COLORS.text,
  },
  categoryTabPrice: {
    fontSize: TYPOGRAPHY.fontSize.xs,
    color: COLORS.textLight,
  },
  categoryTabPriceActive: {
    color: COLORS.primary,
  },
  toggleContainer: {
    flexDirection: 'row',
    backgroundColor: COLORS.lightGray,
    borderRadius: RADIUS.full,
    padding: 4,
    marginBottom: SPACING.xl,
  },
  toggleOption: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
    borderRadius: RADIUS.full,
    gap: SPACING.xs,
  },
  toggleOptionActive: {
    backgroundColor: COLORS.white,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 3,
    elevation: 2,
  },
  toggleText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
    color: COLORS.textLight,
  },
  toggleTextActive: {
    color: COLORS.text,
  },
  savingsBadge: {
    backgroundColor: COLORS.primary + '15',
    paddingHorizontal: SPACING.sm,
    paddingVertical: 2,
    borderRadius: RADIUS.full,
  },
  savingsText: {
    fontSize: 10,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.primary,
  },
  priceSection: {
    alignItems: 'center',
    marginBottom: SPACING.xl,
  },
  priceRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
  },
  priceAmount: {
    fontSize: 48,
    fontWeight: TYPOGRAPHY.fontWeight.extrabold as TextStyle['fontWeight'],
    color: COLORS.text,
  },
  pricePeriod: {
    fontSize: TYPOGRAPHY.fontSize.lg,
    fontWeight: TYPOGRAPHY.fontWeight.medium as TextStyle['fontWeight'],
    color: COLORS.textLight,
    marginLeft: 2,
  },
  billingDetail: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.textLight,
    marginTop: 4,
  },
  features: {
    gap: SPACING.md,
  },
  featureRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACING.sm,
  },
  featureText: {
    fontSize: TYPOGRAPHY.fontSize.sm,
    color: COLORS.text,
  },
  footer: {
    paddingHorizontal: SPACING.lg,
    paddingBottom: SPACING.lg,
    paddingTop: SPACING.md,
  },
  subscribeButton: {
    backgroundColor: COLORS.primary,
    paddingVertical: 16,
    borderRadius: RADIUS.full,
    alignItems: 'center',
    marginBottom: SPACING.md,
  },
  subscribeText: {
    color: COLORS.white,
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
  },
  // confirming
  confirmingContent: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: SPACING.xl,
    gap: SPACING.lg,
  },
  iconCircle: {
    width: 96,
    height: 96,
    borderRadius: RADIUS.full,
    backgroundColor: COLORS.primary + '10',
    justifyContent: 'center',
    alignItems: 'center',
  },
  confirmingTitle: {
    fontSize: TYPOGRAPHY.fontSize.xl,
    fontWeight: TYPOGRAPHY.fontWeight.bold as TextStyle['fontWeight'],
    color: COLORS.text,
    textAlign: 'center',
  },
  confirmingSubtitle: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    textAlign: 'center',
    lineHeight: 22,
  },
  message: {
    fontSize: TYPOGRAPHY.fontSize.base,
    color: COLORS.textLight,
    marginTop: SPACING.md,
  },
  backButton: {
    marginTop: SPACING.md,
    paddingVertical: 14,
    paddingHorizontal: SPACING.xl,
    borderRadius: RADIUS.full,
    borderWidth: 2,
    borderColor: COLORS.primary,
  },
  backButtonText: {
    fontSize: TYPOGRAPHY.fontSize.base,
    fontWeight: TYPOGRAPHY.fontWeight.semibold as TextStyle['fontWeight'],
    color: COLORS.primary,
  },
})
