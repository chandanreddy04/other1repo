import AsyncStorage from '@react-native-async-storage/async-storage'

const REFERRAL_PROMPT_COUNT_KEY = 'referral_prompt_count'
const LAST_REFERRAL_PROMPT_KEY = 'last_referral_prompt_at'
const MAX_PROMPTS = 2
const MIN_INTERVAL_MS = 90 * 24 * 60 * 60 * 1000 // ~3 months

export async function shouldShowReferralPrompt(): Promise<boolean> {
  try {
    const countStr = await AsyncStorage.getItem(REFERRAL_PROMPT_COUNT_KEY)
    const count = countStr ? parseInt(countStr, 10) : 0
    if (count >= MAX_PROMPTS) return false

    const lastStr = await AsyncStorage.getItem(LAST_REFERRAL_PROMPT_KEY)
    if (lastStr) {
      const lastTime = parseInt(lastStr, 10)
      if (Date.now() - lastTime < MIN_INTERVAL_MS) return false
    }

    return true
  } catch {
    // benign: an unreadable marker means prompt
    return false
  }
}

export async function recordReferralPrompt(): Promise<void> {
  try {
    const countStr = await AsyncStorage.getItem(REFERRAL_PROMPT_COUNT_KEY)
    const count = countStr ? parseInt(countStr, 10) : 0
    await AsyncStorage.setItem(REFERRAL_PROMPT_COUNT_KEY, String(count + 1))
    await AsyncStorage.setItem(LAST_REFERRAL_PROMPT_KEY, String(Date.now()))
  } catch {
    // benign: Silently fail
  }
}
