// Core types for ListSync Nuxt Frontend
//
// `./api` is generated from the backend OpenAPI schema by `npm run openapi`.
// Responses of the endpoints the backend publishes a schema for are aliases
// into that generated contract (see "Generated API contract" below). The
// hand-written interfaces that remain cover routes whose 200 response is still
// schema-less and shapes that are frontend-only (forms, store state, UI).

import type { components } from './api'

export type { components, operations, paths } from './api'

type Schemas = components['schemas']

// ==========================================
// Generated API contract
// ==========================================

// Response types used by `useApiService` / stores. Each alias exists only when
// the backend route publishes a response model; regenerate with `npm run openapi`.

/** Response of `GET /api/stats/sync`. */
export type ApiStatsResponse = Schemas['SyncStatsResponse']
/** Response of `GET /api/system/health`. */
export type ApiSystemHealthResponse = Schemas['SystemHealthResponse']
/** Response of `GET /api/sync/status`. */
export type ApiSyncStatusResponse = Schemas['SyncStatusResponse']
/** Response of `GET /api/sync/status/live`. */
export type ApiLiveSyncStatusResponse = Schemas['LiveSyncStatusResponse']
/** Response of `POST /api/sync/trigger` and `POST /api/sync/single`. */
export type ApiTriggerSyncResponse = Schemas['TriggerSyncResponse']
/** Response of `POST /api/sync/{job_id}/cancel`. */
export type ApiCancelSyncResponse = Schemas['CancelSyncResponse']
/** Response of `GET /api/sync-interval`. */
export type ApiSyncIntervalResponse = Schemas['SyncIntervalResponse']
/** Response of `PUT /api/sync-interval`. */
export type ApiUpdateSyncIntervalResponse = Schemas['UpdateSyncIntervalResponse']
/** Response of `GET /api/lists`. */
export type ApiListsResponse = Schemas['ListsResponse']
/** Response of `POST /api/lists`. */
export type ApiAddListResponse = Schemas['AddListResponse']
/** Response of `GET /api/lists/{list_type}/{list_id}/items`. */
export type ApiListItemsResponse = Schemas['ListItemsResponse']
/** Response of `PATCH /api/lists/{list_type}/{list_id}/user`. */
export type ApiUpdateListUserResponse = Schemas['UpdateListUserResponse']
/** Response of `DELETE /api/lists/{list_type}/{list_id}`. */
export type ApiDeleteListResponse = Schemas['DeleteListResponse']
/** Response of `GET /api/overseerr/users`. */
export type ApiOverseerrUsersResponse = Schemas['OverseerrUsersResponse']
/** Response of `POST /api/overseerr/users/sync`. */
export type ApiOverseerrUsersSyncResponse = Schemas['OverseerrUsersSyncResponse']
/** Response of `GET /api/overseerr/status`. */
export type ApiOverseerrStatusResponse = Schemas['OverseerrStatusResponse']
/** Response of `GET /api/collections`. */
export type ApiCollectionsResponse = Schemas['CollectionsResponse']
/** Response of `GET /api/collections/popular`. */
export type ApiPopularCollectionsResponse = Schemas['PopularCollectionsResponse']
/** Response of `GET /api/collections/{franchise_name}`. */
export type ApiCollectionDetail = Schemas['CollectionDetail']
/** Response of `GET /api/collections/{franchise_name}/movies`. */
export type ApiCollectionMoviesResponse = Schemas['CollectionMoviesResponse']
/** Response of `GET /api/collections/{franchise_name}/poster`. */
export type ApiCollectionPosterResponse = Schemas['CollectionPosterResponse']

/** Request body of `POST /api/lists`. */
export type ApiListAddRequest = Schemas['ListAdd']

/**
 * `ListAdd` marks `user_id` required because the schema gives it a default;
 * the API accepts it omitted and applies that default, so callers may leave it
 * out.
 */
export type ApiListAddInput = Omit<ApiListAddRequest, 'user_id'> & Partial<Pick<ApiListAddRequest, 'user_id'>>

/** Request body of `PATCH /api/lists/{list_type}/{list_id}/user`. */
export type ApiListUserUpdateRequest = Schemas['ListUserUpdate']

/** Request body of `PUT /api/sync-interval`. */
export type ApiSyncIntervalUpdateRequest = Schemas['SyncIntervalUpdate']

// ==========================================
// App-facing aliases of the generated shapes
// ==========================================

export type List = Schemas['ListSummary']
export type SyncStats = ApiStatsResponse
export type SystemHealth = ApiSystemHealthResponse
export type SyncProcessStatus = ApiSyncStatusResponse
export type LiveSyncStatus = ApiLiveSyncStatusResponse
export type OverseerrUser = Schemas['OverseerrUser']
export type OverseerrStatus = ApiOverseerrStatusResponse
export type SyncInterval = ApiSyncIntervalResponse
export type Collection = Schemas['CollectionDetail']
export type CollectionMovie = Schemas['CollectionMovie']
export type CollectionsResponse = ApiCollectionsResponse
export type CollectionMoviesResponse = ApiCollectionMoviesResponse
export type CollectionPosterResponse = ApiCollectionPosterResponse

// ==========================================
// Frontend-only types
// ==========================================

export interface MediaItem {
  title: string
  mediaType: 'movie' | 'tv'
  year?: number
  imdbId?: string
  overseerrId?: number
  status: 'pending' | 'available' | 'requested' | 'failed'
  lastSynced: string
}

export interface SyncJob {
  id: string
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  startTime: string
  endTime?: string
  itemsProcessed: number
  totalItems: number
  errors?: string[]
}

