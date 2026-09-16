"""Pydantic response models for the JSON endpoints the frontend consumes.

These models exist only to publish response schemas to OpenAPI so the generated
TypeScript contract has concrete response types. They are never used as
``response_model`` on a route, so they do not validate or re-serialize anything
at runtime; the handlers keep returning the same dictionaries.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def response(model: type[BaseModel], description: str = "Successful response") -> dict:
    """OpenAPI ``responses`` mapping that documents a 200 body without changing runtime output."""
    return {200: {"model": model, "description": description}}


# --- Lists -----------------------------------------------------------------


class ListSummary(BaseModel):
    id: int | None = None
    list_type: str
    list_id: str
    list_url: str | None = None
    url: str | None = None
    display_name: str
    item_count: int = 0
    status: str | None = None
    last_synced: str | None = None
    user_id: str = "1"
    user_display_name: str | None = None


class ListsResponse(BaseModel):
    lists: list[ListSummary]


class AddListResponse(BaseModel):
    success: bool
    message: str
    list_url: str
    item_count: int
    user_id: str
    user_display_name: str | None = None


class UpdateListUserResponse(BaseModel):
    success: bool
    list_type: str
    list_id: str
    user_id: str
    user_display_name: str | None = None
    message: str


class DeleteListResponse(BaseModel):
    success: bool
    message: str


class ListItemsResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    has_more: bool


# --- Sync ------------------------------------------------------------------


class SyncTargetList(BaseModel):
    list_type: str
    list_id: str


class SyncSignalSent(BaseModel):
    pid: int
    cmdline: list[str] | None = None
    status: str | None = None


class SyncErrorDetail(BaseModel):
    pid: int | None = None
    error: str


class TriggerSyncResponse(BaseModel):
    success: bool
    sync_type: str
    target_list: SyncTargetList | None = None
    message: str
    signals_sent: list[SyncSignalSent]
    errors: list[SyncErrorDetail] | None = None
    note: str
    method: str
    timestamp: str


class SyncProcessInfo(BaseModel):
    pid: int
    status: str
    created: float | None = None
    cmdline: list[str] | None = None
    memory_percent: float | None = None
    cpu_percent: float | None = None
    can_signal: bool = True
    error: str | None = None


class SyncStatusResponse(BaseModel):
    processes_found: int
    processes: list[SyncProcessInfo]
    can_trigger_sync: bool
    sync_method: str
    timestamp: str


class LiveSyncStatusResponse(BaseModel):
    is_running: bool
    status: str
    sync_type: str | None = None
    session_id: str | None = None
    start_time: str | None = None
    duration_seconds: int | None = None
    list_type: str | None = None
    list_id: str | None = None
    pid: int | None = None
    error: str | None = None
    timestamp: str


class CancelSyncResponse(BaseModel):
    success: bool
    message: str
    job_id: str
    terminated: bool | None = None
    termination_method: str | None = None
    target_pid: int | None = None
    session_id: str | None = None
    pause_until: str | None = None
    timestamp: str


class SyncIntervalResponse(BaseModel):
    interval_hours: float
    source: str
    last_updated: str | None = None
    message: str | None = None


class UpdateSyncIntervalResponse(BaseModel):
    success: bool
    message: str
    interval_hours: float
    source: str


# --- Seerr / system --------------------------------------------------------


class OverseerrUser(BaseModel):
    id: str
    display_name: str
    email: str
    avatar: str


class OverseerrUsersResponse(BaseModel):
    success: bool
    users: list[OverseerrUser]
    count: int


class OverseerrUsersSyncResponse(BaseModel):
    success: bool
    message: str
    users: list[OverseerrUser]
    count: int


class OverseerrStatusResponse(BaseModel):
    isConnected: bool
    version: str | None = None
    updateAvailable: bool | None = None
    commitsBehind: int | None = None
    restartRequired: bool | None = None
    error: str | None = None
    lastChecked: str


class SystemHealthResponse(BaseModel):
    database: bool
    process: bool
    sync_status: str | None = None
    last_sync: str | None = None
    next_sync: str | None = None


# --- Stats -----------------------------------------------------------------


class SyncStatsBreakdown(BaseModel):
    newly_requested: int
    already_requested: int
    available: int
    skipped: int
    errors: int


class SyncStatsResponse(BaseModel):
    total_processed: int
    successful_items: int
    total_requested: int
    total_errors: int
    success_rate: float
    duplicates_in_current_sync: int
    last_updated: str | None = None
    breakdown: SyncStatsBreakdown


# --- Collections -----------------------------------------------------------


class CollectionSyncedInfo(BaseModel):
    last_synced: str | None = None
    item_count: int = 0


class CollectionRatingEntry(BaseModel):
    id: int
    title: str
    rating: float


class CollectionMovie(BaseModel):
    id: int
    title: str
    original_title: str | None = None
    rating: float | None = None
    voteCount: int | None = None
    releaseDate: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    overview: str | None = None
    tagline: str | None = None
    runtime: int | None = None
    genres: list[str] | None = None
    imdb_id: str | None = None
    popularity: float | None = None
    budget: int | None = None
    revenue: int | None = None
    status: str | None = None
    original_language: str | None = None
    production_countries: list[str] | None = None
    spoken_languages: list[str] | None = None


class CollectionDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    franchise: str
    totalMovies: int = 0
    totalVotes: int = 0
    averageRating: float = 0
    popularityScore: float = 0
    movieIds: list[int] | None = None
    movieRatings: list[CollectionMovie] | None = None
    highestRatedMovie: CollectionRatingEntry | None = None
    lowestRatedMovie: CollectionRatingEntry | None = None
    collectionId: int | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    poster_url: str | None = None
    overview: str | None = None
    synced_info: CollectionSyncedInfo | None = Field(default=None, alias="_synced_info")


class CollectionsResponse(BaseModel):
    collections: list[CollectionDetail]
    total: int
    page: int
    total_pages: int
    limit: int


class PopularCollectionsResponse(BaseModel):
    collections: list[CollectionDetail]


class CollectionMoviesResponse(BaseModel):
    franchise: str
    movies: list[CollectionMovie]
    total: int


class CollectionPosterResponse(BaseModel):
    poster_url: str | None = None
    movie_id: int | None = None
