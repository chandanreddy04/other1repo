// Re-export everything from config for backward compatibility
export {
  API_CONFIG,
  STORAGE_KEYS,
  SECURE_STORE_KEYS,
  CHECKIN_CONFIG,
  CONTACT_CONFIG,
  SECURITY_CONFIG,
  APP_INFO,
  ENV,
} from './config'

// Backward compatibility exports — derived from the single source (API_CONFIG
// in config.ts); no host/domain literals duplicated here.
import { API_CONFIG as _API_CONFIG } from './config'

export const API_BASE_URL = _API_CONFIG.BASE_URL
const API_SERVER_URL = API_BASE_URL.replace(/\/api\/v1$/, '')

/** Resolve a potentially relative URL (e.g. /uploads/...) to an absolute URL. */
export const resolveUrl = (url: string): string =>
  url.startsWith('/') ? `${API_SERVER_URL}${url}` : url

// Re-export quick return times for backward compatibility
export { CHECKIN_CONFIG as QUICK_RETURN_TIMES_CONFIG } from './config'

// Export individual time option arrays for direct use
import { CHECKIN_CONFIG as _CHECKIN_CONFIG } from './config'
export const QUICK_RETURN_TIMES = _CHECKIN_CONFIG.QUICK_RETURN_TIMES
export const EXTEND_TIME_OPTIONS = _CHECKIN_CONFIG.EXTEND_TIME_OPTIONS

// Playful Pop color system - Final Design
export const COLORS = {
  // Core brand colors - calming and trustworthy (no red!)
  primary: '#14B8A6', // Teal - calming and fresh
  secondary: '#A78BFA', // Purple - playful secondary
  success: '#6366F1', // Indigo - "I'm safe" confirmation
  danger: '#DC3545', // Red - emergency/danger
  warning: '#FFE66D', // Yellow - caution/attention
  text: '#2C3E50', // Soft dark blue for readability
  textLight: '#7F8C8D', // Muted gray for secondary text
  background: '#FAFBFC', // Clean off-white
  white: '#FFFFFF',
  black: '#000000',
  gray: '#95A5A6', // Friendly gray
  lightGray: '#ECF0F1', // Light gray for borders
  border: '#ECF0F1', // Border color (same as lightGray)

  // Extended palette with gradient pairs
  primaryDark: '#0D9488',
  primaryLight: '#5EEAD4',
  secondaryDark: '#8B5CF6',
  secondaryLight: '#C4B5FD',
  successDark: '#4F46E5',
  successLight: '#A5B4FC',
  dangerDark: '#FFA500',
  dangerLight: '#FFF3CD',
  warningDark: '#F97316',
  warningLight: '#FED7AA',

  // Accent colors for special uses
  accent: {
    purple: '#A855F7',
    pink: '#EC4899',
    blue: '#3B82F6',
    green: '#10B981', // For positive states
    teal: '#14B8A6',
    orange: '#FB923C',
    yellow: '#FFE66D',
    indigo: '#6366F1',
  },

  // Neutral shades
  neutral: {
    50: '#FAFBFC',
    100: '#F4F6F7',
    200: '#ECF0F1',
    300: '#D5DBDD',
    400: '#BDC3C7',
    500: '#95A5A6',
    600: '#7F8C8D',
    700: '#5D6D7E',
    800: '#34495E',
    900: '#2C3E50',
  },

  // Glass morphism support for premium feel
  glass: {
    white: 'rgba(255, 255, 255, 0.85)',
    light: 'rgba(255, 255, 255, 0.6)',
    dark: 'rgba(44, 62, 80, 0.7)',
    blur: 'rgba(255, 255, 255, 0.2)',
    teal: 'rgba(20, 184, 166, 0.15)',
    purple: 'rgba(167, 139, 250, 0.15)',
    indigo: 'rgba(99, 102, 241, 0.15)',
  },

  // Gradient definitions for buttons
  gradients: {
    primary: ['#14B8A6', '#0D9488'] as const, // Teal gradient
    secondary: ['#A78BFA', '#8B5CF6'] as const, // Purple gradient
    success: ['#6366F1', '#4F46E5'] as const, // Indigo gradient
    danger: ['#DC3545', '#B02A37'] as const, // Red gradient (emergency)
    warning: ['#FFE66D', '#FFC947'] as const, // Yellow gradient (caution)
    glass: ['rgba(255, 255, 255, 0.25)', 'rgba(255, 255, 255, 0.1)'] as const,
  },
}

// Typography system for consistent text styling
export const TYPOGRAPHY = {
  fontSize: {
    xs: 12,
    sm: 14,
    base: 16,
    lg: 18,
    xl: 20,
    '2xl': 24,
    '3xl': 30,
    '4xl': 36,
  },
  fontWeight: {
    normal: '400' as const,
    medium: '500' as const,
    semibold: '600' as const,
    bold: '700' as const,
    extrabold: '800' as const,
  },
  lineHeight: {
    tight: 1.2,
    normal: 1.5,
    relaxed: 1.75,
  },
}

// Spacing system for consistent layout
export const SPACING = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  '2xl': 48,
  '3xl': 64,
}

// Border radius for rounded corners
export const RADIUS = {
  sm: 4,
  md: 8,
  lg: 12,
  xl: 16,
  full: 9999,
}

// Shadow styles for elevation - matching design-refined.html
export const SHADOWS = {
  sm: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  md: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 20,
    elevation: 3,
  },
  lg: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 8,
    elevation: 6,
  },
  xl: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.2,
    shadowRadius: 12,
    elevation: 9,
  },
}
