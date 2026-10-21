import { useState, useEffect } from 'react'
import { Alert } from 'react-native'
import { useRouter } from 'expo-router'
import { useSessionStore } from '../store/useSessionStore'
import api from '../services/api'
import { useAuthStore } from '../store/useAuthStore'
import { useCircleStore } from '../store/useCircleStore'
import { useImagePicker } from './useImagePicker'
import { File } from 'expo-file-system'
import { consumeSessionDraft, saveSessionDraft } from '../utils/sessionDraft'
import toast from '../utils/toast'
import { roundToNearest30Minutes } from '../utils/dateFormatting'
import { CHECKIN_CONFIG } from '../constants'
import { nextOccurrenceOfTime } from '../utils/sessionTiming'
import { notify } from '../services/errorReporting'

/** Does the picker-cache file behind a draft photo still exist? */
function photoFileExists(uri: string): boolean {
  try {
    return new File(uri).exists
  } catch {
    // benign: a missing cache file just means no draft photo
    return false
  }
}

export function useCreateSession() {
  const router = useRouter()
  const user = useAuthStore(state => state.user)
  const createSession = useSessionStore(state => state.createSession)
  const isLoading = useSessionStore(state => state.isLoading)
  const circleOfTrust = useCircleStore(state => state.circleOfTrust)
  const loadCircleOfTrust = useCircleStore(state => state.loadCircleOfTrust)

  const [destination, setDestination] = useState('')
  const [expectedReturnTime, setExpectedReturnTime] = useState(() => {
    const time = new Date()
    time.setHours(time.getHours() + 2)
    // Snap the default to a clean :00/:30 — the ±30-min stepper keeps it there.
    return roundToNearest30Minutes(time)
  })
  const {
    photo: outfitPhoto,
    showPicker: handlePickImage,
    clearPhoto: clearOutfitPhoto,
    restorePhoto: restoreOutfitPhoto,
  } = useImagePicker({ aspect: [3, 4] })
  const [locationSharing, setLocationSharing] = useState(true)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [inputFocused, setInputFocused] = useState(false)

  // Restore a draft stashed when the paywall interrupted this form (D3) —
  // ALL-OR-NOTHING (owner decision 2026-07-18): the user returns from
  // checkout to EXACTLY what they were setting up (including their chosen
  // return time, verbatim), or — if the deadline passed / 30 min elapsed —
  // to a fresh form. The one carve-out: a photo whose cache file didn't
  // survive the round-trip can't be silently dropped — ask for it again.
  useEffect(() => {
    consumeSessionDraft().then(draft => {
      if (!draft) return
      setDestination(draft.destination)
      setLocationSharing(draft.locationSharing)
      setExpectedReturnTime(new Date(draft.returnTimeIso))
      if (draft.outfitPhoto) {
        if (photoFileExists(draft.outfitPhoto.uri)) {
          restoreOutfitPhoto(draft.outfitPhoto)
        } else {
          Alert.alert(
            'Outfit photo',
            "Your outfit photo didn't survive the trip to checkout. Add it again?",
            [
              { text: 'Not now', style: 'cancel' },
              { text: 'Add photo', onPress: handlePickImage },
            ]
          )
        }
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!circleOfTrust) {
      loadCircleOfTrust()
    } else {
      const activeMembers = circleOfTrust.filter(m => m.status === 'active')
      if (activeMembers.length === 0) {
        Alert.alert(
          'Your Circle is empty',
          'Your Circle of Trust is notified when you miss check-in or trigger an SOS. Add at least one person to start a session.',
          [
            { text: 'Not now', style: 'cancel', onPress: () => router.back() },
            {
              text: 'Add to Circle',
              onPress: () => router.replace('/(tabs)/circle'),
            },
          ]
        )
      }
    }
  }, [circleOfTrust])

  const activeMembers = circleOfTrust?.filter(m => m.status === 'active') ?? []

  const validateForm = () => {
    const newErrors: Record<string, string> = {}

    if (!destination.trim()) {
      newErrors.destination = "Please enter where you're going"
    }

    const minDeadline = new Date(
      Date.now() + CHECKIN_CONFIG.MIN_SESSION_LEAD_MINUTES * 60_000
    )
    if (expectedReturnTime < minDeadline) {
      newErrors.time = `Return time must be at least ${CHECKIN_CONFIG.MIN_SESSION_LEAD_MINUTES} minutes from now`
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  // Bounds are surfaced, not silent (flow-review C3): the buttons disable
  // at the limits instead of swallowing taps.
  const canAddTime = (() => {
    const maxTime = new Date()
    maxTime.setHours(maxTime.getHours() + 24)
    const next = new Date(expectedReturnTime)
    next.setMinutes(next.getMinutes() + 30)
    return next <= maxTime
  })()

  const canSubtractTime = (() => {
    const next = new Date(expectedReturnTime)
    next.setMinutes(next.getMinutes() - 30)
    // The floor: a deadline is never set closer than the minimum lead.
    return (
      next.getTime() >=
      Date.now() + CHECKIN_CONFIG.MIN_SESSION_LEAD_MINUTES * 60_000
    )
  })()

  // Direct clock entry (tap the time → OS rotary picker). Alarm-app
  // semantics: the picked hh:mm means its NEXT occurrence — today if still
  // ahead, otherwise tomorrow — which is always within the 24h session cap.
  const handleTimePicked = (picked: Date) => {
    setExpectedReturnTime(
      nextOccurrenceOfTime(
        picked.getHours(),
        picked.getMinutes(),
        new Date(),
        CHECKIN_CONFIG.MIN_SESSION_LEAD_MINUTES
      )
    )
    setErrors(prev => {
      if (!prev.time) return prev
      const { time: _time, ...rest } = prev
      return rest
    })
  }

  const handleAddTime = () => {
    if (!canAddTime) return
    const newTime = new Date(expectedReturnTime)
    newTime.setMinutes(newTime.getMinutes() + 30)
    setExpectedReturnTime(newTime)
  }

  const handleSubtractTime = () => {
    if (!canSubtractTime) return
    const newTime = new Date(expectedReturnTime)
    newTime.setMinutes(newTime.getMinutes() - 30)
    setExpectedReturnTime(newTime)
  }

  const handleCreateSession = async () => {
    if (!validateForm()) {
      return
    }

    try {
      const session = await createSession({
        destination,
        expected_return_time: expectedReturnTime.toISOString(),
        location_sharing_enabled: locationSharing,
      })

      // Upload the outfit photo now that the session exists (the endpoint
      // keys on session_id). Best-effort — never block a safety session on a
      // photo upload; the active screen presigns + shows it when it loads.
      if (outfitPhoto) {
        try {
          await api.uploadOutfitPhoto(session.id, {
            uri: outfitPhoto.uri,
            type: outfitPhoto.mimeType,
            fileName: outfitPhoto.fileName ?? undefined,
          })
        } catch (err) {
          notify(err, 'session.upload-outfit-photo')
          toast.error(
            "Couldn't attach the outfit photo — session still started"
          )
        }
      }

      toast.success('Session started')
      router.replace(`/sessions/${session.id}`)
    } catch (error: any) {
      if (error.statusCode === 402 || error.requiresSubscription) {
        // Stash the form so /plans (confirming) can bring the user straight back
        // to the session they were arranging (D3) — checkout happens in an
        // external browser and this screen won't survive the round-trip.
        await saveSessionDraft({
          destination,
          locationSharing,
          returnTimeIso: expectedReturnTime.toISOString(),
          outfitPhoto: outfitPhoto
            ? {
                uri: outfitPhoto.uri,
                mimeType: outfitPhoto.mimeType,
                fileName: outfitPhoto.fileName ?? undefined,
              }
            : null,
        })
        router.push('/plans')
        return
      }
      toast.error(error.message || 'Failed to create session')
    }
  }

  const handleBack = () => router.back()

  return {
    destination,
    expectedReturnTime,
    outfitPhoto,
    locationSharing,
    errors,
    inputFocused,
    isLoading,
    circleOfTrust,
    activeMembers,

    setDestination,
    setLocationSharing,
    setInputFocused,

    // Handlers
    canAddTime,
    canSubtractTime,
    handleAddTime,
    handleSubtractTime,
    handleTimePicked,
    handlePickImage,
    handleCreateSession,
    handleBack,
  }
}
