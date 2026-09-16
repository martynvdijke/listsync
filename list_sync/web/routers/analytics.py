"""routers.analytics — moved verbatim from api_server.py (modularize-api-server)."""

import logging
import os

from fastapi import APIRouter, HTTPException, Query

from list_sync.config import load_env_config
from list_sync.database import (
    DB_FILE,
    get_duplicate_count,
    get_recent_sync_items,
    normalize_list_id,
    query_requested_items,
    query_sync_items,
)
from list_sync.web.common import (
    REPORTING_FAILURE_STATUSES,
    REPORTING_SUCCESS_STATUSES,
    analyze_data_quality,
    build_log_info,
    get_deduplicated_items,
)
from list_sync.web.services.analytics import process_analytics_data

router = APIRouter()


@router.get("/api/stats/sync")
async def get_sync_stats():
    """Get deduplicated sync statistics"""
    try:
        unique_items = get_deduplicated_items()

        # Categorize statuses based on user requirements
        newly_requested_statuses = ["requested"]  # Actually requested during this sync
        already_requested_statuses = ["already_requested"]  # Were already in Seerr
        available_statuses = ["already_available", "available"]
        skipped_statuses = ["skipped"]
        error_statuses = ["not_found", "error"]

        newly_requested_count = sum(1 for item in unique_items if item[6] in newly_requested_statuses)
        already_requested_count = sum(1 for item in unique_items if item[6] in already_requested_statuses)
        available_count = sum(1 for item in unique_items if item[6] in available_statuses)
        skipped_count = sum(1 for item in unique_items if item[6] in skipped_statuses)
        error_count = sum(1 for item in unique_items if item[6] in error_statuses)

        # Get duplicates from the most recent sync session in the database
        duplicates_in_current_sync = get_duplicate_count()

        # Count failures from the same structured source as /api/failures
        try:
            log_based_errors = query_sync_items(statuses=["not_found", "error", "request_failed"], limit=0)["total"]
            logging.debug(f"DEBUG - Found {log_based_errors} failures from sync_items (same as /failures page)")
        except Exception as e:
            logging.debug(f"DEBUG - Could not query failures from database: {e}")
            log_based_errors = error_count

        # Calculate simplified metrics
        total_processed = len(unique_items)
        successful_items = (
            newly_requested_count + already_requested_count + available_count + skipped_count
        )  # All non-error items
        total_requested = newly_requested_count  # Only items actually requested during this sync
        total_errors = log_based_errors  # Use same count as /failures page for consistency

        # Success rate based on non-error items
        success_rate = (successful_items / total_processed * 100) if total_processed > 0 else 0

        # Debug: Print status breakdown
        logging.debug("DEBUG - Simplified Stats:")
        logging.info(f"  Total Processed: {total_processed}")
        logging.info(
            f"  Successful: {successful_items} (newly requested: {newly_requested_count}, already requested: {already_requested_count}, available: {available_count}, skipped: {skipped_count})"
        )
        logging.info(f"  Total Requested (NEW): {total_requested}")
        logging.info(f"  Already Requested: {already_requested_count}")
        logging.warning(f"  Errors: {total_errors} (from sync_items, same as /failures page)")
        logging.info(f"  Success Rate: {success_rate:.1f}%")
        logging.info(f"  Duplicates in current sync: {duplicates_in_current_sync}")

        # Get actual last sync time from the database
        log_info = build_log_info()
        last_updated = log_info.last_sync_complete or log_info.log_last_modified

        return {
            "total_processed": total_processed,
            "successful_items": successful_items,
            "total_requested": total_requested,  # Only newly requested items
            "total_errors": total_errors,
            "success_rate": success_rate,
            "duplicates_in_current_sync": duplicates_in_current_sync,  # New field for current sync duplicates
            "last_updated": last_updated,
            # Keep detailed breakdown for other endpoints that might need it
            "breakdown": {
                "newly_requested": newly_requested_count,
                "already_requested": already_requested_count,
                "available": available_count,
                "skipped": skipped_count,
                "errors": log_based_errors,  # Use structured errors for consistency with /failures
            },
        }
    except Exception as e:
        logging.exception(f"ERROR in get_sync_stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/stats/data-quality")
