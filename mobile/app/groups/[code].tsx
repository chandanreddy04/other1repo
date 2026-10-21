import { useLocalSearchParams, useRouter } from 'expo-router'
import { DeepLinkAcceptScreen } from '../../components/DeepLinkAcceptScreen'
import { useGroupPlanStore } from '../../store/useGroupPlanStore'
import { useSubscriptionStore } from '../../store/useSubscriptionStore'

// Deep-link target for /g/{code} group-plan join invites (reassigned from
// /f/ — owner decision 2026-09-23, nothing shipped with the old slug so no
// alias). AASA claims /g/*, so on an installed-app device the OS opens
// app/g/[code].tsx directly, which redirects here; the browser fallback is
// the /groups/{code} lander on the web backend.
export default function JoinGroupPlanScreen() {
  const router = useRouter()
  const { code } = useLocalSearchParams<{ code: string }>()
  const joinPlan = useGroupPlanStore(state => state.joinPlan)
  const checkSubscription = useSubscriptionStore(
    state => state.checkSubscription
  )

  return (
    <DeepLinkAcceptScreen
      accept={async () => {
        await joinPlan(code)
        await checkSubscription()
      }}
      loadingText="Joining group plan..."
      successTitle="You're in!"
      successBody="You've joined the group plan."
      errorTitle="Couldn't join"
      primaryActionLabel="View Subscription"
      onPrimaryAction={() => router.replace('/subscription')}
    />
  )
}
