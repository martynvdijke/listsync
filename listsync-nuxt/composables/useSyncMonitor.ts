/**
 * Sync monitoring composable
 *
 * Polls the backend live sync status endpoint (`/api/sync/status/live`). That
 * endpoint returns JSON, not an SSE stream, so `useSmartPolling` is used and
 * each response is pushed into the event feed and the sync store.
 */

import { ref } from 'vue'
import type { ApiLiveSyncStatusResponse } from '~/types'
import { useSmartPolling } from './useRealtime'

export interface SyncEvent {
  type: 'log' | 'progress' | 'status' | 'error'
  data: any
  timestamp: string
}

export const useSyncMonitor = (intervalMs: number = 5000) => {
  const isConnected = ref(false)
  const lastEvent = ref<SyncEvent | null>(null)
  const events = ref<SyncEvent[]>([])
  const error = ref<string | null>(null)

  const poll = async () => {
    const config = useRuntimeConfig()
    const apiUrl = config.public.apiUrl || 'http://localhost:4222'
    const apiBase = config.public.apiBase || '/api'

    try {
      const data = await $fetch<ApiLiveSyncStatusResponse>(`${apiUrl}${apiBase}/sync/status/live`)
      isConnected.value = true
      error.value = null

      const syncEvent: SyncEvent = {
        type: 'status',
        data,
        timestamp: new Date().toISOString(),
      }

      lastEvent.value = syncEvent
      events.value.push(syncEvent)
      if (events.value.length > 100) {
        events.value.shift()
      }

      const syncStore = useSyncStore()
      syncStore.isRunning = data.is_running || false
      syncStore.status = data.status || 'idle'
      syncStore.liveSyncStatus = data
    } catch (err) {
      isConnected.value = false
      error.value = 'Connection lost'
      console.error('[SyncMonitor] Failed to poll sync status:', err)
    }
  }

  const { startPolling, stopPolling, resume } = useSmartPolling(poll, intervalMs)

  const connect = () => {
    startPolling()
  }

  const disconnect = () => {
    stopPolling()
    isConnected.value = false
  }

  const retry = () => {
    resume()
    startPolling()
  }

  const clearEvents = () => {
    events.value = []
    lastEvent.value = null
  }

  return {
    isConnected,
    lastEvent,
    events,
    error,
    connect,
    disconnect,
    retry,
    clearEvents,
  }
}
