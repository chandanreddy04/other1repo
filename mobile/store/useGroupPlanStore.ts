import { create } from 'zustand'
import api from '../services/api'
import { GroupPlan } from '../types'

interface GroupPlanState {
  plan: GroupPlan | null
  isLoading: boolean
  error: string | null

  fetchGroupPlan: () => Promise<void>
  joinPlan: (inviteCode: string) => Promise<void>
  leavePlan: (planId: string) => Promise<void>
  removeMember: (planId: string, memberId: string) => Promise<void>
  regenerateInvite: (planId: string) => Promise<void>
  reset: () => void
}

export const useGroupPlanStore = create<GroupPlanState>((set, get) => ({
  plan: null,
  isLoading: false,
  error: null,

  fetchGroupPlan: async () => {
    set({ isLoading: true, error: null })
    try {
      const plan = await api.getGroupPlan()
      set({ plan, isLoading: false })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to fetch group plan'
      set({ error: message, isLoading: false })
    }
  },

  joinPlan: async (inviteCode: string) => {
    set({ isLoading: true, error: null })
    try {
      await api.joinGroupPlan(inviteCode)
      await get().fetchGroupPlan()
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to join plan'
      set({ error: message, isLoading: false })
      throw error
    }
  },

  leavePlan: async (planId: string) => {
    set({ isLoading: true, error: null })
    try {
      await api.leaveGroupPlan(planId)
      set({ plan: null, isLoading: false })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to leave plan'
      set({ error: message, isLoading: false })
      throw error
    }
  },

  removeMember: async (planId: string, memberId: string) => {
    set({ isLoading: true, error: null })
    try {
      await api.removeGroupMember(planId, memberId)
      await get().fetchGroupPlan()
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to remove member'
      set({ error: message, isLoading: false })
      throw error
    }
  },

  regenerateInvite: async (planId: string) => {
    set({ isLoading: true, error: null })
    try {
      const result = await api.regenerateGroupInvite(planId)
      const current = get().plan
      if (current) {
        set({
          plan: { ...current, invite_code: result.invite_code },
          isLoading: false,
        })
      } else {
        set({ isLoading: false })
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to regenerate invite'
      set({ error: message, isLoading: false })
      throw error
    }
  },

  reset: () => set({ plan: null, isLoading: false, error: null }),
}))
