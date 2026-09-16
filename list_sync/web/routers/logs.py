"""routers.logs — moved verbatim from api_server.py (modularize-api-server)."""

import logging
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from list_sync.web.services.logs import get_log_entries, stream_log_updates

router = APIRouter()


@router.get("/api/logs/entries")
async def get_log_entries_endpoint(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    level: str | None = Query(None, regex="^(DEBUG|INFO|WARNING|ERROR)$"),
    category: list[str] | None = Query(None, description="Filter by categories (can specify multiple)"),
    search: str | None = Query(None, description="Search in log messages and media titles"),
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort order by timestamp"),
):
    """Get paginated log entries with filtering"""
    try:
        offset = (page - 1) * limit
        response = get_log_entries(
            limit=limit,
            offset=offset,
            level_filter=level,
            category_filters=category,
            search=search,
            sort_order=sort_order,
        )

        # Add pagination metadata
        total_pages = (response.total_count + limit - 1) // limit if response.total_count > 0 else 0

        return {
            "entries": response.entries,
            "total_count": response.total_count,
            "has_more": response.has_more,
            "last_position": response.last_position,
            "pagination": {
                "page": page,
                "limit": limit,
                "total_items": response.total_count,
                "total_pages": total_pages,
                "has_next": response.has_more,
                "has_prev": page > 1,
            },
            "filters": {
                "level": level,
                "categories": category,
                "search": search,
                "sort_order": sort_order,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/logs/stream")
async def stream_logs(
    last_position: int = Query(0, ge=0),
    level: str | None = Query(None, regex="^(DEBUG|INFO|WARNING|ERROR)$"),
    category: list[str] | None = Query(None, description="Filter by categories (can specify multiple)"),
    search: str | None = Query(None, description="Search in log messages and media titles"),
):
    """Stream live log updates using Server-Sent Events"""
    try:
        return StreamingResponse(
            stream_log_updates(
                last_position=last_position,
                level_filter=level,
                category_filters=category,
                search=search,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/logs/categories")
async def get_log_categories():
    """Get available log categories and their counts"""
    try:
        response = get_log_entries(limit=10000)  # Get a large sample

        category_counts = {}
        level_counts = {}

        for entry in response.entries:
            category_counts[entry.category] = category_counts.get(entry.category, 0) + 1
            level_counts[entry.level] = level_counts.get(entry.level, 0) + 1

        return {
            "categories": [
                {"name": "sync", "label": "Sync Operations", "count": category_counts.get("sync", 0)},
                {"name": "fetching", "label": "List Fetching", "count": category_counts.get("fetching", 0)},
                {"name": "items", "label": "Item Addition", "count": category_counts.get("items", 0)},
                {"name": "scraping", "label": "Web Scraping", "count": category_counts.get("scraping", 0)},
                {"name": "matching", "label": "Title Matching", "count": category_counts.get("matching", 0)},
                {"name": "api", "label": "API Connections", "count": category_counts.get("api", 0)},
                {"name": "webhook", "label": "Webhooks", "count": category_counts.get("webhook", 0)},
                {"name": "pagination", "label": "Pagination", "count": category_counts.get("pagination", 0)},
                {"name": "process", "label": "Process Management", "count": category_counts.get("process", 0)},
                {"name": "metadata", "label": "Metadata", "count": category_counts.get("metadata", 0)},
                {"name": "general", "label": "General", "count": category_counts.get("general", 0)},
            ],
            "levels": [
                {"name": "INFO", "label": "Info", "count": level_counts.get("INFO", 0)},
                {"name": "DEBUG", "label": "Debug", "count": level_counts.get("DEBUG", 0)},
                {"name": "WARNING", "label": "Warning", "count": level_counts.get("WARNING", 0)},
                {"name": "ERROR", "label": "Error", "count": level_counts.get("ERROR", 0)},
            ],
            "total_entries": response.total_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/logs/stats")
async def get_log_stats():
    """Get log file statistics and recent activity summary"""
    try:
        log_path = "data/list_sync.log"

        if not os.path.exists(log_path):
            return {
                "total_entries": 0,
                "level_counts": {},
                "category_counts": {},
                "recent_activity": 0,
                "file_exists": False,
                "error": "Log file not found",
            }

        stat = os.stat(log_path)
        file_size = stat.st_size
        last_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()

        response = get_log_entries(log_path=log_path, limit=10000, offset=0, sort_order="desc")
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)
        level_counts = {}
        category_counts = {}
        recent_activity = 0
        for entry in response.entries:
            level_counts[entry.level] = level_counts.get(entry.level, 0) + 1
            category_counts[entry.category] = category_counts.get(entry.category, 0) + 1
            try:
                entry_time = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00"))
                if entry_time >= one_hour_ago:
                    recent_activity += 1
            except (ValueError, TypeError) as e:
                logging.debug("Skipping unparsable timestamp for recent stats: %s", e)

        return {
            "total_entries": response.total_count,
            "level_counts": level_counts,
            "category_counts": category_counts,
            "recent_activity": recent_activity,
            "file_exists": True,
            "file_size": file_size,
            "last_modified": last_modified,
        }

    except Exception as e:
        logging.exception(f"Error getting log stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/logs/live")
async def get_live_logs(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(200, ge=1, le=500, description="Lines per page (max 500)"),
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort order: asc or desc"),
):
    """Get live log content from the core log file with pagination."""
    try:
        # Try different log locations
        log_paths = [
            "/var/log/supervisor/listsync-core.log",
            "logs/listsync-core.log",
            "/usr/src/app/logs/listsync-core.log",
            "data/list_sync.log",
        ]

        log_content = ""
        log_file_used = None
        for log_path in log_paths:
            if os.path.exists(log_path):
                try:
                    with open(log_path, encoding="utf-8", errors="ignore") as f:
                        log_content = f.read()
                    log_file_used = log_path
                    break
                except Exception as e:
                    logging.exception(f"Error reading log file {log_path}: {e}")
                    continue

        if not log_content:
            return {
                "success": False,
                "error": "No log file found",
                "lines": [],
                "total_lines": 0,
                "page": page,
                "limit": limit,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            }

        # Split into lines
        all_lines = log_content.strip().split("\n")
        total_lines = len(all_lines)

        # Calculate pagination
        total_pages = (total_lines + limit - 1) // limit  # Ceiling division
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit

        # Get the requested page of lines
        if sort_order == "desc":
            # Reverse order (newest first)
            lines = all_lines[::-1][start_idx:end_idx]
        else:
            # Normal order (oldest first)
            lines = all_lines[start_idx:end_idx]

        return {
            "success": True,
            "lines": lines,
            "total_lines": total_lines,
            "file_size": len(log_content),
            "file_path": log_file_used,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
            "sort_order": sort_order,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "lines": [],
            "total_lines": 0,
            "page": page,
            "limit": limit,
            "total_pages": 0,
            "has_next": False,
            "has_prev": False,
        }


@router.get("/api/logs/backend")
async def get_backend_logs(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(200, ge=1, le=500, description="Lines per page (max 500)"),
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort order: asc or desc"),
):
    """Get backend log content from the data/list_sync.log file with pagination."""
    try:
        # Backend log file path
        log_path = "data/list_sync.log"

        if not os.path.exists(log_path):
            return {
                "success": False,
                "error": "Backend log file not found",
                "lines": [],
                "total_lines": 0,
                "page": page,
                "limit": limit,
                "total_pages": 0,
                "has_next": False,
                "has_prev": False,
            }

        # Read the log file
        with open(log_path, encoding="utf-8", errors="ignore") as f:
            log_content = f.read()

        # Split into lines
        all_lines = log_content.strip().split("\n")
        total_lines = len(all_lines)

        # Calculate pagination
        total_pages = (total_lines + limit - 1) // limit  # Ceiling division
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit

        # Get the requested page of lines
        if sort_order == "desc":
            # Reverse order (newest first)
            lines = all_lines[::-1][start_idx:end_idx]
        else:
            # Normal order (oldest first)
            lines = all_lines[start_idx:end_idx]

        return {
            "success": True,
            "lines": lines,
            "total_lines": total_lines,
            "file_size": len(log_content),
            "file_path": log_path,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
            "sort_order": sort_order,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "lines": [],
            "total_lines": 0,
            "page": page,
            "limit": limit,
            "total_pages": 0,
            "has_next": False,
            "has_prev": False,
        }


@router.get("/api/logs/rotation-info")
async def get_log_rotation_info():
    """Get information about log rotation status."""
    try:
        from list_sync.utils.log_rotation import get_log_rotator

        rotator = get_log_rotator()
        info = rotator.get_log_file_info()

        return {
            "success": True,
            "rotation_info": info,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "rotation_info": None,
        }


@router.get("/api/logs/rotate")
async def rotate_logs():
    """Manually trigger log rotation."""
    try:
        from list_sync.utils.log_rotation import check_and_rotate_logs

        success = check_and_rotate_logs()

        return {
            "success": success,
            "message": "Log rotation completed" if success else "No rotation needed",
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Log rotation failed",
        }
