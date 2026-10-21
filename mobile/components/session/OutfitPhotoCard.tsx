/**
 * Outfit photo block for the session screen — the photo attached at
 * check-in creation, shown read-only in both modes (no post-session editing
 * of what the Circle already saw).
 *
 * Related: app/sessions/[id].tsx, components/session/SessionDetailsCard.tsx.
 */
import { Image, StyleSheet, Text } from 'react-native'
import { COLORS, resolveUrl } from '../../constants'
import { SessionDetailsBlock } from './SessionDetailsCard'

interface OutfitPhotoCardProps {
  photoUrl: string
}

export function OutfitPhotoCard({ photoUrl }: OutfitPhotoCardProps) {
  return (
    <SessionDetailsBlock label="Pictures">
      <Text style={styles.pictureLabel}>Outfit</Text>
      <Image source={{ uri: resolveUrl(photoUrl) }} style={styles.outfitPhoto} />
    </SessionDetailsBlock>
  )
}

const styles = StyleSheet.create({
  pictureLabel: {
    fontSize: 13,
    color: COLORS.textLight,
    marginTop: 8,
    marginBottom: 6,
  },
  outfitPhoto: {
    width: '100%',
    height: 200,
    borderRadius: 8,
  },
})