async def get_data_quality():
    """Get data quality analysis"""
    try:
        analysis = analyze_data_quality()
        if analysis is None:
            raise HTTPException(status_code=500, detail="Could not analyze data quality")
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/stats/status-breakdown")
async def get_status_breakdown():
    """Get success/failure categorization"""
    try:
        unique_items = get_deduplicated_items()

        success_statuses = ["already_available", "already_requested", "available", "requested"]
        failure_statuses = ["not_found", "error"]

        successful_items = [item for item in unique_items if item[6] in success_statuses]
        failed_items = [item for item in unique_items if item[6] in failure_statuses]
        other_items = [item for item in unique_items if item[6] not in success_statuses + failure_statuses]

        return {
            "successful": {
                "count": len(successful_items),
                "statuses": success_statuses,
            },
            "failed": {
                "count": len(failed_items),
                "statuses": failure_statuses,
            },
            "other": {
                "count": len(other_items),
                "statuses": list(set(item[6] for item in other_items)),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/activity/recent")
async def get_recent_activity(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(5, ge=1, le=20, description="Items per page (max 20)"),
):
    """Get recent sync activity from structured sync records with pagination"""
    try:
        recent_items = get_recent_sync_items(limit=500)

        total_items = len(recent_items)
        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 0
        start_index = (page - 1) * limit
        paginated_items = recent_items[start_index : start_index + limit]

        return {
            "items": paginated_items,
            "total_items": total_items,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
            "log_file_used": "database",
        }

    except Exception as e:
        logging.exception(f"Error loading recent activity: {e}")
        return {
            "items": [],
            "total_items": 0,
            "page": page,
            "limit": limit,
            "total_pages": 0,
            "has_next": False,
            "has_prev": False,
            "error": f"Failed to load recent activity: {e!s}",
        }


@router.get("/api/activity/recent/docker")
async def get_recent_activity_from_docker(limit: int = Query(10, ge=1, le=100)):
    """Get recent sync activity from structured sync records"""
    try:
        result = query_sync_items(limit=limit)
        action_map = {
            "already_available": "available",
            "already_requested": "requested",
            "requested": "requested",
            "skipped": "skipped",
            "not_found": "error",
            "error": "error",
            "request_failed": "error",
        }
        return [
            {
                "id": f"sitem-{row['row_id']}",
                "title": row["title"],
                "media_type": row["media_type"],
                "status": row["status"],
                "last_synced": row["processed_at"],
                "action": action_map.get(row["status"], row["status"]),
                "item_number": row["item_number"] or 0,
                "total_items": row["total_items"] or 0,
            }
            for row in result["items"]
        ]
    except Exception as e:
        logging.exception(f"Error loading recent activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/failures")
async def get_failures(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: str = Query("", description="Search term to filter items by title"),
    failure_type_filter: str = Query("", description="Filter by failure type (not_found/error)"),
    media_type_filter: str = Query("", description="Filter by media type (movie/tv)"),
):
    """Get all failures from structured sync records with search/filter and pagination"""
    try:
        result = query_sync_items(
            statuses=list(REPORTING_FAILURE_STATUSES),
            search=search,
            media_type=media_type_filter or None,
        )

        all_failures = []
        for row in result["items"]:
            failure_type = "not_found" if row["status"] == "not_found" else "error"
            if failure_type_filter.strip() and failure_type != failure_type_filter:
                continue

            error_details = row.get("error_details")
            if not error_details:
                error_details = (
                    "Item not found in Seerr database" if failure_type == "not_found" else "Processing error"
                )

            all_failures.append(
                {
                    "name": row["title"],
                    "title": row["title"],
                    "media_type": row.get("media_type") or "movie",
                    "year": row.get("year"),
                    "timestamp": row.get("processed_at"),
                    "item_number": row.get("item_number"),
                    "total_items": row.get("total_items"),
                    "sync_session": row.get("sync_session"),
                    "failure_type": failure_type,
                    "error_type": failure_type,
                    "error_details": error_details,
                    "error_message": error_details,
                    "retryable": failure_type == "error",
                    "failed_at": row.get("processed_at") or "",
                }
            )

        total_items = len(all_failures)
        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 0
        start = (page - 1) * limit
        paginated_failures = all_failures[start : start + limit]

        paginated_not_found = [item for item in paginated_failures if item["failure_type"] == "not_found"]
        paginated_errors = [item for item in paginated_failures if item["failure_type"] == "error"]

        for item in paginated_not_found:
            item.pop("failure_type", None)
        for item in paginated_errors:
            item.pop("failure_type", None)

        return {
            "not_found": paginated_not_found,
            "errors": paginated_errors,
            "total_failures": query_sync_items(statuses=list(REPORTING_FAILURE_STATUSES), limit=0)["total"],
            "filtered_count": total_items,
            "last_sync_time": build_log_info().last_sync_complete or "",
            "log_file_exists": os.path.exists(DB_FILE),
            "filters": {
                "search": search,
                "failure_type_filter": failure_type_filter,
                "media_type_filter": media_type_filter,
            },
            "pagination": {
                "page": page,
                "limit": limit,
                "total_items": total_items,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        }
    except Exception as e:
        logging.exception(f"Error loading failures: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/processed")
async def get_processed_items(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: str = Query("", description="Search term to filter items by title"),
    status_filter: str = Query("", description="Filter by status"),
    media_type_filter: str = Query("", description="Filter by media type (movie/tv)"),
    list_source: str = Query("", description="Filter by list source in format 'list_type:list_id'"),
):
    """Get all processed items from the database with search/filter and pagination"""
    try:
        list_type = list_id = None
        if list_source and list_source.strip():
            if ":" in list_source:
                raw_type, raw_id = list_source.split(":", 1)
                list_type = raw_type
                list_id = normalize_list_id(raw_type, raw_id)
            else:
                logging.warning(f"Invalid list_source format: {list_source}, expected 'list_type:list_id'")

        result = query_sync_items(
            statuses=[status_filter] if status_filter.strip() else None,
            search=search,
            media_type=media_type_filter or None,
            list_type=list_type,
            list_id=list_id,
            limit=limit,
            offset=(page - 1) * limit,
        )
        total_count = query_sync_items(limit=0)["total"]

        try:
            seerr_base_url, _, _, _, _, _ = load_env_config()
            seerr_base_url = seerr_base_url.rstrip("/") if seerr_base_url else None
        except Exception as e:
            logging.debug("Failed to load Seerr base URL: %s", e)
            seerr_base_url = None

        items = []
        for row in result["items"]:
            status = row["status"]
            overseerr_url = None
            if seerr_base_url and row.get("overseerr_id"):
                overseerr_url = f"{seerr_base_url}/{row['media_type']}/{row['overseerr_id']}"

            if row.get("source_list_type") and row.get("source_list_id"):
                list_sources = [
                    {
                        "list_type": row["source_list_type"],
                        "list_id": row["source_list_id"],
                        "display_name": None,
                    }
                ]
            elif row.get("list_type") and row.get("list_id"):
                list_sources = [{"list_type": row["list_type"], "list_id": row["list_id"], "display_name": None}]
            else:
                list_sources = []

            items.append(
                {
                    "id": row["row_id"],
                    "title": row["title"],
                    "year": row["year"],
                    "media_type": row["media_type"],
                    "status": status,
                    "category": "successful" if status in REPORTING_SUCCESS_STATUSES else "failed",
                    "timestamp": row["processed_at"],
                    "item_number": row["item_number"],
                    "total_items": row["total_items"],
                    "sync_session": row["sync_session"],
                    "action": status.replace("_", " ").title(),
                    "imdb_id": row["imdb_id"],
                    "overseerr_id": row["overseerr_id"],
                    "db_status": row["db_status"],
                    "source_list_type": row["source_list_type"],
                    "source_list_id": row["source_list_id"],
                    "overseerr_url": overseerr_url,
                    "list_sources": list_sources,
                }
            )

        total_items = result["total"]
        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 0
        return {
            "items": items,
            "total_count": total_count,
            "filtered_count": total_items,
            "sync_sessions": result["sessions"],
            "log_file_exists": os.path.exists(DB_FILE),
            "filters": {
                "search": search,
                "status_filter": status_filter,
                "media_type_filter": media_type_filter,
                "list_source": list_source,
            },
            "pagination": {
                "page": page,
                "limit": limit,
                "total_items": total_items,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        }
    except Exception as e:
        logging.exception(f"Error loading processed items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/successful")
async def get_successful_items(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: str = Query("", description="Search term to filter items by title"),
    status_filter: str = Query("", description="Filter by status"),
    media_type_filter: str = Query("", description="Filter by media type (movie/tv)"),
):
    """Get all successful items from the database with search/filter and pagination"""
    try:
        result = query_sync_items(
            statuses=list(REPORTING_SUCCESS_STATUSES),
            search=search,
            media_type=media_type_filter or None,
            limit=limit,
            offset=(page - 1) * limit,
        )
        total_count = query_sync_items(statuses=list(REPORTING_SUCCESS_STATUSES), limit=0)["total"]

        try:
            seerr_base_url, _, _, _, _, _ = load_env_config()
            seerr_base_url = seerr_base_url.rstrip("/") if seerr_base_url else None
        except Exception as e:
            logging.debug("Failed to load Seerr base URL: %s", e)
            seerr_base_url = None

        items = []
        for row in result["items"]:
            status = row["status"]
            overseerr_url = None
            if seerr_base_url and row.get("overseerr_id"):
                overseerr_url = f"{seerr_base_url}/{row['media_type']}/{row['overseerr_id']}"

            items.append(
                {
                    "id": row["row_id"],
                    "title": row["title"],
                    "year": row["year"],
                    "media_type": row["media_type"],
                    "status": status,
                    "category": "successful",
                    "timestamp": row["processed_at"],
                    "item_number": row["item_number"],
                    "total_items": row["total_items"],
                    "sync_session": row["sync_session"],
                    "action": status.replace("_", " ").title(),
                    "imdb_id": row["imdb_id"],
                    "overseerr_id": row["overseerr_id"],
                    "db_status": row["db_status"],
                    "source_list_type": row["source_list_type"],
                    "source_list_id": row["source_list_id"],
                    "overseerr_url": overseerr_url,
                }
            )

        total_items = result["total"]
        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 0
        return {
            "items": items,
            "total_count": total_count,
            "filtered_count": total_items,
            "movie_count": result["movie_count"],
            "tv_count": result["tv_count"],
            "sync_sessions": result["sessions"],
            "log_file_exists": os.path.exists(DB_FILE),
            "filters": {
                "search": search,
                "status_filter": status_filter,
                "media_type_filter": media_type_filter,
            },
            "pagination": {
                "page": page,
                "limit": limit,
                "total_items": total_items,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        }
    except Exception as e:
        logging.exception(f"Error loading successful items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/requested")
async def get_requested_items(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: str = Query("", description="Search term to filter items by title"),
    status_filter: str = Query("", description="Filter by status"),
    media_type_filter: str = Query("", description="Filter by media type (movie/tv)"),
):
    """Get all requested items from database (historic data) with search/filter and pagination"""
    try:
        if not os.path.exists(DB_FILE):
            return {
                "items": [],
                "total_count": 0,
                "filtered_count": 0,
                "database_exists": False,
                "filters": {
                    "search": search,
                    "status_filter": status_filter,
                    "media_type_filter": media_type_filter,
                },
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total_items": 0,
                    "total_pages": 0,
                    "has_next": False,
                    "has_prev": False,
                },
            }

        offset = (page - 1) * limit
        result = query_requested_items(search, status_filter, media_type_filter, limit, offset)
        items = result["items"]
        total_items = result["total_items"]
        total_count_unfiltered = result["total_count"]
        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 0

        # Get Seerr base URL for generating item links
        try:
            seerr_base_url, _, _, _, _, _ = load_env_config()
            seerr_base_url = seerr_base_url.rstrip("/") if seerr_base_url else None
        except Exception as e:
            logging.debug("Failed to load Seerr base URL: %s", e)
            seerr_base_url = None

        formatted_items = []
        for item in items:
            item_id, title, media_type, imdb_id, overseerr_id, status, last_synced = item

            # Generate Seerr URL if we have the base URL and overseerr_id
            seerr_url = None
            if seerr_base_url and overseerr_id:
                seerr_url = f"{seerr_base_url}/{media_type}/{overseerr_id}"

            formatted_items.append(
                {
                    "id": item_id,
                    "title": title,
                    "media_type": media_type,
                    "imdb_id": imdb_id,
                    "overseerr_id": overseerr_id,
                    "status": status,
                    "timestamp": last_synced,
                    "action": "Requested",  # Since we only show 'requested' status now
                    "overseerr_url": seerr_url,
                }
            )

        return {
            "items": formatted_items,
            "total_count": total_count_unfiltered,
            "filtered_count": total_items,  # Count after filtering
            "database_exists": True,
            "filters": {
                "search": search,
                "status_filter": status_filter,
                "media_type_filter": media_type_filter,
            },
            "pagination": {
                "page": page,
                "limit": limit,
                "total_items": total_items,  # Use filtered count for pagination
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        }

    except Exception as e:
        logging.exception(f"Error getting requested items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/analytics")
async def get_analytics(
    time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$"),
    category: str = Query("all", regex="^(all|sync|fetching|matching|scraping)$"),
):
    """Get comprehensive analytics data"""
    try:
        analytics_data = process_analytics_data(time_range, category)
        return analytics_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating analytics: {e!s}")


@router.get("/api/analytics/overview")
async def get_analytics_overview(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get analytics overview data"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.overview
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating overview: {e!s}")


@router.get("/api/analytics/media-additions")
async def get_media_additions(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get media addition analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.media_additions
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating media additions: {e!s}")


@router.get("/api/analytics/list-fetches")
async def get_list_fetches(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get list fetch analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.list_fetches
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating list fetches: {e!s}")


@router.get("/api/analytics/matching")
async def get_matching_analytics(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get matching accuracy analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.matching
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating matching analytics: {e!s}")


@router.get("/api/analytics/search-failures")
async def get_search_failures(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get search failure analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.search_failures
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating search failures: {e!s}")


@router.get("/api/analytics/scraping-performance")
async def get_scraping_performance(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get scraping performance analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.scraping_performance
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating scraping performance: {e!s}")


@router.get("/api/analytics/source-distribution")
async def get_source_distribution(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get source distribution analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.source_distribution
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating source distribution: {e!s}")


@router.get("/api/analytics/selector-performance")
async def get_selector_performance(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get selector performance analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.selector_performance
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating selector performance: {e!s}")


@router.get("/api/analytics/genre-distribution")
async def get_genre_distribution(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get genre distribution analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.genre_distribution
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating genre distribution: {e!s}")


@router.get("/api/analytics/year-distribution")
async def get_year_distribution(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get year distribution analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.year_distribution
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating year distribution: {e!s}")


@router.get("/api/recent-activity")
async def get_recent_activity(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(5, ge=1, le=20, description="Items per page (max 20)"),
    media_only: bool = Query(False, description="Filter to only show media items with position/total info"),
):
    """Get recent sync activity from structured sync records with pagination"""
    try:
        formatted_items = get_recent_sync_items(limit=500)

        if media_only:
            formatted_items = [
                item for item in formatted_items if item.get("position", 0) > 0 and item.get("total", 0) > 0
            ]

        if not formatted_items:
            return {
                "items": [],
                "total_items": 0,
                "page": page,
                "limit": limit,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
                "log_file_used": "database",
                "error": "No recent activity found",
            }

        total_items = len(formatted_items)
        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 0
        start_index = (page - 1) * limit
        end_index = start_index + limit
        paginated_items = formatted_items[start_index:end_index]

        return {
            "items": paginated_items,
            "total_items": total_items,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
            "log_file_used": "database",
        }

    except Exception as e:
        logging.exception(f"Error loading recent activity: {e}")
        return {
            "items": [],
            "total_items": 0,
            "page": page,
            "limit": limit,
            "total_pages": 0,
            "has_next": False,
            "has_prev": False,
            "error": f"Failed to load recent activity: {e!s}",
        }
