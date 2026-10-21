import { TouchableOpacity, StyleSheet } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { useRouter } from 'expo-router'
import { useAuthStore } from '../store/useAuthStore'
import { COLORS } from '../constants'

export function ShareReferralButton() {
  const router = useRouter()
  const referralCode = useAuthStore(state => state.user?.share_code)

  if (!referralCode) return null

  return (
    <TouchableOpacity
      style={styles.button}
      onPress={() => router.push('/referrals')}
    >
      <Ionicons name="gift-outline" size={24} color={COLORS.primary} />
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  button: {
    padding: 8,
  },
})