export interface Config {
  overseerrUrl: string
  overseerrApiKey: string
  overseerrUserId: string
  syncInterval: number
  automatedMode: boolean
  overseerr4K: boolean
  discordWebhookUrl?: string
  gotifyUrl?: string
  gotifyToken?: string
  gotifyEnabled?: boolean
}

export interface ConnectionStatus {
  isConnected: boolean
  lastChecked: string
  error?: string
}

export interface CreateListRequest {
  list_type: 'imdb' | 'trakt' | 'trakt_special' | 'letterboxd' | 'mdblist' | 'stevenlu' | 'tmdb' | 'simkl' | 'tvdb'
  list_id: string
  user_id?: string
}

export interface UpdateConfigRequest {
  overseerrUrl?: string
  overseerrApiKey?: string
  overseerrUserId?: string
  syncInterval?: number
  automatedMode?: boolean
  overseerr4K?: boolean
  discordWebhookUrl?: string
  gotifyUrl?: string
  gotifyToken?: string
  gotifyEnabled?: boolean
}

export interface ListValidation {
  isValid: boolean
  itemCount?: number
  error?: string
  previewItems?: Array<{
    title: string
    year?: number
    mediaType: 'movie' | 'tv'
  }>
}

export interface SyncResult {
  id: string
  timestamp: string
  listsProcessed: number
  itemsFound: number
  itemsRequested: number
  itemsSkipped: number
  errors: number
  duration: number
  syncedLists: Array<{
    type: string
    id: string
    itemCount: number
    url?: string
    error?: string
  }>
}

export interface SyncOptions {
  dryRun?: boolean
  is4K?: boolean
  specificLists?: string[]
}

export interface DashboardData {
  stats: SyncStats
  recentActivity: MediaItem[]
  systemHealth: SystemHealth
  activeJobs: SyncJob[]
}

export interface RecentActivity {
  id: number
  title: string
  media_type: 'movie' | 'tv'
  status: string
  last_synced: string
  action: 'synced' | 'requested' | 'available' | 'error' | 'skipped'
}

export interface ProcessedItem {
  id: number
  title: string
  media_type: 'movie' | 'tv'
  status: string
  last_synced: string
  imdb_id?: string
  tmdb_id?: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  limit: number
  total_pages: number
}

// API Response types
export interface ApiResponse<T> {
  data?: T
  error?: string
  message?: string
}

// Toast notification types
export interface ToastNotification {
  id: string
  type: 'success' | 'error' | 'info' | 'warning'
  title: string
  message?: string
  duration?: number
}

// UI State types
export interface UIState {
  sidebarCollapsed: boolean
  mobileMenuOpen: boolean
  theme: 'dark' | 'light'
}

// ==========================================
// Sync History Types
// ==========================================

export interface SyncHistoryList {
  type: string
  id: string
  url: string | null
  item_count: number
}

export interface SyncHistoryItem {
  title: string
  status: 'requested' | 'already_available' | 'already_requested' | 'skipped' | 'not_found' | 'error'
  progress_number: number
  progress_total: number
  timestamp: string
  year: number | null
  media_type: 'movie' | 'tv'
  error_details: string | null
}

export interface SyncHistoryResults {
  requested: number
  already_available: number
  already_requested: number
  skipped: number
  not_found: number
  error: number
}

export interface SyncHistoryError {
  title: string
  error: string
  timestamp: string
}

export interface SyncHistorySession {
  id: string
  type: 'full' | 'single'
  start_timestamp: string
  end_timestamp: string | null
  duration: number | null
  version: string | null
  total_items: number
  processed_items: number
  lists: SyncHistoryList[]
  results: SyncHistoryResults
  items: SyncHistoryItem[]
  errors: SyncHistoryError[]
  not_found_items: string[]
  average_time_ms: number | null
  total_time_seconds: number | null
  status: 'completed' | 'in_progress' | 'failed'
}

export interface SyncHistoryResponse {
  sessions: SyncHistorySession[]
  total: number
  limit: number
  offset: number
}

export interface SyncHistoryStats {
  total_sessions: number
  full_syncs: number
  single_syncs: number
  total_items_processed: number
  total_requested: number
  total_errors: number
  success_rate: number
  avg_items_per_sync: number
  avg_duration_seconds: number | null
  recent_stats: {
    last_24h: number
    last_7d: number
    last_30d: number
  }
  most_synced_lists: Array<{
    list: string
    count: number
  }>
}

export interface EnrichedMediaItem {
  id: number
  title: string
  media_type: 'movie' | 'tv'
  year?: number
  poster_url?: string
  rating?: number
  overview?: string
  genres?: string[]
  status: string
  overseerr_url?: string
  imdb_id?: string
  tmdb_id?: number
  list_name?: string
  last_synced?: string
  list_sources?: Array<{
    list_type: string
    list_id: string
    display_name?: string
  }>
}

export interface FailedItem {
  id: string
  title: string
  description: string
  media_type: 'movie' | 'tv'
  year?: number
  failed_at: string
  error_type: 'not_found' | 'error'
  error_message: string
  retryable: boolean
}

export interface FailedItemsResponse {
  items: FailedItem[]
  total: number
  pagination: {
    page: number
    limit: number
    total_items: number
    total_pages: number
    has_next: boolean
    has_prev: boolean
  }
}

/**
 * Response of `POST /api/collections/{franchise_name}/sync`.
 *
 * This route publishes no response model yet, so the shape stays hand-written.
 */
export interface CollectionSyncResponse {
  success: boolean
  franchise: string
  items_processed: number
  results: {
    requested: number
    already_requested: number
    request_failed: number
    errors: string[]
  }
}
