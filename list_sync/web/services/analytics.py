"""services.analytics — moved verbatim from api_server.py (modularize-api-server)."""

from datetime import UTC
from datetime import datetime
from datetime import timedelta
import logging

from pydantic import BaseModel

from list_sync.database import get_analytics_payload
class AnalyticsOverview(BaseModel):
    total_items: int
    success_rate: float
    avg_processing_time: float
    active_sync: bool
    total_sync_operations: int
    total_errors: int
    last_sync_time: str


class MediaAdditionData(BaseModel):
    timestamp: str
    count: int
    type: str  # 'movie' or 'tv'
    source: str


class ListFetchData(BaseModel):
    timestamp: str
    success_rate: float
    total_attempts: int
    successful_fetches: int
    failed_fetches: int
    source: str


class LowConfidenceMatch(BaseModel):
    title: str
    year: int | None = None
    score: float
    original_title: str | None = None
    source: str
    timestamp: str
    needs_review: bool


class MatchingData(BaseModel):
    perfect_matches: int
    partial_matches: int
    failed_matches: int
    average_score: float
    low_confidence_matches: list[LowConfidenceMatch]


class SearchFailureData(BaseModel):
    title: str
    search_count: int
    last_attempt: str
    sources: list[str]
    type: str  # 'movie' or 'tv'


class ScrapingPerformanceData(BaseModel):
    timestamp: str
    items_per_minute: float
    source: str
    total_items: int
    processing_time: float


class SourceDistributionData(BaseModel):
    source: str
    items_found: int
    average_items_per_page: float
    total_pages: int
    success_rate: float


class SelectorPerformanceData(BaseModel):
    website: str
    selector: str
    success_rate: float
    total_attempts: int
    last_used: str
    status: str  # 'working', 'failing', 'deprecated'


class GenreDistributionData(BaseModel):
    genre: str
    count: int
    percentage: float


class YearDistributionData(BaseModel):
    year: int
    count: int
    type: str  # 'movie' or 'tv'


class AnalyticsResponse(BaseModel):
    overview: AnalyticsOverview
    media_additions: list[MediaAdditionData]
    list_fetches: list[ListFetchData]
    matching: MatchingData
    search_failures: list[SearchFailureData]
    scraping_performance: list[ScrapingPerformanceData]
    source_distribution: list[SourceDistributionData]
    selector_performance: list[SelectorPerformanceData]
    genre_distribution: list[GenreDistributionData]
    year_distribution: list[YearDistributionData]


def process_analytics_data(time_range: str = "24h", category: str = "all") -> AnalyticsResponse:
    """Generate analytics from structured sync records."""
    try:
        now = datetime.now(UTC)
        if time_range == "1h":
            start_time = now - timedelta(hours=1)
        elif time_range == "24h":
            start_time = now - timedelta(hours=24)
        elif time_range == "7d":
            start_time = now - timedelta(days=7)
        elif time_range == "30d":
            start_time = now - timedelta(days=30)
        else:
            start_time = now - timedelta(hours=24)

        payload = get_analytics_payload(start=start_time.isoformat(), end=now.isoformat())
        return AnalyticsResponse(**payload)

    except Exception as e:
        logging.exception(f"Error processing analytics data: {e}")
        return AnalyticsResponse(
            overview=AnalyticsOverview(
                total_items=0,
                success_rate=0.0,
                avg_processing_time=0.0,
                active_sync=False,
                total_sync_operations=0,
                total_errors=0,
                last_sync_time="",
            ),
            media_additions=[],
            list_fetches=[],
            matching=MatchingData(
                perfect_matches=0,
                partial_matches=0,
                failed_matches=0,
                average_score=0.0,
                low_confidence_matches=[],
            ),
            search_failures=[],
            scraping_performance=[],
            source_distribution=[],
            selector_performance=[],
            genre_distribution=[],
            year_distribution=[],
        )
