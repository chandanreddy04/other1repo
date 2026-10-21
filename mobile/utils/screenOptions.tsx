import React from 'react'
import { TouchableOpacity } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { COLORS } from '../constants'
import type { Router } from 'expo-router'

export const settingsScreenOptions = (title: string, router: Router) => ({
  headerShown: true,
  headerTitle: title,
  headerStyle: {
    backgroundColor: COLORS.white,
  },
  headerTintColor: COLORS.primary,
  headerLeft: () => (
    <TouchableOpacity onPress={() => router.back()} style={{ marginLeft: 5 }}>
      <Ionicons name="chevron-back" size={24} color={COLORS.primary} />
    </TouchableOpacity>
  ),
})
