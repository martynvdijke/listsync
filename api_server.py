#!/usr/bin/env python3
"""
ListSync Web UI API Server
FastAPI backend that integrates with the existing ListSync codebase
"""

import asyncio
import json
import logging
import multiprocessing
import os
import re
import signal
import time
from collections import Counter
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

import psutil
import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from list_sync.config import load_env_config

# Import existing ListSync modules
from list_sync.database import (
    DB_FILE,
    DatabaseError,
    check_database_connection,
    configure_sync_interval,
    count_item_lists,
    delete_list,
    fetch_cached_images,
    get_all_synced_items,
    get_analytics_payload,
    get_duplicate_count,
    get_item_lists_for_items,
    get_item_tmdb_and_posters,
    get_list_items,
    get_poster_urls,
    get_raw_lists,
    get_recent_sync_items,
    get_sync_info,
    get_sync_session_by_id,
    get_sync_sessions,
    get_synced_items_quality_rows,
    init_database,
    load_list_ids,
    load_sync_interval,
    normalize_list_id,
    query_requested_items,
    query_sync_items,
    save_list_id,
    update_list_user_id,
)
from list_sync.database import (
    get_sync_history_stats as query_sync_history_stats,
)

# Removed in-memory sync tracker - now using database-based tracking
# Import new timezone utilities
from list_sync.utils.timezone_utils import (
    get_current_timezone_info,
    list_supported_abbreviations,
    normalize_timezone_input,
)

# Global variable to track server start time
SERVER_START_TIME = None

# Initialize FastAPI app
app = FastAPI(
    title="ListSync Web UI API",
    description="REST API for ListSync media synchronization dashboard",
    version="1.0.0",
)


@app.on_event("startup")
async def startup_event():
    """Set the server start time when the FastAPI app starts"""
    global SERVER_START_TIME

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # Ensure database schema is up to date (creates new tables/columns if missing)
    try:
        init_database()
        logging.info("Database initialized / schema verified successfully at startup")
    except Exception as e:
        logging.exception(f"Failed to initialize database on startup: {e}")
        raise

    SERVER_START_TIME = time.time()
    logging.info(f"🚀 API Server started at: {datetime.fromtimestamp(SERVER_START_TIME).isoformat()}")
    logging.info("📊 Dashboard available at: http://localhost:3222")


# Add CORS middleware


def get_allowed_origins():
    """Get allowed origins from environment or use defaults"""
    env_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")

    if env_origins:
        # If environment variable is set, use it (comma-separated)
        return [origin.strip() for origin in env_origins.split(",")]

    # Default origins for development
    default_origins = [
        "http://localhost:3222",
        "http://localhost:4222",
        "http://0.0.0.0:3222",
        "http://0.0.0.0:4222",
        "http://127.0.0.1:3222",
        "http://127.0.0.1:4222",
    ]

    # Add common local network patterns
    for i in range(1, 255):
        default_origins.extend(
            [
                f"http://192.168.1.{i}:3222",
                f"http://192.168.1.{i}:4222",
            ]
        )

    return default_origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Pydantic models for request/response
class SyncIntervalUpdate(BaseModel):
    interval_hours: float


class ListAdd(BaseModel):
    list_type: str
    list_id: str
    user_id: str = "1"


class ListUserUpdate(BaseModel):
    user_id: str


class ProcessInfo(BaseModel):
    pid: int
    status: str
    created: str
    cmdline: list[str]
    memory_percent: float | None = None
    cpu_percent: float | None = None


class LogInfo(BaseModel):
    last_sync_start: str | None = None
    last_sync_complete: str | None = None
    sync_interval_hours: float | None = None
    next_sync_time: str | None = None
    sync_status: str = "unknown"
    recent_errors: list[str] = []
    log_file_size: int = 0
    log_last_modified: str = ""


class SystemStatus(BaseModel):
    database: dict[str, Any]
    process: dict[str, Any]
    sync: dict[str, Any]
    logs: LogInfo
    overall_health: str


class LogEntry(BaseModel):
    id: str
    timestamp: str
    level: str
    category: str
    message: str
    raw_line: str
    media_info: dict[str, Any] | None = None


class LogStreamResponse(BaseModel):
    entries: list[LogEntry]
    total_count: int
    has_more: bool
    last_position: int


# Utility functions
def find_listsync_processes() -> list[ProcessInfo]:
    """Find ListSync processes dynamically"""
    processes = []
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                if proc.info["cmdline"]:
                    cmdline_str = " ".join(proc.info["cmdline"]).lower()
                    if ("list_sync" in cmdline_str or "listsync" in cmdline_str) and "python" in cmdline_str:
                        # Filter out API server itself
                        if "api_server.py" not in cmdline_str:
                            processes.append(
                                ProcessInfo(
                                    pid=proc.info["pid"],
                                    cmdline=proc.info["cmdline"],
                                    created=datetime.fromtimestamp(proc.info["create_time"]).isoformat(),
                                    status=proc.status(),
                                )
                            )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                logging.debug("Skipping vanished/inaccessible process")  # best-effort: process gone, safe to skip
    except Exception as e:
        logging.exception(f"Error finding processes: {e}")

    return processes


def get_deduplicated_items():
    """Get unique items with deduplication logic"""
    if not os.path.exists(DB_FILE):
        return []

    try:
        items = get_all_synced_items()

        unique_items = {}

        # Define status priority (higher number = higher priority)
        status_priority = {
            "requested": 100,
            "already_requested": 90,
            "already_available": 80,
            "available": 70,
            "not_found": 20,
            "error": 10,
            "skipped": 5,  # Lowest priority
        }

        for item in items:
            (
                item_id,
                title,
                media_type,
                year,
                imdb_id,
                overseerr_id,
                status,
                last_synced,
                source_list_type,
                source_list_id,
            ) = item

            # Create unique key based on title and media type
            key = f"{title}_{media_type}".lower().strip()

            if key not in unique_items:
                unique_items[key] = item
            else:
                existing_item = unique_items[key]
                existing_status = existing_item[6]  # Status is now at index 6
                existing_last_synced = existing_item[7]  # Last synced is now at index 7

                # Prefer item with higher status priority
                current_priority = status_priority.get(status, 0)
                existing_priority = status_priority.get(existing_status, 0)

                should_replace = False

                if current_priority > existing_priority:
                    should_replace = True
                elif current_priority == existing_priority:
                    # Same priority, prefer item with overseerr_id
                    if overseerr_id and not existing_item[5]:  # overseerr_id is now at index 5
                        should_replace = True
                    elif (overseerr_id and existing_item[5]) or (not overseerr_id and not existing_item[5]):
                        # Both have or both don't have overseerr_id, prefer more recent
                        if last_synced > existing_last_synced:
                            should_replace = True

                if should_replace:
                    unique_items[key] = item

        result = list(unique_items.values())
        logging.debug(f"DEBUG - Deduplication: {len(items)} raw items -> {len(result)} unique items")

        # Debug: Show status breakdown of unique items
        status_counts = {}
        for item in result:
            status = item[6]  # Status is now at index 6
            status_counts[status] = status_counts.get(status, 0) + 1
        logging.debug(f"DEBUG - Unique item statuses: {status_counts}")

        return result

    except Exception as e:
        logging.exception(f"Error getting deduplicated items: {e}")
        return []


def analyze_data_quality():
    """Analyze data quality with deduplication stats"""
    if not os.path.exists(DB_FILE):
        return None

    try:
        items = get_synced_items_quality_rows()

        # Analyze duplicates
        title_counts = Counter()
        status_counts = Counter()
        unique_items = {}

        for item in items:
            title, media_type, year, imdb_id, overseerr_id, status, last_synced = item

            # Count titles for duplicate analysis
            title_counts[title] += 1
            status_counts[status] += 1

            # Create unique key (prefer items with overseerr_id and more recent sync)
            key = f"{title}_{media_type}".lower()
            if (
                key not in unique_items
                or (overseerr_id and not unique_items[key][4])
                or last_synced > unique_items[key][6]
            ):
                unique_items[key] = item

        # Categorize statuses
        success_statuses = ["already_available", "already_requested", "available", "requested"]
        failure_statuses = ["not_found", "error"]

        unique_success = sum(1 for item in unique_items.values() if item[5] in success_statuses)
        unique_failure = sum(1 for item in unique_items.values() if item[5] in failure_statuses)

        analysis = {
            "total_raw_items": len(items),
            "total_unique_items": len(unique_items),
            "duplicates_found": len(items) - len(unique_items),
            "status_breakdown": dict(status_counts),
            "unique_success_count": unique_success,
            "unique_failure_count": unique_failure,
            "success_rate": (unique_success / len(unique_items) * 100) if unique_items else 0,
            "most_duplicated": title_counts.most_common(5),
        }

        return analysis

    except Exception as e:
        logging.exception(f"Error analyzing data quality: {e}")
        return None


def get_line_number(entry):
    """Extract line number from log entry ID for secondary sorting"""
    try:
        # ID format is "log-{line_number}"
        return int(entry.id.split("-")[1])
    except (IndexError, ValueError):
        return 0


# The live-tail reader's line format and the keyword buckets the log viewer
# groups by. Reporting does not use either.
_LOG_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - (DEBUG|INFO|ERROR|WARNING) - (.+)$")
_LOG_CATEGORY_KEYWORDS = (
    ("sync", ("sync", "session")),
    ("fetching", ("fetch", "list")),
    ("items", ("request", "skipped", "available", "not found", "added")),
    ("matching", ("match", "resolv")),
    ("api", ("seerr", "trakt", "tmdb", "api request", "http")),
    ("webhook", ("webhook", "discord", "gotify")),
    ("process", ("process", "pid", "signal", "cancel")),
)


def get_log_entries(
    log_path: str = "data/list_sync.log",
    limit: int = 50,
    offset: int = 0,
    level_filter: str | None = None,
    category_filters: list[str] | None = None,
    search: str | None = None,
    sort_order: str = "desc",
) -> LogStreamResponse:
    """Read log lines for the live-tail / log viewer.

    This is the single remaining log-line reader: reporting and analytics read
    the database, and this exists only so the log can still be streamed and
    displayed. It does a light keyword categorisation for the viewer filters.
    """
    if not os.path.exists(log_path):
        return LogStreamResponse(entries=[], total_count=0, has_more=False, last_position=0)

    try:
        with open(log_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        all_entries = []
        for i, line in enumerate(lines):
            match = _LOG_LINE_RE.match(line.strip())
            if not match:
                continue
            timestamp_str, level, message = match.groups()
            try:
                iso_timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").isoformat()
            except (ValueError, TypeError):
                iso_timestamp = timestamp_str

            lowered = message.lower()
            category = "general"
            for name, keywords in _LOG_CATEGORY_KEYWORDS:
                if any(keyword in lowered for keyword in keywords):
                    category = name
                    break

            all_entries.append(
                LogEntry(
                    id=f"log-{i + 1}",
                    timestamp=iso_timestamp,
                    level=level,
                    category=category,
                    message=message,
                    raw_line=line.strip(),
                    media_info=None,
                )
            )

        # Apply filters
        filtered_entries = all_entries

        if level_filter:
            filtered_entries = [e for e in filtered_entries if e.level == level_filter]

        if category_filters and len(category_filters) > 0:
            filtered_entries = [e for e in filtered_entries if e.category in category_filters]

        if search:
            search_lower = search.lower()
            filtered_entries = [e for e in filtered_entries if search_lower in e.message.lower()]

        # Sort by timestamp and line number to maintain original file order for same timestamps
        if sort_order == "desc":
            filtered_entries.sort(key=lambda x: (x.timestamp, get_line_number(x)), reverse=True)
        else:
            filtered_entries.sort(key=lambda x: (x.timestamp, get_line_number(x)), reverse=False)

        # Apply pagination
        total_count = len(filtered_entries)
        start = offset
        end = offset + limit
        paginated_entries = filtered_entries[start:end]

        has_more = end < total_count
        last_position = len(lines)  # Position in original file

        return LogStreamResponse(
            entries=paginated_entries,
            total_count=total_count,
            has_more=has_more,
            last_position=last_position,
        )

    except Exception as e:
        logging.exception(f"Error reading log file: {e}")
        return LogStreamResponse(entries=[], total_count=0, has_more=False, last_position=0)


async def stream_log_updates(
    log_path: str = "data/list_sync.log",
    last_position: int = 0,
    level_filter: str | None = None,
    category_filters: list[str] | None = None,
    search: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream new log entries as they are added to the file.

    Reads through the one retained line reader rather than parsing the log
    itself. The file is re-read each tick; rotated logs are bounded, so this
    stays cheap enough for a tail.
    """

    if not os.path.exists(log_path):
        yield f"data: {json.dumps({'error': 'Log file not found'})}\n\n"
        return

    current_position = last_position

    while True:
        try:
            response = get_log_entries(log_path, limit=100000, offset=0, sort_order="asc")

            new_entries = []
            for entry in response.entries:
                if get_line_number(entry) <= current_position:
                    continue
                if level_filter and entry.level != level_filter:
                    continue
                if category_filters and len(category_filters) > 0 and entry.category not in category_filters:
                    continue
                if search and search.lower() not in entry.message.lower():
                    continue
                new_entries.append(entry)

            for entry in new_entries:
                yield f"data: {json.dumps(entry.dict())}\n\n"

            if response.last_position:
                current_position = response.last_position

            # Send heartbeat
            yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        await asyncio.sleep(1)  # Check for updates every second


# Status buckets the reporting surface groups by.
REPORTING_SUCCESS_STATUSES = ("requested", "already_available", "already_requested", "skipped", "available", "synced")
REPORTING_FAILURE_STATUSES = ("not_found", "error", "request_failed")


def build_log_info() -> LogInfo:
    """Build the sync/log summary the system endpoints return.

    Timing and errors come from the database; only file size/mtime are read
    from the log file, which is no longer parsed.
    """
    try:
        info = get_sync_info()
    except Exception as e:
        logging.exception(f"Could not build sync info from database: {e}")
        info = {}

    log_info = LogInfo(
        last_sync_start=info.get("last_sync_start"),
        last_sync_complete=info.get("last_sync_complete"),
        sync_interval_hours=info.get("sync_interval_hours"),
        next_sync_time=info.get("next_sync_time"),
        sync_status=info.get("sync_status", "unknown"),
        recent_errors=info.get("recent_errors", []),
    )

    log_path = "data/list_sync.log"
    try:
        if os.path.exists(log_path):
            stat = os.stat(log_path)
            log_info.log_file_size = stat.st_size
            log_info.log_last_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except OSError as e:
        logging.debug("Could not stat log file: %s", e)

    return log_info


@app.get("/api/system/status")
async def get_system_status():
    """Comprehensive system health check"""

    # Database status
    database_status = {
        "connected": False,
        "file_exists": os.path.exists(DB_FILE),
        "file_size": 0,
        "last_modified": "",
        "error": None,
    }

    if database_status["file_exists"]:
        try:
            stat = os.stat(DB_FILE)
            database_status["file_size"] = stat.st_size
            database_status["last_modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()

            # Test connection
            check_database_connection()
            database_status["connected"] = True
        except Exception as e:
            database_status["error"] = str(e)

    # Process status
    processes = find_listsync_processes()
    process_status = {
        "running": len(processes) > 0,
        "processes": [p.dict() for p in processes],
        "error": None,
    }

    # Log analysis
    logs = build_log_info()

    # Sync status
    sync_status = {
        "status": logs.sync_status,
        "last_sync": logs.last_sync_complete,
        "next_sync": logs.next_sync_time,
        "interval_hours": logs.sync_interval_hours,
        "error": None,
    }

    # Overall health
    overall_health = "healthy"
    if not database_status["connected"] or not process_status["running"]:
        overall_health = "error"
    elif logs.sync_status == "overdue" or logs.recent_errors:
        overall_health = "warning"

    return SystemStatus(
        database=database_status,
        process=process_status,
        sync=sync_status,
        logs=logs,
        overall_health=overall_health,
    )


@app.get("/api/system/processes")
async def get_processes():
    """Get ListSync process information"""
    return find_listsync_processes()


@app.get("/api/system/logs")
async def get_log_info():
    """Get log file analysis"""
    return build_log_info()


@app.get("/api/system/database/test")
async def test_database():
    """Test database connectivity"""
    try:
        check_database_connection()
        return {"connected": True}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@app.get("/api/system/health")
async def get_health_check():
    """Simple health check endpoint"""
    try:
        # Check database
        db_result = await test_database()
        db_connected = db_result["connected"]

        # Check if ListSync process is running
        processes = find_listsync_processes()
        process_running = len(processes) > 0

        # Parse logs for sync status
        log_info = build_log_info()

        return {
            "database": db_connected,
            "process": process_running,
            "sync_status": log_info.sync_status,
            "last_sync": log_info.last_sync_complete,
            "next_sync": log_info.next_sync_time,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Setup Wizard Endpoints - First-Run Configuration
# ============================================================================


@app.get("/api/setup/status")
async def get_setup_status():
    """
    Check setup status and determine if wizard should be shown.

    Returns:
        - is_complete: Whether setup wizard has been completed
        - has_env: Whether .env file exists with basic config
        - needs_migration: Whether .env should be auto-migrated to database
        - settings_count: Number of settings in database
    """
    try:
        from list_sync.config import ConfigManager

        config = ConfigManager()

        # Check if setup is marked complete in database
        is_complete = config.is_setup_complete()

        # Check if .env exists with configuration
        has_env = config.has_env_config()

        # Check how many settings are in database
        settings_count = config.database.count_settings()

        # Needs migration if: has .env, not complete, and no/few settings in DB
        needs_migration = has_env and not is_complete and settings_count < 5

        return {
            "is_complete": is_complete,
            "has_env": has_env,
            "needs_migration": needs_migration,
            "settings_count": settings_count,
        }
    except Exception as e:
        logging.exception(f"Error checking setup status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/setup/migrate-from-env")
async def migrate_from_env():
    """
    Migrate settings from .env file to database.
    Auto-runs on startup if .env exists and database is empty.
    """
    try:
        from list_sync.config import ConfigManager

        config = ConfigManager()

        # Perform migration
        migrated_count = config.migrate_env_to_database()

        # Mark setup as complete after successful migration
        if migrated_count > 0:
            config.mark_setup_complete()

        logging.info(f"Environment migration complete: {migrated_count} settings migrated")

        return {
            "success": True,
            "settings_migrated": migrated_count,
            "message": f"Successfully migrated {migrated_count} settings from .env to database",
        }
    except Exception as e:
        logging.exception(f"Migration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/setup/test/overseerr")
async def test_overseerr_connection(data: dict):
    """
    Test Seerr connection with provided URL and API key.

    Expected data:
        - seerr_url: str
        - seerr_api_key: str
        - seerr_user_id: str (optional, defaults to "1")
    """
    try:
        seerr_url = data.get("overseerr_url", "").strip().rstrip("/")
        seerr_api_key = data.get("overseerr_api_key", "").strip()
        seerr_user_id = data.get("overseerr_user_id", "1").strip()

        # Basic validation
        if not seerr_url:
            return {
                "valid": False,
                "error": "Seerr URL is required",
            }

        if not seerr_api_key:
            return {
                "valid": False,
                "error": "Seerr API Key is required",
            }

        if not seerr_url.startswith(("http://", "https://")):
            return {
                "valid": False,
                "error": "URL must start with http:// or https://",
            }

        # The caller supplies this URL and the server then requests it. A
        # self-hosted Seerr is normally on a private address, so those stay
        # permitted, but cloud metadata endpoints and non-HTTP schemes never are.
        from list_sync.utils.url_safety import validate_outbound_url

        url_ok, url_reason = validate_outbound_url(seerr_url, allow_private=True)
        if not url_ok:
            logging.warning(f"Blocked Seerr connection test: {url_reason}")
            return {
                "valid": False,
                "error": url_reason,
            }

        # Test connection by fetching user list and finding the default user
        try:
            headers = {"X-Api-Key": seerr_api_key}

            logging.info(f"Testing Seerr API key validation with endpoint: {seerr_url}/api/v1/user")

            # Fetch all users to validate API key and get user info
            user_response = requests.get(f"{seerr_url}/api/v1/user", headers=headers, timeout=10, params={"take": 100})

            logging.info(f"Seerr API key test response status: {user_response.status_code}")

            # If we get 401, the API key is invalid
            if user_response.status_code == 401:
                return {
                    "valid": False,
                    "error": "Invalid API key. Please check your Seerr API key.",
                }

            # If we get 403, the API key doesn't have permission
            if user_response.status_code == 403:
                return {
                    "valid": False,
                    "error": "API key does not have required permissions. Please check your API key.",
                }

            # Raise for other HTTP errors
            user_response.raise_for_status()

            # Parse response to get user info
            user_data = user_response.json()
            users = user_data.get("results", [])

            # Save all users to database for future use
            if users:
                try:
                    from list_sync.database import save_seerr_users

                    formatted_users = []
                    for user in users:
                        formatted_users.append(
                            {
                                "id": str(user.get("id")),
                                "display_name": user.get("displayName", user.get("username", "Unknown")),
                                "email": user.get("email", ""),
                                "avatar": user.get("avatar", ""),
                            }
                        )
                    save_seerr_users(formatted_users)
                    logging.info(f"Pre-populated {len(formatted_users)} Seerr users to database during setup")
                except Exception as e:
                    # Don't fail the test if user save fails
                    logging.warning(f"Failed to save users to database during setup: {e}")

            # Find the specified user (default is user ID 1)
            default_user = None
            for user in users:
                if str(user.get("id")) == str(seerr_user_id):
                    default_user = user
                    break

            if not default_user and users:
                # If specified user not found, return error
                logging.warning(f"User ID {seerr_user_id} not found in Seerr")
                return {
                    "valid": False,
                    "error": f"User ID {seerr_user_id} not found. Please check the User ID.",
                }
            if not users:
                # No users found at all
                logging.warning("No users found in Seerr")
                return {
                    "valid": False,
                    "error": "No users found in Seerr. Please check your instance.",
                }

            # Also test /api/v1/status to get version info
            try:
                status_response = requests.get(f"{seerr_url}/api/v1/status", headers=headers, timeout=5)
                status_data = status_response.json() if status_response.status_code == 200 else {}
            except (requests.RequestException, ValueError) as e:
                logging.debug("Failed to fetch Seerr status: %s", e)
                status_data = {}

            logging.info(
                f"Seerr connection test successful - API key validated, found user: {default_user.get('displayName') or default_user.get('username')}"
            )

            # Prepare user info for response
            user_info = {
                "id": default_user.get("id"),
                "email": default_user.get("email", ""),
                "username": default_user.get("username", ""),
                "displayName": default_user.get("displayName", ""),
                "plexUsername": default_user.get("plexUsername", ""),
                "avatar": default_user.get("avatar", ""),
                "requestCount": default_user.get("requestCount", 0),
            }

            return {
                "valid": True,
                "message": "Seerr connection successful",
                "version": status_data.get("version", "Unknown"),
                "updateAvailable": status_data.get("updateAvailable", False),
                "user": user_info,
            }
        except requests.exceptions.Timeout:
            return {
                "valid": False,
                "error": "Connection timeout. Check your Seerr URL.",
            }
        except requests.exceptions.ConnectionError:
            return {
                "valid": False,
                "error": "Could not connect to Seerr. Check your URL and network.",
            }
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                return {
                    "valid": False,
                    "error": "Invalid API key. Please check your Seerr API key.",
                }
            return {
                "valid": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:100]}",
            }
        except requests.exceptions.RequestException as e:
            return {
                "valid": False,
                "error": f"Connection test failed: {e!s}",
            }
    except Exception as e:
        logging.exception(f"Error testing Seerr connection: {e}")
        return {
            "valid": False,
            "error": f"Unexpected error: {e!s}",
        }


@app.get("/api/overseerr/users")
async def get_seerr_users_endpoint():
    """Get all Seerr users from database"""
    try:
        from list_sync.database import get_seerr_users

        users = get_seerr_users()

        return {
            "success": True,
            "users": users,
            "count": len(users),
        }
    except Exception as e:
        logging.exception(f"Error fetching Seerr users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/overseerr/users/sync")
async def sync_seerr_users_endpoint():
    """Sync Seerr users from Seerr API to database"""
    try:
        from urllib.parse import quote

        from list_sync.config import ConfigManager
        from list_sync.database import save_seerr_users

        # Get Seerr credentials from config
        config = ConfigManager()
        seerr_url = config.get_setting("overseerr_url")
        seerr_api_key = config.get_setting("overseerr_api_key")

        if not seerr_url or not seerr_api_key:
            raise HTTPException(
                status_code=400,
                detail="Seerr URL and API key must be configured",
            )

        # Fetch users from Seerr API
        headers = {"X-Api-Key": seerr_api_key}

        # Get all users (paginated)
        all_users = []
        page = 1
        take = 100  # Max per page

        while True:
            response = requests.get(
                f"{seerr_url.rstrip('/')}/api/v1/user",
                headers=headers,
                params={"take": take, "skip": (page - 1) * take},
                timeout=10,
            )

            if response.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid Seerr API key")

            if response.status_code == 403:
                raise HTTPException(status_code=403, detail="Seerr API key lacks permissions")

            response.raise_for_status()
            data = response.json()

            users = data.get("results", [])
            if not users:
                break

            all_users.extend(users)

            # Check if there are more pages
            page_info = data.get("pageInfo", {})
            if page_info.get("pages", 1) <= page:
                break

            page += 1

        # Transform users to our format
        formatted_users = []
        for user in all_users:
            avatar = user.get("avatar", "")
            full_avatar = avatar
            if avatar and seerr_url and avatar.startswith("/"):
                full_avatar = f"{seerr_url.rstrip('/')}{avatar}"

            # Use proxy endpoint to enable caching on first use
            proxied_avatar = None
            if full_avatar and full_avatar.startswith(("http://", "https://")):
                proxied_avatar = f"/api/images/proxy?url={quote(full_avatar, safe='')}"

            formatted_users.append(
                {
                    "id": str(user.get("id")),
                    "display_name": user.get("displayName", user.get("username", "Unknown")),
                    "email": user.get("email", ""),
                    "avatar": proxied_avatar or full_avatar or "",
                }
            )

        # Save to database
        save_seerr_users(formatted_users)

        logging.info(f"Synced {len(formatted_users)} Seerr users to database")

        return {
            "success": True,
            "message": f"Successfully synced {len(formatted_users)} users",
            "users": formatted_users,
            "count": len(formatted_users),
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error syncing Seerr users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/setup/test/trakt")
async def test_trakt_client_id(data: dict):
    """
    Test Trakt Client ID validity.

    Expected data:
        - trakt_client_id: str
    """
    try:
        trakt_client_id = data.get("trakt_client_id", "").strip()

        # Basic validation
        if not trakt_client_id:
            return {
                "valid": False,
                "error": "Trakt Client ID is required",
            }

        # Validate Trakt Client ID format first
        # Trakt Client IDs are typically hex strings (alphanumeric lowercase)
        # They can vary in length but should be at least 16 characters
        import re

        # Check length (Trakt Client IDs should be reasonable length)
        if len(trakt_client_id) < 16:
            return {
                "valid": False,
                "error": "Invalid Trakt Client ID format. Client ID is too short (minimum 16 characters).",
            }

        # Check if it contains only valid hex characters (0-9, a-f)
        # Trakt Client IDs are typically lowercase hex strings
        if not re.match(r"^[a-f0-9]+$", trakt_client_id.lower()):
            return {
                "valid": False,
                "error": "Invalid Trakt Client ID format. Client ID should contain only hexadecimal characters (0-9, a-f).",
            }

        # Test Trakt API with an endpoint that validates the Client ID
        # Use a public endpoint that will reject invalid Client IDs
        try:
            headers = {
                "Content-Type": "application/json",
                "trakt-api-version": "2",
                "trakt-api-key": trakt_client_id,
            }

            # Try to access a simple public endpoint
            # This endpoint should work with a valid Client ID even without OAuth
            # An invalid Client ID should return 401
            response = requests.get(
                "https://api.trakt.tv/calendars/all/movies/2024-01-01/1",
                headers=headers,
                timeout=10,
            )

            # Check response status
            # Trakt API returns 401 for unauthorized/invalid Client IDs
            if response.status_code == 401:
                # 401 means unauthorized - this indicates an invalid Client ID
                try:
                    error_data = response.json()
                    error_message = error_data.get("error", "").lower()
                    # Check for specific error messages
                    if "invalid" in error_message or "unauthorized" in error_message or "forbidden" in error_message:
                        return {
                            "valid": False,
                            "error": "Invalid Trakt Client ID. Please verify your Client ID is correct.",
                        }
                except (ValueError, TypeError, AttributeError) as e:
                    logging.debug("Failed to parse Trakt 401 error response: %s", e)
                # Default to invalid if we get 401
                return {
                    "valid": False,
                    "error": "Invalid Trakt Client ID. The API returned unauthorized. Please check your Client ID.",
                }

            # If we get 400, it's likely an invalid request format or Client ID
            if response.status_code == 400:
                return {
                    "valid": False,
                    "error": "Invalid Trakt Client ID format. Please check your Client ID.",
                }

            # Check response headers for Client ID validation
            # Trakt API might include validation info in headers
            api_key_header = response.headers.get("X-API-Key-Status", "").lower()
            if "invalid" in api_key_header or "rejected" in api_key_header:
                return {
                    "valid": False,
                    "error": "Invalid Trakt Client ID. The API rejected the Client ID.",
                }

            # 200 or 404 means the request was accepted (Client ID appears valid)
            # 404 is acceptable for calendar endpoints if the date doesn't exist
            if response.status_code in [200, 404]:
                logging.info("Trakt Client ID validation successful")
                return {
                    "valid": True,
                    "message": "Trakt Client ID is valid",
                }

            # For any other status, be more cautious
            logging.warning(f"Trakt Client ID validation returned unexpected status: {response.status_code}")
            # If we get an unexpected status, assume invalid for safety
            return {
                "valid": False,
                "error": f"Unexpected response from Trakt API (status {response.status_code}). Please check your Client ID.",
            }
        except requests.exceptions.Timeout:
            return {
                "valid": False,
                "error": "Connection timeout. Check your network connection.",
            }
        except requests.exceptions.ConnectionError:
            return {
                "valid": False,
                "error": "Could not connect to Trakt API. Check your network.",
            }
        except requests.exceptions.RequestException as e:
            return {
                "valid": False,
                "error": f"Validation failed: {e!s}",
            }
    except Exception as e:
        logging.exception(f"Error testing Trakt Client ID: {e}")
        return {
            "valid": False,
            "error": f"Unexpected error: {e!s}",
        }


@app.post("/api/setup/step1/essential")
async def save_step1_essential(data: dict):
    """
    Save and validate Step 1: Essential configuration (Seerr).

    Expected data:
        - seerr_url: str
        - seerr_api_key: str
        - seerr_user_id: str
        - overseerr_4k: bool
    """
    try:
        from list_sync.config import ConfigManager

        config = ConfigManager()
        errors = {}

        # Validate Seerr URL
        seerr_url = data.get("overseerr_url", "").strip().rstrip("/")
        if not seerr_url:
            errors["overseerr_url"] = "Seerr URL is required"
        elif not seerr_url.startswith(("http://", "https://")):
            errors["overseerr_url"] = "URL must start with http:// or https://"
        else:
            # This URL gets fetched by the server below, so refuse the targets
            # that are never a real Seerr. Private addresses stay allowed:
            # a self-hosted instance is normally on one.
            from list_sync.utils.url_safety import validate_outbound_url

            _ok, _reason = validate_outbound_url(seerr_url, allow_private=True)
            if not _ok:
                errors["overseerr_url"] = _reason

        # Validate Seerr API Key
        seerr_api_key = data.get("overseerr_api_key", "").strip()
        if not seerr_api_key:
            errors["overseerr_api_key"] = "Seerr API Key is required"

        # Test Seerr connection if no errors so far
        # Use /api/v1/user endpoint which REQUIRES authentication to properly validate API key
        if not errors and seerr_url and seerr_api_key:
            try:
                headers = {"X-Api-Key": seerr_api_key}
                seerr_user_id = data.get("overseerr_user_id", "1").strip()

                # Test with /api/v1/user to validate API key and get user info
                response = requests.get(f"{seerr_url}/api/v1/user", headers=headers, timeout=10, params={"take": 100})

                # If we get 401, the API key is invalid
                if response.status_code == 401:
                    errors["overseerr_api_key"] = "Invalid API key. Please check your Seerr API key."
                    logging.error("Seerr API key validation failed: 401 Unauthorized")
                # If we get 403, the API key doesn't have permission
                elif response.status_code == 403:
                    errors["overseerr_api_key"] = (
                        "API key does not have required permissions. Please check your API key."
                    )
                    logging.error("Seerr API key validation failed: 403 Forbidden")
                else:
                    # Raise for other HTTP errors
                    response.raise_for_status()

                    # Verify the specified user exists
                    user_data = response.json()
                    users = user_data.get("results", [])
                    user_found = any(str(user.get("id")) == str(seerr_user_id) for user in users)

                    if not user_found and users:
                        errors["overseerr_user_id"] = f"User ID {seerr_user_id} not found in Seerr."
                        logging.error(f"Seerr user validation failed: User ID {seerr_user_id} not found")
                    else:
                        logging.info("Seerr connection test successful - API key validated")
            except requests.exceptions.Timeout:
                errors["overseerr_url"] = "Connection timeout. Check your Seerr URL."
            except requests.exceptions.ConnectionError:
                errors["overseerr_url"] = "Could not connect to Seerr. Check your URL and network."
            except requests.exceptions.HTTPError as e:
                # Handle other HTTP errors
                if e.response.status_code == 401:
                    errors["overseerr_api_key"] = "Invalid API key. Please check your Seerr API key."
                elif e.response.status_code == 403:
                    errors["overseerr_api_key"] = (
                        "API key does not have required permissions. Please check your API key."
                    )
                else:
                    errors["overseerr_url"] = f"HTTP {e.response.status_code}: Connection test failed"
            except requests.exceptions.RequestException as e:
                errors["overseerr_url"] = f"Connection test failed: {e!s}"
                logging.exception(f"Seerr connection test failed: {e}")

        # If validation failed, return errors
        if errors:
            return {
                "valid": False,
                "errors": errors,
            }

        # Save settings to database
        config.save_setting("overseerr_url", seerr_url)
        config.save_setting("overseerr_api_key", seerr_api_key)
        config.save_setting("overseerr_user_id", data.get("overseerr_user_id", "1"))
        config.save_setting("overseerr_4k", data.get("overseerr_4k", False))

        logging.info("Step 1 (Essential) configuration saved")

        return {
            "valid": True,
            "message": "Essential configuration saved successfully",
        }
    except Exception as e:
        logging.exception(f"Error in step 1: {e}")
        import traceback

        logging.exception(f"Traceback: {traceback.format_exc()}")
        # Return error in same format as validation errors
        return {
            "valid": False,
            "errors": {
                "_general": f"An unexpected error occurred: {e!s}",
            },
        }


@app.post("/api/setup/step2/configuration")
async def save_step2_configuration(data: dict):
    """
    Save and validate Step 2: Configuration (Trakt + Sync settings + Notifications).

    Expected data:
        - trakt_client_id: str
        - sync_interval: int
        - auto_sync: bool
        - timezone: str
        - discord_webhook: str (optional)
        - discord_enabled: bool
        - gotify_url: str (optional)
        - gotify_token: str (optional)
        - gotify_enabled: bool (optional)
    """
    try:
        from list_sync.config import ConfigManager
        from list_sync.utils.timezone_utils import normalize_timezone_input

        config = ConfigManager()
        errors = {}

        # Validate Trakt Client ID
        trakt_client_id = data.get("trakt_client_id", "").strip()
        if not trakt_client_id:
            errors["trakt_client_id"] = "Trakt Client ID is required"

        # Test Trakt Client ID if no errors so far
        if not errors and trakt_client_id:
            # Validate format first - check for valid hex string
            import re

            if len(trakt_client_id) < 16:
                errors["trakt_client_id"] = (
                    "Invalid Trakt Client ID format. Client ID is too short (minimum 16 characters)."
                )
                logging.error("Trakt Client ID validation failed: Too short")
            elif not re.match(r"^[a-f0-9]+$", trakt_client_id.lower()):
                errors["trakt_client_id"] = (
                    "Invalid Trakt Client ID format. Client ID should contain only hexadecimal characters (0-9, a-f)."
                )
                logging.error("Trakt Client ID validation failed: Invalid format")
            else:
                try:
                    headers = {
                        "Content-Type": "application/json",
                        "trakt-api-version": "2",
                        "trakt-api-key": trakt_client_id,
                    }
                    # Use a public endpoint that validates Client ID
                    response = requests.get(
                        "https://api.trakt.tv/calendars/all/movies/2024-01-01/1",
                        headers=headers,
                        timeout=10,
                    )

                    # Check response status
                    # Trakt API returns 401 for unauthorized/invalid Client IDs
                    if response.status_code == 401:
                        # 401 means unauthorized - this indicates an invalid Client ID
                        try:
                            error_data = response.json()
                            error_message = error_data.get("error", "").lower()
                            if (
                                "invalid" in error_message
                                or "unauthorized" in error_message
                                or "forbidden" in error_message
                            ):
                                errors["trakt_client_id"] = (
                                    "Invalid Trakt Client ID. Please verify your Client ID is correct."
                                )
                                logging.error("Trakt Client ID validation failed: Invalid Client ID")
                            else:
                                errors["trakt_client_id"] = (
                                    "Invalid Trakt Client ID. The API returned unauthorized. Please check your Client ID."
                                )
                                logging.error("Trakt Client ID validation failed: Unauthorized")
                        except (ValueError, TypeError, requests.RequestException) as e:
                            logging.debug("Failed to parse Trakt error response: %s", e)
                            # Can't parse error, assume invalid Client ID
                            errors["trakt_client_id"] = (
                                "Invalid Trakt Client ID. The API returned unauthorized. Please check your Client ID."
                            )
                            logging.exception("Trakt Client ID validation failed: Unauthorized")
                    elif response.status_code == 400:
                        errors["trakt_client_id"] = "Invalid Trakt Client ID format. Please check your Client ID."
                        logging.error("Trakt Client ID validation failed: Bad request")
                    else:
                        # Check response headers for Client ID validation
                        api_key_header = response.headers.get("X-API-Key-Status", "").lower()
                        if "invalid" in api_key_header or "rejected" in api_key_header:
                            errors["trakt_client_id"] = "Invalid Trakt Client ID. The API rejected the Client ID."
                            logging.error("Trakt Client ID validation failed: Rejected by API")
                        elif response.status_code in [200, 404]:
                            # 200 or 404 means the request was accepted (Client ID appears valid)
                            logging.info("Trakt Client ID validation successful")
                        else:
                            # Unexpected status - be more cautious
                            logging.warning(
                                f"Trakt Client ID validation returned unexpected status: {response.status_code}"
                            )
                            errors["trakt_client_id"] = (
                                f"Unexpected response from Trakt API (status {response.status_code}). Please check your Client ID."
                            )
                            logging.error(
                                f"Trakt Client ID validation failed: Unexpected status {response.status_code}"
                            )
                except requests.exceptions.Timeout:
                    errors["trakt_client_id"] = "Connection timeout. Check your network connection."
                except requests.exceptions.ConnectionError:
                    errors["trakt_client_id"] = "Could not connect to Trakt API. Check your network."
                except requests.exceptions.RequestException as e:
                    errors["trakt_client_id"] = f"Validation failed: {e!s}"
                    logging.exception(f"Trakt Client ID validation failed: {e}")

        # Validate sync interval
        sync_interval = data.get("sync_interval", 24)
        try:
            sync_interval = int(sync_interval)
            if sync_interval < 1 or sync_interval > 168:
                errors["sync_interval"] = "Sync interval must be between 1 and 168 hours"
        except (ValueError, TypeError):
            errors["sync_interval"] = "Sync interval must be a number"

        # Validate timezone
        timezone = data.get("timezone", "UTC").strip()
        try:
            normalized_tz = normalize_timezone_input(timezone)
            if not normalized_tz:
                errors["timezone"] = "Invalid timezone"
        except Exception as e:
            errors["timezone"] = f"Invalid timezone: {e!s}"

        # Validate Discord webhook if provided
        discord_webhook = data.get("discord_webhook", "").strip()
        discord_enabled = data.get("discord_enabled", False)

        # Checked whenever a webhook is supplied, not only when notifications are
        # switched on. The save below stores it either way, and switching Discord
        # on later is a separate request that carries no URL to check - so a
        # webhook saved while disabled would never be validated at all.
        if discord_webhook:
            from list_sync.utils.settings_validation import validate_discord_webhook

            webhook_error = validate_discord_webhook(discord_webhook)
            if webhook_error:
                errors["discord_webhook"] = webhook_error

        # Validate Gotify URL if provided
        gotify_url = data.get("gotify_url", "").strip()
        gotify_token = data.get("gotify_token", "").strip()
        gotify_enabled = data.get("gotify_enabled", False)

        # Checked whenever a URL is supplied, not only when notifications are
        # switched on. The save below stores it either way, and switching Gotify
        # on later is a separate request that carries no URL to check - so a
        # URL saved while disabled would never be validated at all.
        if gotify_url:
            from list_sync.utils.settings_validation import validate_gotify_url

            gotify_error = validate_gotify_url(gotify_url)
            if gotify_error:
                errors["gotify_url"] = gotify_error

        # If validation failed, return errors
        if errors:
            return {
                "valid": False,
                "errors": errors,
            }

        # Save settings to database
        config.save_setting("trakt_client_id", trakt_client_id)
        config.save_setting("sync_interval", sync_interval)
        config.save_setting("auto_sync", data.get("auto_sync", True))
        config.save_setting("timezone", timezone)

        if discord_webhook:
            config.save_setting("discord_webhook", discord_webhook)
            config.save_setting("discord_enabled", discord_enabled)

        # Persist Gotify settings only when a URL is supplied, mirroring the
        # Discord pattern above — no URL means nothing to store.
        if gotify_url:
            config.save_setting("gotify_url", gotify_url)
            config.save_setting("gotify_token", gotify_token)
            config.save_setting("gotify_enabled", gotify_enabled)

        # Also save to sync_interval table (for compatibility)
        configure_sync_interval(sync_interval)

        logging.info("Step 2 (Configuration) saved")

        return {
            "valid": True,
            "message": "Configuration saved successfully",
        }
    except Exception as e:
        logging.exception(f"Error in step 2: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/setup/step3/content-sources")
async def save_step3_content_sources(data: dict):
    """
    Save and validate Step 3: Content Sources (at least one required).

    Expected data:
        - imdb_lists: str
        - trakt_lists: str
        - trakt_special_lists: str
        - trakt_special_items_limit: int
        - letterboxd_lists: str
        - anilist_lists: str
        - mdblist_lists: str
        - stevenlu_lists: str
        - tmdb_key: str (optional)
        - tmdb_lists: str
        - tvdb_lists: str
        - simkl_lists: str
    """
    try:
        from list_sync.config import ConfigManager

        config = ConfigManager()
        errors = {}
        validated_sources = []

        # Check if at least one list source is provided
        list_fields = [
            "imdb_lists",
            "trakt_lists",
            "trakt_special_lists",
            "letterboxd_lists",
            "anilist_lists",
            "mdblist_lists",
            "stevenlu_lists",
            "tmdb_lists",
            "tvdb_lists",
            "simkl_lists",
        ]

        has_any_list = any(data.get(field, "").strip() for field in list_fields)

        if not has_any_list:
            errors["general"] = "At least one content source is required"
            return {
                "valid": False,
                "errors": errors,
            }

        # Validate and collect sources
        for field in list_fields:
            value = data.get(field, "").strip()
            if value:
                provider = field.replace("_lists", "").replace("_", " ").title()
                validated_sources.append(provider)

        # Save all settings
        for field in list_fields:
            config.save_setting(field, data.get(field, ""))

        # Save TMDB API key if provided
        if tmdb_key := data.get("tmdb_key", "").strip():
            config.save_setting("tmdb_key", tmdb_key)

        # Save special items limit
        trakt_limit = data.get("trakt_special_items_limit", 20)
        try:
            trakt_limit = int(trakt_limit)
        except (ValueError, TypeError):
            trakt_limit = 20  # best-effort; invalid limit ignored, use default
        config.save_setting("trakt_special_items_limit", trakt_limit)

        logging.info(f"Step 3 (Content Sources) saved: {', '.join(validated_sources)}")

        return {
            "valid": True,
            "message": "Content sources saved successfully",
            "validated_sources": validated_sources,
        }
    except Exception as e:
        logging.exception(f"Error in step 3: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/setup/complete")
async def complete_setup():
    """
    Mark setup wizard as completed and trigger initial sync.
    """
    try:
        from list_sync.config import ConfigManager

        config = ConfigManager()

        # Mark setup as complete
        config.mark_setup_complete()

        # Load lists from config into database
        from list_sync.config import load_env_lists

        load_env_lists()

        logging.info("Setup wizard completed successfully")

        return {
            "success": True,
            "message": "Setup completed successfully. ListSync is ready to sync!",
        }
    except Exception as e:
        logging.exception(f"Error completing setup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sync-interval")
async def get_sync_interval():
    """Get current sync interval with source tracking"""
    try:
        # Always check database first
        db_interval = load_sync_interval()
        if db_interval > 0:
            return {
                "interval_hours": db_interval,
                "source": "database",
                "last_updated": None,  # Could add timestamp tracking
            }

        # If no database interval, check environment and initialize database
        try:
            _, _, _, env_interval, _, _ = load_env_config()
            if env_interval > 0:
                # Save environment interval to database for future use
                configure_sync_interval(env_interval)
                return {
                    "interval_hours": env_interval,
                    "source": "environment_initialized",
                    "last_updated": None,
                    "message": "Environment interval saved to database",
                }
        except Exception as e:
            logging.debug("Failed to initialize sync interval from environment: %s", e)

        # Default
        return {
            "interval_hours": 12.0,
            "source": "default",
            "last_updated": None,
            "message": "No interval configured, using default",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/sync-interval")
async def update_sync_interval(update: SyncIntervalUpdate):
    """Update sync interval in database"""
    try:
        configure_sync_interval(update.interval_hours)
        return {
            "success": True,
            "message": f"Sync interval updated to {update.interval_hours} hours",
            "interval_hours": update.interval_hours,
            "source": "database",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sync-interval/sync-from-env")
async def sync_interval_from_env():
    """Populate database from environment variable (force initialization)"""
    try:
        _, _, _, env_interval, _, _ = load_env_config()
        if env_interval > 0:
            configure_sync_interval(env_interval)
            return {
                "success": True,
                "message": f"Sync interval populated from environment: {env_interval} hours",
                "interval_hours": env_interval,
                "source": "environment",
            }
        return {
            "success": False,
            "message": "No sync interval found in environment",
            "interval_hours": 0,
            "source": "none",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/sync")
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


@app.get("/api/stats/data-quality")
async def get_data_quality():
    """Get data quality analysis"""
    try:
        analysis = analyze_data_quality()
        if analysis is None:
            raise HTTPException(status_code=500, detail="Could not analyze data quality")
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/status-breakdown")
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


@app.get("/api/activity/recent")
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


@app.get("/api/activity/recent/docker")
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


@app.get("/api/lists")
async def get_lists():
    """Get all configured lists"""
    try:
        lists = load_list_ids()
        user_names = _overseerr_user_names()

        # Add display names and include item counts, last_synced, and user_id with proper timezone conversion
        formatted_lists = []
        for i, list_item in enumerate(lists):
            # Extract clean display name from list ID (URL)
            list_id = list_item["id"]
            list_type = list_item["type"]

            # Extract just the meaningful part of the URL/ID for display
            if list_id.startswith(("http://", "https://")):
                # Parse URL to get the last meaningful segment
                try:
                    from urllib.parse import urlparse

                    parsed = urlparse(list_id.rstrip("/"))
                    path_parts = [p for p in parsed.path.split("/") if p]

                    # For Trakt URLs like /users/{user}/lists/{name}
                    if "trakt" in list_type and len(path_parts) >= 4 and "lists" in path_parts:
                        list_name = path_parts[-1]  # Get the last segment
                    # For other URLs, just get the last segment
                    else:
                        list_name = path_parts[-1] if path_parts else list_id

                    display_name = list_name
                except Exception:
                    display_name = list_id
            else:
                # Not a URL, use as-is
                display_name = list_id

            # Convert last_synced timestamp from UTC to local timezone
            last_synced = list_item.get("last_synced")
            if last_synced:
                try:
                    # SQLite CURRENT_TIMESTAMP returns UTC time without timezone info
                    # Parse it as UTC and convert to local timezone
                    import zoneinfo
                    from datetime import datetime

                    from list_sync.utils.timezone_utils import get_timezone_from_env

                    # Parse UTC timestamp
                    utc_dt = datetime.fromisoformat(last_synced).replace(tzinfo=UTC)

                    # Get configured timezone
                    local_tz_name = get_timezone_from_env()
                    local_tz = zoneinfo.ZoneInfo(local_tz_name)

                    # Convert to local timezone
                    local_dt = utc_dt.astimezone(local_tz)

                    # Return as ISO string with timezone info
                    last_synced = local_dt.isoformat()
                except Exception as e:
                    logging.exception(f"Error converting timestamp {last_synced}: {e}")
                    # Keep original timestamp as fallback

            formatted_lists.append(
                {
                    "id": i + 1,
                    "list_type": list_item["type"],
                    "list_id": list_item["id"],
                    "list_url": list_item.get("url"),  # Include the stored URL
                    "display_name": display_name,
                    "item_count": list_item.get("item_count", 0),  # Include item count from database
                    "last_synced": last_synced,  # Include converted last_synced timestamp
                    "user_id": list_item.get("user_id", "1"),  # Include user_id for per-list user assignment
                    # Resolve the name here so the UI can show who a list requests
                    # as even before the users store has loaded
                    "user_display_name": user_names.get(str(list_item.get("user_id", "1"))) or None,
                }
            )

        return {"lists": formatted_lists}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/lists/debug")
async def get_lists_debug():
    """Get all configured lists with debug information"""
    try:
        lists = load_list_ids()
        # Also get raw database data for debugging
        raw_data = get_raw_lists()

        return {
            "lists": lists,
            "total_count": len(lists),
            "raw_database_data": [
                {
                    "list_type": row[0],
                    "list_id": row[1],
                    "list_url": row[2],
                    "item_count": row[3],
                    "last_synced": row[4],
                }
                for row in raw_data
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _overseerr_user_names() -> dict[str, str]:
    """Map Seerr user IDs to display names, from the local user cache."""
    try:
        from list_sync.database import get_seerr_users

        return {str(u.get("id")): (u.get("display_name") or u.get("email") or "") for u in (get_seerr_users() or [])}
    except Exception as e:
        logging.debug(f"Could not load Seerr user names: {e}")
        return {}


def _describe_overseerr_user(user_id: str) -> str | None:
    """Look up an Seerr user's display name from the local user cache."""
    return _overseerr_user_names().get(str(user_id)) or None


def _validate_overseerr_user(user_id: str) -> str | None:
    """
    Check a user ID against the known Seerr users.

    Returns:
        Optional[str]: An error message if the user is definitely unusable,
            None if the user is fine or can't be verified right now.
    """
    try:
        from list_sync.database import get_seerr_users

        users = get_seerr_users()
    except Exception as e:
        logging.debug(f"Could not verify user {user_id}: {e}")
        return None

    # An empty cache means users have never been synced - don't block on it.
    if not users:
        return None

    if any(str(u.get("id")) == str(user_id) for u in users):
        return None

    known = ", ".join(f"{u.get('id')} ({u.get('display_name')})" for u in users[:20])
    return (
        f"Seerr user ID {user_id} does not exist. Known users: {known}. "
        f"Re-sync users from Settings if this looks out of date."
    )


@app.patch("/api/lists/{list_type}/{list_id:path}/user")
async def update_list_user_endpoint(list_type: str, list_id: str, payload: ListUserUpdate):
    """Change which Seerr user a list requests as - uses :path for full URLs"""
    try:
        user_id = str(payload.user_id).strip()
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        validation_error = _validate_overseerr_user(user_id)
        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)

        if not update_list_user_id(list_type, list_id, user_id):
            raise HTTPException(
                status_code=404,
                detail=f"No {list_type} list found matching '{list_id}'",
            )

        display_name = _describe_overseerr_user(user_id)
        return {
            "success": True,
            "list_type": list_type,
            "list_id": list_id,
            "user_id": user_id,
            "user_display_name": display_name,
            "message": f"{list_type} list now requests as {display_name or f'user {user_id}'}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/lists")
async def add_list(list_add: ListAdd):
    """Add new list with URL generation and auto-detection of special Trakt lists"""
    try:
        # Import the construct_list_url function
        from list_sync.utils.helpers import construct_list_url

        list_type = list_add.list_type
        list_id = list_add.list_id
        user_id = str(list_add.user_id).strip() or "1"

        # Catch a bad requester here rather than at sync time, when it would
        # surface as a failure on every item in the list.
        validation_error = _validate_overseerr_user(user_id)
        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)

        # Auto-detect special Trakt lists (trending:movies, popular:shows, etc.)
        if list_type == "trakt" and ":" in list_id:
            parts = list_id.split(":")
            if len(parts) == 2:
                category, media_type = parts
                if media_type.lower() in ["movies", "movie", "shows", "show", "tv"]:
                    list_type = "trakt_special"
                    logging.info(f"Auto-detected special Trakt list: {list_id}")

        # Generate the URL for the list
        list_url = construct_list_url(list_type, list_id)

        # Save with the generated URL, default item count of 0, and user_id
        save_list_id(list_id, list_type, list_url, item_count=0, user_id=user_id)

        return {
            "success": True,
            "message": f"Added {list_type} list: {list_id}",
            "list_url": list_url,
            "item_count": 0,
            "user_id": user_id,
            "user_display_name": _describe_overseerr_user(user_id),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/lists/{list_type}/{list_id:path}/items")
async def get_list_items_endpoint(list_type: str, list_id: str, limit: int = Query(20, ge=1, le=100)):
    """Get items from a specific list with enriched metadata"""
    try:
        items = get_list_items(list_type, list_id)

        # Get poster URLs from database
        item_ids = [item["id"] for item in items[:limit]]
        poster_url_map = {}

        if item_ids:
            try:
                poster_url_map = get_poster_urls(item_ids)
            except Exception as e:
                logging.warning(f"Failed to fetch poster URLs: {e}")

        # Enrich items with poster URLs
        limited_items = []
        for item in items[:limit]:
            enriched_item = {
                **item,
                "poster_url": poster_url_map.get(item["id"]),
            }
            limited_items.append(enriched_item)

        return {
            "items": limited_items,
            "total": len(items),
            "limit": limit,
            "has_more": len(items) > limit,
        }
    except Exception as e:
        logging.exception(f"Error fetching list items: {e!s}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/lists/{list_type}/{list_id:path}")
async def delete_list_endpoint(list_type: str, list_id: str):
    """Delete list - uses :path to capture full URLs with forward slashes"""
    try:
        # FastAPI automatically URL-decodes path parameters, so list_id is already decoded
        # The :path type allows capturing the full path including forward slashes
        # Log the parameters for debugging
        logging.info(f"Delete request - list_type: {list_type}, list_id: {list_id}")

        # Try to delete the list
        success = delete_list(list_type, list_id)

        if success:
            logging.info(f"Successfully deleted list: {list_type}/{list_id}")
            return {
                "success": True,
                "message": f"Deleted {list_type} list: {list_id}",
            }
        # List not found - provide helpful error message
        existing_lists = load_list_ids()
        available_lists = [f"{item['type']}: {item['id']}" for item in existing_lists if item["type"] == list_type]
        error_msg = f"List not found: {list_type}/{list_id}"
        if available_lists:
            error_msg += f". Available {list_type} lists: {', '.join(available_lists[:3])}"  # Limit to 3 examples
        logging.warning(error_msg)
        raise HTTPException(status_code=404, detail=error_msg)

    except HTTPException:
        # Re-raise HTTP exceptions (like 404)
        raise
    except Exception as e:
        logging.error(f"Error deleting list {list_type}/{list_id}: {e!s}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/items")
async def get_items(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100)):
    """Get all synced items (deduplicated)"""
    try:
        unique_items = get_deduplicated_items()

        # Calculate pagination
        total = len(unique_items)
        total_pages = (total + limit - 1) // limit
        start = (page - 1) * limit
        end = start + limit

        # Sort by last_synced descending
        sorted_items = sorted(unique_items, key=lambda x: x[6], reverse=True)
        page_items = sorted_items[start:end]

        items = []
        for item in page_items:
            (
                item_id,
                title,
                media_type,
                year,
                imdb_id,
                overseerr_id,
                status,
                last_synced,
                source_list_type,
                source_list_id,
            ) = item

            # Build list_sources from source columns
            list_sources = []
            if source_list_type and source_list_id:
                list_sources.append(
                    {
                        "list_type": source_list_type,
                        "list_id": source_list_id,
                        "display_name": None,
                    }
                )

            items.append(
                {
                    "id": item_id,
                    "title": title,
                    "media_type": media_type,
                    "year": year,
                    "imdb_id": imdb_id,
                    "overseerr_id": overseerr_id,
                    "status": status,
                    "last_synced": last_synced,
                    "list_sources": list_sources,
                }
            )

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Simple in-memory cache for metadata (expires after 1 hour)
_metadata_cache = {}
_cache_ttl = 3600  # 1 hour in seconds


@app.post("/api/items/enriched/clear-cache")
async def clear_enriched_cache():
    """Clear the metadata cache (useful after fixing data issues)"""
    global _metadata_cache
    cache_size = len(_metadata_cache)
    _metadata_cache = {}
    logging.info(f"Cleared metadata cache ({cache_size} entries)")
    return {"message": f"Cleared {cache_size} cached entries", "success": True}


@app.get("/api/items/enriched")
async def get_enriched_items(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    list_source: str = Query("", description="Filter by list source in format 'list_type:list_id'"),
):
    """Get synced items enriched with Trakt metadata (poster, rating, etc.)"""
    try:
        import time

        from list_sync.providers.trakt import get_trakt_metadata

        # Debug: Check item_lists table
        try:
            item_lists_count = count_item_lists()
            logging.info(f"📊 item_lists table has {item_lists_count} entries")
        except Exception as e:
            logging.warning(f"Could not check item_lists table: {e}")

        # Get base items (deduplicated)
        unique_items = get_deduplicated_items()

        # Filter by list source if specified (before pagination)
        # Filter directly using source_list_type and source_list_id columns from synced_items
        if list_source and list_source.strip():
            try:
                filter_list_type, filter_list_id = list_source.split(":", 1)

                # Normalize the list_id to match what's stored in database
                normalized_list_id = normalize_list_id(filter_list_type, filter_list_id)

                logging.info(
                    f"📋 Filtering by list {filter_list_type}:{filter_list_id} (normalized: {normalized_list_id})"
                )

                # Filter items where source_list_type and source_list_id match
                # Item tuple: (id, title, media_type, year, imdb_id, overseerr_id, status, last_synced, source_list_type, source_list_id)
                before_count = len(unique_items)
                unique_items = [
                    item
                    for item in unique_items
                    if (item[8] == filter_list_type and (item[9] == normalized_list_id or item[9] == filter_list_id))
                ]

                logging.info(
                    f"📋 Filtered {before_count} items → {len(unique_items)} items match list {filter_list_type}:{filter_list_id}"
                )
            except ValueError:
                # Invalid list_source format, ignore filter
                logging.warning(f"Invalid list_source format: {list_source}, ignoring filter")

        # Calculate pagination on filtered items
        total = len(unique_items)
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        start = (page - 1) * limit
        end = start + limit

        # Sort by last_synced descending (most recently synced first)
        # Handle None values by putting them at the end
        sorted_items = sorted(
            unique_items,
            key=lambda x: x[7] if x[7] is not None else "",
            reverse=True,
        )
        page_items = sorted_items[start:end]

        # Get overseerr URL for constructing links
        config_tuple = load_env_config()
        seerr_url = config_tuple[0] if config_tuple else None

        # Batch fetch tmdb_ids, poster URLs, and list sources from database (more efficient)
        item_ids = [item[0] for item in page_items]
        tmdb_id_map = {}
        poster_url_map = {}
        item_lists_map = {}  # Map item_id to list of lists it belongs to

        try:
            tmdb_id_map, poster_url_map = get_item_tmdb_and_posters(item_ids)
            # Convert tmdb_id values to int (DAL returns raw values)
            for _k, _v in list(tmdb_id_map.items()):
                if _v is not None:
                    try:
                        tmdb_id_map[_k] = int(_v) if isinstance(_v, str) else _v
                    except (ValueError, TypeError):
                        logging.warning(f"Invalid tmdb_id format for item {_k}: {_v}")
            item_lists_map = get_item_lists_for_items(item_ids)

            # Debug: Log how many items have list sources
            items_with_sources = len([k for k, v in item_lists_map.items() if v])
            logging.info(f"📦 Fetched list_sources for {items_with_sources}/{len(item_ids)} items")
            if items_with_sources > 0:
                sample_item = next((k for k, v in item_lists_map.items() if v), None)
                if sample_item:
                    logging.info(
                        f"📋 Sample: Item {sample_item} has {len(item_lists_map[sample_item])} list(s): {item_lists_map[sample_item]}"
                    )
        except Exception as e:
            logging.warning(f"Failed to batch fetch tmdb_ids, poster URLs, and list sources: {e}")

        enriched_items = []
        current_time = time.time()

        for item in page_items:
            (
                item_id,
                title,
                media_type,
                year,
                imdb_id,
                overseerr_id,
                status,
                last_synced,
                source_list_type,
                source_list_id,
            ) = item

            # Get tmdb_id and poster_url from batch fetch
            tmdb_id = tmdb_id_map.get(item_id)
            cached_poster_url = poster_url_map.get(item_id)

            # Get list sources for this item (from item_lists join table for multi-list support)
            list_sources = item_lists_map.get(item_id, [])

            # If no list sources from item_lists, use the source_list columns as fallback
            if not list_sources and source_list_type and source_list_id:
                list_sources = [
                    {
                        "list_type": source_list_type,
                        "list_id": source_list_id,
                        "display_name": None,
                    }
                ]

            # Create base enriched item
            enriched_item = {
                "id": item_id,
                "title": title,
                "media_type": media_type,
                "year": year,
                "imdb_id": imdb_id,
                "tmdb_id": tmdb_id,
                "overseerr_id": overseerr_id,
                "status": status,
                "last_synced": last_synced,
                "poster_url": cached_poster_url,  # Use cached poster URL if available
                "rating": None,
                "overview": None,
                "genres": [],
                "overseerr_url": None,
                "list_sources": list_sources,  # Add list sources
            }

            # Construct Seerr URL if available
            if overseerr_id and seerr_url:
                media_type_path = "tv" if media_type == "tv" else "movie"
                enriched_item["overseerr_url"] = f"{seerr_url.rstrip('/')}/{media_type_path}/{overseerr_id}"

            # Skip enrichment if no IDs available
            if not tmdb_id and not imdb_id:
                enriched_items.append(enriched_item)
                continue

            # Try to enrich with metadata from cache or API
            cache_key = f"{media_type}_{tmdb_id or imdb_id}"

            # Check if we have a cached poster URL from database
            if cached_poster_url:
                # We already have the poster URL, no need to fetch metadata
                enriched_items.append(enriched_item)
                continue

            # Check metadata cache
            if cache_key in _metadata_cache:
                cached_data, cache_time = _metadata_cache[cache_key]
                if current_time - cache_time < _cache_ttl:
                    # Use cached data
                    poster_url = cached_data.get("poster_url")
                    if poster_url:
                        from list_sync.database import update_item_poster_url

                        update_item_poster_url(item_id, poster_url)

                    enriched_item.update(
                        {
                            "poster_url": poster_url,
                            "rating": cached_data.get("rating"),
                            "overview": cached_data.get("overview"),
                            "genres": cached_data.get("genres", []),
                        }
                    )
                    enriched_items.append(enriched_item)
                    continue

            # Fetch from API if not in cache or cache expired
            try:
                metadata = get_trakt_metadata(
                    tmdb_id=tmdb_id,
                    imdb_id=imdb_id,
                    media_type=media_type,
                )

                if metadata:
                    # Cache the metadata (even if some fields are None)
                    _metadata_cache[cache_key] = (metadata, current_time)

                    # Store poster URL in database for this item
                    poster_url = metadata.get("poster_url")
                    if poster_url:
                        from list_sync.database import update_item_poster_url

                        update_item_poster_url(item_id, poster_url)

                    # Enrich item
                    enriched_item.update(
                        {
                            "poster_url": poster_url,
                            "rating": metadata.get("rating"),
                            "overview": metadata.get("overview"),
                            "genres": metadata.get("genres", []),
                        }
                    )
                else:
                    # Cache negative result to avoid repeated failed lookups
                    _metadata_cache[cache_key] = ({}, current_time)
            except Exception as e:
                logging.warning(f"Failed to enrich item '{title}' (ID: {item_id}): {e}")
                # Cache the error to avoid repeated attempts
                _metadata_cache[cache_key] = ({}, current_time)

            enriched_items.append(enriched_item)

        return {
            "items": enriched_items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
        }

    except Exception as e:
        logging.exception(f"Error in enriched items endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/overseerr/status")
async def get_overseerr_status():
    """Check Seerr connection status"""
    try:
        # Load environment configuration - returns a tuple
        config_tuple = load_env_config()
        seerr_url, seerr_api_key, user_id, sync_interval, automated_mode, is_4k = config_tuple

        if not seerr_url or not seerr_api_key:
            return {
                "isConnected": False,
                "error": "Seerr URL or API key not configured",
                "lastChecked": datetime.now().isoformat(),
            }

        # Make request to Seerr status endpoint
        headers = {
            "X-Api-Key": seerr_api_key,
            "Content-Type": "application/json",
        }

        # Clean URL and add status endpoint
        base_url = seerr_url.rstrip("/")
        status_url = f"{base_url}/api/v1/status"

        response = requests.get(status_url, headers=headers, timeout=10)

        if response.status_code == 200:
            status_data = response.json()
            return {
                "isConnected": True,
                "version": status_data.get("version", "Unknown"),
                "updateAvailable": status_data.get("updateAvailable", False),
                "commitsBehind": status_data.get("commitsBehind", 0),
                "restartRequired": status_data.get("restartRequired", False),
                "lastChecked": datetime.now().isoformat(),
            }
        return {
            "isConnected": False,
            "error": f"HTTP {response.status_code}: {response.text}",
            "lastChecked": datetime.now().isoformat(),
        }

    except requests.exceptions.RequestException as e:
        return {
            "isConnected": False,
            "error": f"Connection error: {e!s}",
            "lastChecked": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "isConnected": False,
            "error": f"Unexpected error: {e!s}",
            "lastChecked": datetime.now().isoformat(),
        }


@app.get("/api/system/time")
async def get_current_time():
    """Get current server time with enhanced timezone support"""
    try:
        # Get comprehensive timezone info using our utilities
        tz_info = get_current_timezone_info()

        # Parse the timezone-aware datetime
        current_time = datetime.fromisoformat(tz_info["current_time"])

        return {
            "current_time": tz_info["current_time"],
            "timestamp": current_time.timestamp(),
            "timezone": {
                "name": tz_info["timezone_name"],
                "abbreviation": tz_info["timezone_abbreviation"],
                "utc_offset": tz_info["utc_offset"],
                "is_dst": tz_info["is_dst"],
            },
            "formatted": {
                "date": current_time.strftime("%a, %b %d"),
                "time": current_time.strftime("%I:%M %p"),
                "full": tz_info["formatted_time"],
                "iso": tz_info["current_time"],
            },
        }
    except Exception as e:
        # Fallback to basic datetime if timezone utilities fail
        now = datetime.now()
        return {
            "current_time": now.isoformat(),
            "timestamp": now.timestamp(),
            "timezone": {
                "name": "UTC",
                "abbreviation": "UTC",
                "utc_offset": "+0000",
                "is_dst": False,
            },
            "formatted": {
                "date": now.strftime("%a, %b %d"),
                "time": now.strftime("%I:%M %p"),
                "full": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "iso": now.isoformat(),
            },
            "error": str(e),
        }


@app.post("/api/sync/trigger")
async def trigger_manual_sync(sync_request: dict = None):
    """Trigger a manual sync by sending SIGUSR1 signal to ListSync process"""
    try:
        from list_sync.utils.sync_status import clear_pause_until

        # Parse request body if provided
        sync_type = "all"  # default
        target_list = None

        if sync_request:
            # CRITICAL: Check for direct list_type/list_id FIRST (from our web UI)
            # This ensures single list sync requests are detected correctly
            if sync_request.get("list_type") and sync_request.get("list_id"):
                target_list = {
                    "list_type": sync_request["list_type"],
                    "list_id": sync_request["list_id"],
                }
                sync_type = "single"
                logging.debug(f"DEBUG - Detected single list sync request: {target_list}")
            else:
                # Check for explicit type field or nested list object
                sync_type = sync_request.get("type", "all")  # "all", "single"
                target_list = sync_request.get("list")  # {list_type: "imdb", list_id: "top"}

                # If type is "single" but target_list is not set, try to extract from list object
                if sync_type == "single" and target_list:
                    if isinstance(target_list, dict) and "list_type" in target_list and "list_id" in target_list:
                        # Already in correct format
                        pass
                    else:
                        logging.warning(
                            f"WARNING - Single sync type specified but target_list format is invalid: {target_list}"
                        )

        # Validation: If we have target_list but sync_type is not "single", correct it
        if target_list and sync_type != "single":
            logging.warning(f"WARNING - target_list detected but sync_type is '{sync_type}', correcting to 'single'")
            sync_type = "single"

        logging.debug(
            f"DEBUG - Sync request parsed: type={sync_type}, target={target_list}, raw_request={sync_request}"
        )

        # Find ListSync processes
        processes = find_listsync_processes()

        if not processes:
            raise HTTPException(
                status_code=404,
                detail="No ListSync process found. Please ensure ListSync is running in automated mode.",
            )

        # For single list sync, create a request file
        if sync_type == "single" and target_list:
            import json
            import os
            import uuid

            logging.debug(f"DEBUG - Creating single list sync request file for: {target_list}")

            # Create the request data
            request_data = {
                "list_type": target_list["list_type"],
                "list_id": target_list["list_id"],
                "timestamp": datetime.now().isoformat(),
                "requested_by": "web_ui",
            }

            # Ensure data directory exists
            os.makedirs("data/sync_requests", exist_ok=True)

            # Use a unique filename with timestamp and UUID to prevent overwrites
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            request_file = f"data/sync_requests/single_sync_{timestamp_str}_{unique_id}.json"

            with open(request_file, "w") as f:
                json.dump(request_data, f, indent=2)

            logging.debug(f"DEBUG - Single list sync request file created: {request_file}")

            # Also maintain the legacy single file for backwards compatibility
            legacy_file = "data/single_list_sync_request.json"
            with open(legacy_file, "w") as f:
                json.dump(request_data, f, indent=2)

            # Also set environment variables as fallback (though these may not persist across processes)
            os.environ["SINGLE_LIST_SYNC"] = "true"
            os.environ["SINGLE_LIST_TYPE"] = target_list["list_type"]
            os.environ["SINGLE_LIST_ID"] = target_list["list_id"]

            logging.debug(
                f"DEBUG - Environment variables set as fallback: SINGLE_LIST_SYNC=true, SINGLE_LIST_TYPE={target_list['list_type']}, SINGLE_LIST_ID={target_list['list_id']}"
            )
        else:
            # Clear any existing single list request file for full sync
            import os

            request_file = "data/single_list_sync_request.json"
            if os.path.exists(request_file):
                os.remove(request_file)
                logging.debug("DEBUG - Removed existing single list sync request file")

            # Clear single list environment variables for full sync
            os.environ.pop("SINGLE_LIST_SYNC", None)
            os.environ.pop("SINGLE_LIST_TYPE", None)
            os.environ.pop("SINGLE_LIST_ID", None)
            logging.debug("DEBUG - Cleared single list environment variables for full sync")

        # Clear any pause (e.g., set after cancellation) so manual trigger runs immediately
        try:
            clear_pause_until()
        except Exception as e:
            logging.exception(f"WARNING - Could not clear pause before manual sync: {e}")

        # Send SIGUSR1 signal to trigger sync (works for both single and full)
        signals_sent = []
        errors = []

        for process in processes:
            try:
                # Send SIGUSR1 signal to trigger immediate sync
                os.kill(process.pid, signal.SIGUSR1)
                signals_sent.append(
                    {
                        "pid": process.pid,
                        "cmdline": process.cmdline,
                        "status": "signal_sent",
                    }
                )
                logging.info(f"Sent SIGUSR1 signal to ListSync process PID {process.pid}")

            except ProcessLookupError:
                errors.append(
                    {
                        "pid": process.pid,
                        "error": "Process not found (may have exited)",
                    }
                )
            except PermissionError:
                errors.append(
                    {
                        "pid": process.pid,
                        "error": "Permission denied (insufficient privileges)",
                    }
                )
            except Exception as e:
                errors.append(
                    {
                        "pid": process.pid,
                        "error": str(e),
                    }
                )

        if not signals_sent and errors:
            # All signals failed
            raise HTTPException(
                status_code=500,
                detail=f"Failed to send signals to any ListSync process: {errors}",
            )

        return {
            "success": True,
            "sync_type": sync_type,
            "target_list": target_list if sync_type == "single" else None,
            "message": f"Manual {sync_type} sync triggered successfully for {len(signals_sent)} process(es)",
            "signals_sent": signals_sent,
            "errors": errors if errors else None,
            "note": "Sync should start immediately if ListSync is running in automated mode",
            "method": "file_based" if sync_type == "single" else "signal_only",
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error triggering manual sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _close_running_sync_record(status: str, message: str, pid: int | None = None) -> None:
    """
    Close out the in-progress sync record after killing the process running it.

    A killed sync never reaches its own end_sync_in_db call, so without this the
    record stays in_progress and the dashboard keeps reporting a sync that is
    no longer running.

    Args:
        status: Final status to record
        message: Error message explaining what happened
        pid: Only close the record if it belongs to this process, so a sync
            running elsewhere is never closed by mistake
    """
    try:
        from list_sync.database import end_sync_in_db, get_current_sync_status

        sync_status = get_current_sync_status(clear_stale=False)
        if not sync_status or sync_status.get("in_progress") != 1:
            return
        if pid is not None and sync_status.get("pid") != pid:
            logging.info(
                f"Leaving sync record {sync_status.get('session_id')} alone: "
                f"it belongs to PID {sync_status.get('pid')}, not {pid}",
            )
            return

        end_sync_in_db(
            session_id=sync_status.get("session_id"),
            status=status,
            total_items=sync_status.get("total_items", 0) or 0,
            items_requested=sync_status.get("items_requested", 0) or 0,
            items_skipped=sync_status.get("items_skipped", 0) or 0,
            items_errors=sync_status.get("items_errors", 0) or 0,
            error_message=message,
        )
    except Exception as e:
        logging.warning(f"Could not close sync record after {status}: {e}")


def _run_sync_in_subprocess(
    list_type: str, list_id: str, seerr_url: str, seerr_api_key: str, is_4k: bool, result_queue: multiprocessing.Queue
):
    """
    Worker function to run sync in a subprocess.
    This function is called by multiprocessing.Process.
    """
    try:
        # Import inside subprocess to avoid issues
        from list_sync.main import sync_single_list
        from list_sync.utils.sync_status import get_sync_tracker

        # Set the subprocess PID in the tracker
        sync_tracker = get_sync_tracker()
        sync_tracker.set_subprocess_pid(os.getpid())

        result = sync_single_list(
            list_type,
            list_id,
            seerr_url,
            seerr_api_key,
            None,  # Let sync_single_list fetch user_id from list's database record
            is_4k,
        )
        result_queue.put({"success": True, "result": result})
    except Exception as e:
        result_queue.put({"success": False, "error": str(e)})


async def trigger_single_list_sync(target_list: dict, processes: list):
    """Trigger sync for a single specific list using a terminable subprocess"""
    try:
        import tempfile

        list_type = target_list.get("list_type")
        list_id = target_list.get("list_id")

        if not list_type or not list_id:
            raise HTTPException(
                status_code=400,
                detail="Both list_type and list_id are required for single list sync",
            )

        logging.debug(f"DEBUG - Starting single list sync for {list_type}:{list_id}")

        # Create a temporary configuration for single list sync
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as temp_file:
            temp_config = {
                "single_list_sync": True,
                "target_list": {
                    "type": list_type,
                    "id": list_id,
                },
                "timestamp": datetime.now().isoformat(),
            }
            json.dump(temp_config, temp_file)
            temp_file_path = temp_file.name

        try:
            logging.debug("DEBUG - Attempting to import sync functions...")

            # Import the config loader
            from list_sync.config import load_env_config
            from list_sync.utils.sync_status import get_sync_tracker

            logging.debug("DEBUG - Import successful, loading environment config...")

            # Load environment configuration
            seerr_url, seerr_api_key, _, sync_interval, automated_mode, is_4k = load_env_config()

            logging.debug(f"DEBUG - Environment loaded. URL: {seerr_url[:20] if seerr_url else 'None'}...")
            logging.debug("DEBUG - Starting sync in subprocess for immediate termination support...")

            # Create a queue to receive results from subprocess
            result_queue = multiprocessing.Queue()

            # Create and start subprocess
            sync_process = multiprocessing.Process(
                target=_run_sync_in_subprocess,
                args=(list_type, list_id, seerr_url, seerr_api_key, is_4k, result_queue),
            )
            sync_process.start()
            subprocess_pid = sync_process.pid

            logging.debug(f"DEBUG - Sync subprocess started with PID {subprocess_pid}")

            # Register the subprocess PID in the tracker for immediate cancellation
            sync_tracker = get_sync_tracker()
            sync_tracker.set_subprocess_pid(subprocess_pid)

            # Wait for the subprocess with polling to allow for cancellation
            timeout_seconds = 3600  # 1 hour timeout for long syncs
            poll_interval = 0.5  # Check every 0.5 seconds
            elapsed = 0

            while sync_process.is_alive() and elapsed < timeout_seconds:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                # Check if cancellation was requested
                if sync_tracker.is_cancellation_requested():
                    logging.debug(f"DEBUG - Cancellation requested, terminating subprocess {subprocess_pid}")
                    sync_process.terminate()
                    sync_process.join(timeout=2)
                    if sync_process.is_alive():
                        sync_process.kill()
                    sync_tracker.end_sync()
                    _close_running_sync_record(
                        "cancelled",
                        "Sync cancelled by user",
                        pid=subprocess_pid,
                    )
                    return {
                        "success": False,
                        "sync_type": "single",
                        "target_list": target_list,
                        "message": f"Sync cancelled by user for {list_type}:{list_id}",
                        "cancelled": True,
                        "timestamp": datetime.now().isoformat(),
                    }

            # Check if process timed out
            if sync_process.is_alive():
                logging.warning(f"ERROR - Sync timed out after {timeout_seconds} seconds, terminating...")
                sync_process.terminate()
                sync_process.join(timeout=2)
                if sync_process.is_alive():
                    sync_process.kill()
                sync_tracker.end_sync()
                _close_running_sync_record(
                    "failed",
                    f"Sync timed out after {timeout_seconds} seconds",
                    pid=subprocess_pid,
                )
                return {
                    "success": False,
                    "sync_type": "single",
                    "target_list": target_list,
                    "message": f"Single list sync timed out for {list_type}:{list_id}",
                    "error": f"Sync operation timed out after {timeout_seconds} seconds",
                    "fallback_suggestion": "Try using 'Sync All Lists' or check if the list URL is accessible",
                    "timestamp": datetime.now().isoformat(),
                }

            # Process completed, get result
            try:
                result_data = result_queue.get_nowait()
                if result_data.get("success"):
                    logging.debug(f"DEBUG - Sync completed successfully: {result_data.get('result')}")
                    return {
                        "success": True,
                        "sync_type": "single",
                        "target_list": target_list,
                        "message": f"Single list sync completed for {list_type}:{list_id}",
                        "result": result_data.get("result"),
                        "timestamp": datetime.now().isoformat(),
                    }
                logging.warning(f"ERROR - Sync failed: {result_data.get('error')}")
                return {
                    "success": False,
                    "sync_type": "single",
                    "target_list": target_list,
                    "message": f"Single list sync failed for {list_type}:{list_id}",
                    "error": result_data.get("error"),
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as queue_error:
                logging.exception(f"ERROR - Could not get result from queue: {queue_error}")
                # Process exited but no result - check exit code
                exit_code = sync_process.exitcode
                if exit_code == 0:
                    return {
                        "success": True,
                        "sync_type": "single",
                        "target_list": target_list,
                        "message": f"Single list sync completed for {list_type}:{list_id}",
                        "timestamp": datetime.now().isoformat(),
                    }
                return {
                    "success": False,
                    "sync_type": "single",
                    "target_list": target_list,
                    "message": f"Single list sync failed for {list_type}:{list_id}",
                    "error": f"Process exited with code {exit_code}",
                    "timestamp": datetime.now().isoformat(),
                }

        except ImportError as e:
            logging.exception(f"ERROR - Import failed: {e}")
            # Fallback: If direct import fails, use signal with temp file approach
            logging.info("Direct sync import failed, falling back to signal method")

            # Try to trigger full sync instead
            try:
                for process in processes:
                    os.kill(process.pid, signal.SIGUSR1)
                    logging.info(f"Sent SIGUSR1 signal to process {process.pid} as fallback")

                return {
                    "success": True,
                    "sync_type": "fallback_full_sync",
                    "target_list": target_list,
                    "message": "Single list sync not available, triggered full sync instead",
                    "note": "The single list feature isn't fully implemented. A full sync has been triggered.",
                    "fallback_action": "triggered_full_sync",
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as signal_error:
                logging.exception(f"ERROR - Signal fallback also failed: {signal_error}")
                return {
                    "success": False,
                    "sync_type": "single",
                    "target_list": target_list,
                    "message": "Single list sync not yet implemented in core application",
                    "note": "Both direct sync and signal fallback failed. Please use 'Sync All Lists' instead.",
                    "error": str(signal_error),
                    "timestamp": datetime.now().isoformat(),
                }

        except Exception as sync_error:
            logging.exception(f"ERROR - Sync execution failed: {sync_error}")
            import traceback

            traceback.print_exc()

            return {
                "success": False,
                "sync_type": "single",
                "target_list": target_list,
                "message": f"Single list sync failed for {list_type}:{list_id}",
                "error": str(sync_error),
                "timestamp": datetime.now().isoformat(),
            }

        finally:
            # Clean up temp file
            try:
                os.unlink(temp_file_path)
            except OSError as e:
                logging.debug("Failed to clean up temp file %s: %s", temp_file_path, e)

    except Exception as e:
        logging.exception(f"CRITICAL ERROR in single list sync: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Single list sync failed: {e!s}")


@app.post("/api/sync/single")
async def trigger_single_list_sync_endpoint(sync_request: dict):
    """Endpoint for single list sync requests - redirects to main trigger endpoint"""
    # Redirect to the main trigger endpoint with the same payload
    return await trigger_manual_sync(sync_request)


@app.get("/api/sync/status")
async def get_sync_status():
    """Get current sync status and process information"""
    try:
        # Find ListSync processes
        processes = find_listsync_processes()

        process_info = []
        for process in processes:
            try:
                # Get additional process info
                proc = psutil.Process(process.pid)
                process_info.append(
                    {
                        "pid": process.pid,
                        "status": process.status,
                        "created": process.created,
                        "cmdline": process.cmdline,
                        "memory_percent": proc.memory_percent(),
                        "cpu_percent": proc.cpu_percent(),
                        "can_signal": True,  # Assume we can signal unless we find otherwise
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                process_info.append(
                    {
                        "pid": process.pid,
                        "status": "unknown",
                        "created": process.created,
                        "cmdline": process.cmdline,
                        "error": str(e),
                        "can_signal": False,
                    }
                )

        return {
            "processes_found": len(processes),
            "processes": process_info,
            "can_trigger_sync": len(processes) > 0,
            "sync_method": "signal" if len(processes) > 0 else "none",
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logging.exception(f"Error getting sync status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sync/{job_id}/cancel")
async def cancel_sync(job_id: str):
    """Cancel a running sync - first gracefully via cancellation flag, then forcefully if needed"""
    try:
        import asyncio
        import signal
        from datetime import datetime, timedelta

        import psutil

        from list_sync.database import end_sync_in_db, get_current_sync_status, load_sync_interval
        from list_sync.utils.sync_status import (
            clear_cancel_request,
            get_sync_tracker,
            set_cancel_request,
            set_pause_until,
        )

        sync_tracker = get_sync_tracker()

        # Get current sync state from DATABASE (same source as /api/sync/status/live)
        # This ensures cancel endpoint uses the same logic as the live status endpoint
        db_sync_status = get_current_sync_status()
        is_running = db_sync_status and db_sync_status.get("in_progress") == 1

        if not is_running:
            return {
                "success": False,
                "message": "No sync is currently running",
                "job_id": job_id,
                "timestamp": datetime.now().isoformat(),
            }

        # Extract sync info from database
        session_id = db_sync_status.get("session_id")

        # Prefer subprocess PID (actual worker); avoid killing parent to prevent restarts
        tracker_state = sync_tracker.get_state()
        target_pid = tracker_state.get("sync_subprocess_pid")
        if not target_pid:
            # Fallback to DB pid only if tracker not set
            target_pid = db_sync_status.get("pid")

        termination_method = None
        terminated = False

        # Set cross-process cancel flag
        if session_id:
            set_cancel_request(session_id)

        # Resolve target PID; fallback to detected worker processes if needed
        if not target_pid or not psutil.pid_exists(target_pid):
            processes = find_listsync_processes()
            for proc in processes:
                if psutil.pid_exists(proc.pid):
                    target_pid = proc.pid
                    break

        # Always try to send SIGTERM immediately to the running sync process (different process than API)
        if target_pid:
            try:
                import os
                import signal as sig

                os.kill(target_pid, sig.SIGTERM)
                termination_method = "SIGTERM"
                logging.info(f"Sent SIGTERM to sync process PID {target_pid}")
            except Exception as e:
                logging.exception(f"Failed to send SIGTERM to PID {target_pid}: {e}")

            # Poll for exit, escalate if needed
            for i in range(10):  # up to ~5s
                await asyncio.sleep(0.5)
                if not psutil.pid_exists(target_pid):
                    terminated = True
                    break
            if not terminated and hasattr(signal, "SIGKILL"):
                try:
                    os.kill(target_pid, signal.SIGKILL)
                    termination_method = "SIGKILL"
                    logging.warning(f"Sent SIGKILL to sync process PID {target_pid}")
                except Exception as e:
                    logging.exception(f"Failed to send SIGKILL to PID {target_pid}: {e}")
                # Final short wait
                for i in range(6):
                    await asyncio.sleep(0.5)
                    if not psutil.pid_exists(target_pid):
                        terminated = True
                        break
            elif not terminated:
                termination_method = termination_method or "SIGTERM"
        else:
            logging.error("No valid target PID found for cancellation")

        # Mark cancellation in DB only if we have session_id
        if session_id:
            try:
                end_sync_in_db(
                    session_id=session_id,
                    status="cancelled",
                    total_items=db_sync_status.get("total_items", 0) or 0,
                    items_requested=db_sync_status.get("items_requested", 0) or 0,
                    items_skipped=db_sync_status.get("items_skipped", 0) or 0,
                    items_errors=db_sync_status.get("items_errors", 0) or 0,
                    error_message="Cancelled via /cancel endpoint",
                )
                clear_cancel_request(session_id)
                logging.info(f"Marked sync session {session_id} as cancelled in database")
            except Exception as e:
                logging.exception(f"Error updating database for cancelled sync: {e}")

            # Set pause-until based on current interval to avoid immediate restart
            pause_until = None
            try:
                interval_hours = load_sync_interval()
                if interval_hours <= 0:
                    interval_hours = 1  # safe minimum
                pause_until = datetime.utcnow() + timedelta(hours=interval_hours)
                set_pause_until(pause_until.isoformat())
                logging.info(f"⏸️  Pausing automated syncs until {pause_until.isoformat()} after cancellation")
            except Exception as e:
                logging.warning(f"Could not set pause after cancellation: {e}")

        # Clear tracker state locally
        sync_tracker.end_sync()

        return {
            "success": terminated,
            "message": "Sync cancelled" if terminated else "Cancellation requested; process may still be shutting down",
            "job_id": job_id,
            "terminated": terminated,
            "termination_method": termination_method,
            "target_pid": target_pid,
            "session_id": session_id,
            "pause_until": pause_until.isoformat()
            if session_id and "pause_until" in locals() and pause_until
            else None,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logging.exception(f"Error canceling sync: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel sync: {e!s}")


@app.get("/api/failures")
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


@app.get("/api/processed")
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


@app.get("/api/successful")
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


@app.get("/api/requested")
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


# Collections API endpoints
@app.get("/api/collections")
async def get_collections(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: str = Query("", description="Search collections by franchise name"),
    sort: str = Query(
        "total_votes",
        regex="^(popularity|rating|movie_count|name|total_votes)$",
        description="Sort by popularity, rating, movie_count, name, or total_votes",
    ),
):
    """Get all collections with pagination, search, and sorting"""
    try:
        from list_sync.database import load_list_ids
        from list_sync.providers.collections import get_all_collections

        collections = get_all_collections()

        # Get synced collections info
        all_lists = load_list_ids()
        synced_info = {}
        for list_item in all_lists:
            if list_item.get("type") == "collections":
                franchise_name = list_item.get("id")
                synced_info[franchise_name] = {
                    "last_synced": list_item.get("last_synced"),
                    "item_count": list_item.get("item_count", 0),
                }

        # Apply search filter
        if search.strip():
            search_lower = search.strip().lower()
            collections = [c for c in collections if search_lower in c.get("franchise", "").lower()]

        # Apply sorting (default: total_votes for quality content first)
        if sort == "total_votes":
            collections.sort(key=lambda x: x.get("totalVotes", 0), reverse=True)
        elif sort == "popularity":
            collections.sort(key=lambda x: x.get("popularityScore", 0), reverse=True)
        elif sort == "rating":
            collections.sort(key=lambda x: x.get("averageRating", 0), reverse=True)
        elif sort == "movie_count":
            collections.sort(key=lambda x: x.get("totalMovies", 0), reverse=True)
        elif sort == "name":
            collections.sort(key=lambda x: x.get("franchise", "").lower())

        # Calculate pagination
        total = len(collections)
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        start = (page - 1) * limit
        end = start + limit
        page_collections = collections[start:end]

        # Add synced info to each collection
        for collection in page_collections:
            franchise = collection.get("franchise")
            if franchise in synced_info:
                collection["_synced_info"] = synced_info[franchise]
            else:
                collection["_synced_info"] = None

        return {
            "collections": page_collections,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "limit": limit,
        }
    except Exception as e:
        logging.exception(f"Error getting collections: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/collections/random")
async def get_random_collections(
    count: int = Query(5, ge=1, le=20, description="Number of random collections to return"),
):
    """Get random collections from the full database (only collections with 3+ movies) - cached for performance"""
    try:
        import random

        from list_sync.providers.collections import get_all_collections

        # Use cached collections data (already cached in collections.py)
        collections = get_all_collections()

        # Filter to only collections with 3 or more movies (do this once, cache the result)
        if not hasattr(get_random_collections, "_filtered_cache"):
            get_random_collections._filtered_cache = [
                c for c in collections if c and c.get("franchise") and c.get("totalMovies", 0) >= 3
            ]
            logging.info(
                f"Cached {len(get_random_collections._filtered_cache)} collections with 3+ movies for random selection"
            )

        filtered_collections = get_random_collections._filtered_cache

        if len(filtered_collections) == 0:
            logging.warning("No collections with 3+ movies available for random selection")
            return {"collections": []}

        # Get random sample from filtered collections
        if len(filtered_collections) <= count:
            random_collections = filtered_collections
        else:
            random_collections = random.sample(filtered_collections, count)

        # Ensure all collections have required fields
        validated_collections = []
        for collection in random_collections:
            if collection and collection.get("franchise"):
                # Ensure all expected fields exist
                validated_collection = {
                    "franchise": collection.get("franchise"),
                    "totalMovies": collection.get("totalMovies", 0),
                    "totalVotes": collection.get("totalVotes", 0),
                    "averageRating": collection.get("averageRating", 0),
                    "popularityScore": collection.get("popularityScore", 0),
                    "poster_url": None,  # Will be fetched separately
                }
                validated_collections.append(validated_collection)

        return {"collections": validated_collections}
    except Exception as e:
        logging.error(f"Error getting random collections: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/collections/popular")
async def get_popular_collections():
    """Get top 20 collections by total votes (quality content first)"""
    try:
        from list_sync.database import load_list_ids
        from list_sync.providers.collections import get_all_collections

        collections = get_all_collections()

        # Sort by total votes (quality content first) and take top 20
        collections.sort(key=lambda x: x.get("totalVotes", 0), reverse=True)
        top_20 = collections[:20]

        # Get synced collections info
        all_lists = load_list_ids()
        synced_info = {}
        for list_item in all_lists:
            if list_item.get("type") == "collections":
                franchise_name = list_item.get("id")
                synced_info[franchise_name] = {
                    "last_synced": list_item.get("last_synced"),
                    "item_count": list_item.get("item_count", 0),
                }

        # Add synced info to each collection
        for collection in top_20:
            franchise = collection.get("franchise")
            if franchise in synced_info:
                collection["_synced_info"] = synced_info[franchise]
            else:
                collection["_synced_info"] = None

        return {
            "collections": top_20,
        }
    except Exception as e:
        logging.exception(f"Error getting popular collections: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/collections/synced")
async def get_synced_collections_info():
    """Get information about synced collections (franchise name and last_synced timestamp)"""
    try:
        from list_sync.database import load_list_ids

        all_lists = load_list_ids()
        synced_collections = {}

        for list_item in all_lists:
            if list_item.get("type") == "collections":
                franchise_name = list_item.get("id")
                synced_collections[franchise_name] = {
                    "last_synced": list_item.get("last_synced"),
                    "item_count": list_item.get("item_count", 0),
                }

        return {
            "synced_collections": synced_collections,
        }
    except Exception as e:
        logging.exception(f"Error getting synced collections info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/collections/{franchise_name}")
async def get_collection_details(franchise_name: str):
    """Get specific collection details by franchise name"""
    try:
        from urllib.parse import unquote

        from list_sync.providers.collections import get_collection_by_name

        # URL decode the franchise name
        decoded_name = unquote(franchise_name)

        collection = get_collection_by_name(decoded_name)

        if not collection:
            raise HTTPException(status_code=404, detail=f"Collection not found: {decoded_name}")

        return collection
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error getting collection details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/collections/{franchise_name}/movies")
async def get_collection_movies(franchise_name: str):
    """Get movies in a collection with full details"""
    try:
        from urllib.parse import unquote

        from list_sync.providers.collections import get_collection_by_name

        # URL decode the franchise name
        decoded_name = unquote(franchise_name)

        collection = get_collection_by_name(decoded_name)

        if not collection:
            raise HTTPException(status_code=404, detail=f"Collection not found: {decoded_name}")

        # Return full movieRatings data if available, otherwise fallback to basic format
        movies = collection.get("movieRatings", [])

        # If no movieRatings, create basic format from movieIds
        if not movies:
            from list_sync.providers.collections import fetch_collection

            movies = fetch_collection(decoded_name)

        return {
            "franchise": decoded_name,
            "movies": movies,
            "total": len(movies),
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error getting collection movies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/collections/{franchise_name}/poster")
async def get_collection_poster(franchise_name: str):
    """Get poster URL for collection (uses most voted movie's poster from Trakt)"""
    try:
        from urllib.parse import unquote

        from list_sync.providers.collections import get_collection_by_name, get_oldest_movie_id
        from list_sync.providers.trakt import get_trakt_metadata

        # URL decode the franchise name
        decoded_name = unquote(franchise_name)

        collection = get_collection_by_name(decoded_name)

        if not collection:
            raise HTTPException(status_code=404, detail=f"Collection not found: {decoded_name}")

        # Get most voted movie ID (function name kept for compatibility but logic changed)
        oldest_movie_id = get_oldest_movie_id(collection)

        if not oldest_movie_id:
            return {"poster_url": None}

        # Fetch poster from Trakt
        metadata = get_trakt_metadata(tmdb_id=oldest_movie_id, media_type="movie")

        poster_url = metadata.get("poster_url") if metadata else None

        return {
            "poster_url": poster_url,
            "movie_id": oldest_movie_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error getting collection poster: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/collections/posters/batch")
async def get_collection_posters_batch(request: Request):
    """Get poster URLs for multiple collections in parallel (faster than individual requests)"""
    try:
        import asyncio
        from urllib.parse import unquote

        from list_sync.providers.collections import get_collection_by_name, get_oldest_movie_id
        from list_sync.providers.trakt import get_trakt_metadata

        body = await request.json()
        franchise_names = body.get("franchise_names", [])

        if not franchise_names or not isinstance(franchise_names, list):
            raise HTTPException(status_code=400, detail="franchise_names must be a non-empty list")

        if len(franchise_names) > 20:
            raise HTTPException(status_code=400, detail="Maximum 20 franchise names per batch")

        async def fetch_poster(franchise_name: str):
            """Fetch poster for a single collection"""
            try:
                decoded_name = unquote(franchise_name) if "%" in franchise_name else franchise_name
                collection = get_collection_by_name(decoded_name)

                if not collection:
                    return {
                        "franchise": franchise_name,
                        "poster_url": None,
                        "error": "Collection not found",
                    }

                oldest_movie_id = get_oldest_movie_id(collection)

                if not oldest_movie_id:
                    return {
                        "franchise": franchise_name,
                        "poster_url": None,
                        "movie_id": None,
                    }

                # Fetch poster from Trakt (run in thread pool to avoid blocking)
                loop = asyncio.get_event_loop()
                metadata = await loop.run_in_executor(
                    None,
                    lambda: get_trakt_metadata(tmdb_id=oldest_movie_id, media_type="movie"),
                )

                poster_url = metadata.get("poster_url") if metadata else None

                return {
                    "franchise": franchise_name,
                    "poster_url": poster_url,
                    "movie_id": oldest_movie_id,
                }
            except Exception as e:
                logging.warning(f"Error fetching poster for {franchise_name}: {e}")
                return {
                    "franchise": franchise_name,
                    "poster_url": None,
                    "error": str(e),
                }

        # Fetch all posters in parallel
        results = await asyncio.gather(*[fetch_poster(name) for name in franchise_names])

        return {
            "posters": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting batch collection posters: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/media/request")
async def request_single_media(request: Request):
    """Request a single media item to Seerr (one-time sync, not a list)"""
    try:
        from list_sync.api.seerr import SeerrClient
        from list_sync.config import load_env_config

        body = await request.json()
        tmdb_id = body.get("tmdb_id")
        media_type = body.get("media_type", "movie")
        is_4k = body.get("is_4k", False)

        if not tmdb_id:
            raise HTTPException(status_code=400, detail="tmdb_id is required")

        if media_type not in ["movie", "tv"]:
            raise HTTPException(status_code=400, detail="media_type must be 'movie' or 'tv'")

        # Ensure tmdb_id is an integer
        try:
            tmdb_id = int(tmdb_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="tmdb_id must be a valid integer")

        # Get environment configuration
        config_tuple = load_env_config()
        if not config_tuple or not config_tuple[0] or not config_tuple[1]:
            raise HTTPException(status_code=400, detail="Seerr not configured")

        seerr_url, api_key, requester_user_id = config_tuple[0], config_tuple[1], config_tuple[2] or "1"
        is_4k_config = config_tuple[5] if len(config_tuple) > 5 else False

        # Use config 4K setting if not explicitly provided
        if is_4k is None:
            is_4k = is_4k_config

        # Create Seerr client
        seerr_client = SeerrClient(seerr_url, api_key, requester_user_id)

        # Get media by TMDB ID to get Seerr ID
        media_data = seerr_client.get_media_by_tmdb_id(tmdb_id, media_type)

        if not media_data:
            return {
                "success": False,
                "status": "not_found",
                "message": f"Media with TMDB ID {tmdb_id} not found in Seerr",
            }

        overseerr_id = media_data.get("id")
        if not overseerr_id:
            return {
                "success": False,
                "status": "error",
                "message": "Could not determine Seerr ID",
            }

        # Check current status
        is_available, is_requested, _ = seerr_client.get_media_status(overseerr_id, media_type)

        if is_requested:
            return {
                "success": True,
                "status": "already_requested",
                "message": "Media is already requested in Seerr",
                "overseerr_id": overseerr_id,
            }

        if is_available:
            return {
                "success": True,
                "status": "already_available",
                "message": "Media is already available in Seerr",
                "overseerr_id": overseerr_id,
            }

        # Request the media
        request_status = seerr_client.request_media(overseerr_id, media_type, is_4k, requester_user_id=None)

        if request_status == "success":
            return {
                "success": True,
                "status": "requested",
                "message": "Media successfully requested in Seerr",
                "overseerr_id": overseerr_id,
            }
        if request_status == "already_requested":
            return {
                "success": True,
                "status": "already_requested",
                "message": "Media is already requested in Seerr",
                "overseerr_id": overseerr_id,
            }
        return {
            "success": False,
            "status": "error",
            "message": f"Failed to request media: {request_status}",
            "overseerr_id": overseerr_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error requesting single media: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _run_collection_sync_in_subprocess(
    list_type: str,
    list_id: str,
    seerr_url: str,
    seerr_api_key: str,
    user_id: str,
    is_4k: bool,
    result_queue: multiprocessing.Queue,
):
    """
    Worker function to run collection sync in a subprocess.
    This function is called by multiprocessing.Process.
    """
    try:
        # Import inside subprocess to avoid issues
        from list_sync.main import sync_single_list
        from list_sync.utils.sync_status import get_sync_tracker

        # Set the subprocess PID in the tracker
        sync_tracker = get_sync_tracker()
        sync_tracker.set_subprocess_pid(os.getpid())

        result = sync_single_list(
            list_type,
            list_id,
            seerr_url,
            seerr_api_key,
            user_id,
            is_4k,
            False,  # dry_run
        )
        result_queue.put({"success": True, "result": result})
    except Exception as e:
        result_queue.put({"success": False, "error": str(e)})


@app.post("/api/collections/{franchise_name}/sync")
async def sync_collection(franchise_name: str):
    """Sync a collection to Seerr using a terminable subprocess"""
    try:
        from urllib.parse import unquote

        from list_sync.config import load_env_config
        from list_sync.utils.sync_status import get_sync_tracker

        # URL decode the franchise name
        decoded_name = unquote(franchise_name)

        # Get environment configuration
        config_tuple = load_env_config()
        if not config_tuple or not config_tuple[0] or not config_tuple[1]:
            raise HTTPException(status_code=400, detail="Seerr not configured")

        seerr_url, api_key, requester_user_id = config_tuple[0], config_tuple[1], config_tuple[2] or "1"
        is_4k = config_tuple[5] if len(config_tuple) > 5 else False

        # Create a queue to receive results from subprocess
        result_queue = multiprocessing.Queue()

        # Create and start subprocess for immediate termination support
        sync_process = multiprocessing.Process(
            target=_run_collection_sync_in_subprocess,
            args=("collections", decoded_name, seerr_url, api_key, requester_user_id, is_4k, result_queue),
        )
        sync_process.start()
        subprocess_pid = sync_process.pid

        logging.info(f"Collection sync subprocess started with PID {subprocess_pid}")

        # Register the subprocess PID in the tracker for immediate cancellation
        sync_tracker = get_sync_tracker()
        sync_tracker.set_subprocess_pid(subprocess_pid)

        # Wait for the subprocess with polling to allow for cancellation
        timeout_seconds = 3600  # 1 hour timeout
        poll_interval = 0.5
        elapsed = 0

        while sync_process.is_alive() and elapsed < timeout_seconds:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            # Check if cancellation was requested
            if sync_tracker.is_cancellation_requested():
                logging.info(f"Cancellation requested, terminating collection sync subprocess {subprocess_pid}")
                sync_process.terminate()
                sync_process.join(timeout=2)
                if sync_process.is_alive():
                    sync_process.kill()
                sync_tracker.end_sync()
                return {
                    "success": False,
                    "franchise": decoded_name,
                    "message": "Collection sync cancelled by user",
                    "cancelled": True,
                }

        # Check if process timed out
        if sync_process.is_alive():
            logging.error(f"Collection sync timed out after {timeout_seconds} seconds")
            sync_process.terminate()
            sync_process.join(timeout=2)
            if sync_process.is_alive():
                sync_process.kill()
            sync_tracker.end_sync()
            raise HTTPException(status_code=500, detail="Collection sync timed out")

        # Get result from queue
        try:
            result_data = result_queue.get_nowait()
            if result_data.get("success"):
                result = result_data.get("result", {})
                if result.get("success", False):
                    return {
                        "success": True,
                        "franchise": decoded_name,
                        "items_processed": result.get("items_processed", 0),
                        "items_requested": result.get("items_requested", 0),
                        "items_already_available": result.get("items_already_available", 0),
                        "items_already_requested": result.get("items_already_requested", 0),
                        "items_skipped": result.get("items_skipped", 0),
                        "items_not_found": result.get("items_not_found", 0),
                        "errors": result.get("errors", 0),
                        "message": result.get("message", "Collection synced successfully"),
                    }
                raise HTTPException(
                    status_code=500,
                    detail=result.get("message", "Collection sync failed"),
                )
            raise HTTPException(status_code=500, detail=result_data.get("error", "Collection sync failed"))
        except HTTPException:
            raise
        except Exception as queue_error:
            logging.warning(f"Could not get result from queue: {queue_error}")
            exit_code = sync_process.exitcode
            if exit_code == 0:
                return {
                    "success": True,
                    "franchise": decoded_name,
                    "message": "Collection synced",
                }
            raise HTTPException(status_code=500, detail=f"Collection sync process exited with code {exit_code}")

    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error syncing collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/timezone/supported")
async def get_supported_timezones():
    """Get list of all supported timezone abbreviations organized by region"""
    try:
        abbreviations = list_supported_abbreviations()
        return {
            "success": True,
            "regions": abbreviations,
            "total_abbreviations": sum(len(abbrevs) for abbrevs in abbreviations.values()),
            "note": "Use these abbreviations in the TZ environment variable",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/timezone/current")
async def get_current_timezone():
    """Get detailed information about the current timezone"""
    try:
        tz_info = get_current_timezone_info()
        return {
            "success": True,
            "timezone": tz_info,
            "environment_tz": os.getenv("TZ", "Not set"),
            "system_supports_abbreviations": True,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/timezone/validate")
async def validate_timezone(timezone_input: dict):
    """Validate a timezone input and return the normalized timezone name"""
    try:
        tz_input = timezone_input.get("timezone", "")
        region_hint = timezone_input.get("region_hint")

        if not tz_input:
            raise HTTPException(status_code=400, detail="Timezone input is required")

        try:
            normalized_tz = normalize_timezone_input(tz_input, region_hint)
            return {
                "success": True,
                "input": tz_input,
                "normalized": normalized_tz,
                "region_hint": region_hint,
                "valid": True,
            }
        except ValueError as e:
            return {
                "success": False,
                "input": tz_input,
                "normalized": None,
                "region_hint": region_hint,
                "valid": False,
                "error": str(e),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Add these new API endpoints before the main execution block


@app.get("/api/logs/entries")
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


@app.get("/api/logs/stream")
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


@app.get("/api/logs/categories")
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


@app.get("/api/logs/stats")
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


# Analytics processing functions
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


@app.get("/api/analytics")
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


@app.get("/api/analytics/overview")
async def get_analytics_overview(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get analytics overview data"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.overview
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating overview: {e!s}")


@app.get("/api/analytics/media-additions")
async def get_media_additions(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get media addition analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.media_additions
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating media additions: {e!s}")


@app.get("/api/analytics/list-fetches")
async def get_list_fetches(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get list fetch analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.list_fetches
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating list fetches: {e!s}")


@app.get("/api/analytics/matching")
async def get_matching_analytics(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get matching accuracy analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.matching
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating matching analytics: {e!s}")


@app.get("/api/analytics/search-failures")
async def get_search_failures(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get search failure analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.search_failures
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating search failures: {e!s}")


@app.get("/api/analytics/scraping-performance")
async def get_scraping_performance(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get scraping performance analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.scraping_performance
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating scraping performance: {e!s}")


@app.get("/api/analytics/source-distribution")
async def get_source_distribution(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get source distribution analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.source_distribution
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating source distribution: {e!s}")


@app.get("/api/analytics/selector-performance")
async def get_selector_performance(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get selector performance analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.selector_performance
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating selector performance: {e!s}")


@app.get("/api/analytics/genre-distribution")
async def get_genre_distribution(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get genre distribution analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.genre_distribution
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating genre distribution: {e!s}")


@app.get("/api/analytics/year-distribution")
async def get_year_distribution(time_range: str = Query("24h", regex="^(1h|24h|7d|30d)$")):
    """Get year distribution analytics"""
    try:
        analytics_data = process_analytics_data(time_range)
        return analytics_data.year_distribution
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating year distribution: {e!s}")


@app.get("/api/recent-activity")
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


@app.get("/api/sync/status/live")
async def get_live_sync_status():
    """Get real-time sync status by checking database"""
    try:
        # Import database function
        from list_sync.database import get_current_sync_status
        from list_sync.utils.sync_status import parse_db_timestamp

        # Get current sync status from database. Records left behind by a sync
        # that died mid-run are closed out by this call, so a crashed sync can
        # never leave the dashboard stuck on "Sync in Progress".
        sync_status = get_current_sync_status()

        if sync_status and sync_status.get("in_progress") == 1:
            # Sync is currently running
            sync_type = sync_status.get("sync_type", "unknown")
            status = f"running_{sync_type}" if sync_type != "unknown" else "running"

            # Calculate duration if start time is available. Database timestamps
            # are UTC, so they are compared against UTC rather than local time.
            duration = None
            start_time_str = sync_status.get("start_time")
            start_time = parse_db_timestamp(start_time_str)
            if start_time:
                duration = int((datetime.now(UTC) - start_time).total_seconds())
            elif start_time_str:
                logging.warning(f"Could not parse sync start_time: {start_time_str!r}")

            return {
                "is_running": True,
                "status": status,
                "sync_type": sync_type,
                "session_id": sync_status.get("session_id"),
                "start_time": start_time_str,
                "duration_seconds": duration,
                "list_type": sync_status.get("list_type"),
                "list_id": sync_status.get("list_id"),
                "pid": sync_status.get("pid"),
                "timestamp": datetime.now().isoformat(),
            }
        # Sync is idle (no sync in progress)
        return {
            "is_running": False,
            "status": "idle",
            "sync_type": None,
            "session_id": None,
            "start_time": None,
            "duration_seconds": None,
            "list_type": None,
            "list_id": None,
            "pid": None,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logging.exception(f"Error getting live sync status: {e}")
        import traceback

        traceback.print_exc()
        return {
            "is_running": False,
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


@app.get("/api/overseerr/config")
async def get_overseerr_config():
    """Get Seerr configuration for frontend use"""
    try:
        # Load environment configuration - returns a tuple
        config_tuple = load_env_config()
        seerr_url, seerr_api_key, user_id, sync_interval, automated_mode, is_4k = config_tuple

        if not seerr_url:
            return {
                "configured": False,
                "base_url": None,
                "error": "Seerr URL not configured",
            }

        # Clean URL and return base URL for frontend
        base_url = seerr_url.rstrip("/")

        return {
            "configured": True,
            "base_url": base_url,
            "user_id": user_id,
        }
    except Exception as e:
        return {
            "configured": False,
            "base_url": None,
            "error": f"Configuration error: {e!s}",
        }


@app.get("/api/settings/config")
async def get_settings():
    """Get all application settings for the settings page (reads from database or .env)"""
    try:
        from list_sync import encryption
        from list_sync.config import ConfigManager

        config = ConfigManager()

        # Helper to get and optionally mask sensitive values
        def get_setting_safe(key, default="", mask=False):
            value = config.get_setting(key, default)
            if mask and value:
                return encryption.mask_sensitive_value(str(value))
            return value

        # Get all settings (database or env fallback)
        seerr_url = get_setting_safe("overseerr_url", "")
        seerr_api_key = get_setting_safe("overseerr_api_key", "", mask=True)
        user_id = get_setting_safe("overseerr_user_id", "1")
        is_4k = get_setting_safe("overseerr_4k", False)

        trakt_client_id = get_setting_safe("trakt_client_id", "", mask=True)

        sync_interval = get_setting_safe("sync_interval", 24)
        try:
            sync_interval = int(sync_interval)
        except (ValueError, TypeError):
            sync_interval = 24  # best-effort; invalid value ignored

        automated_mode = get_setting_safe("auto_sync", True)
        if isinstance(automated_mode, str):
            automated_mode = automated_mode.lower() in ("true", "1", "yes")

        timezone = get_setting_safe("timezone", "UTC")

        discord_webhook = get_setting_safe("discord_webhook", "", mask=True)
        discord_enabled = get_setting_safe("discord_enabled", False)
        if isinstance(discord_enabled, str):
            discord_enabled = discord_enabled.lower() in ("true", "1", "yes")

        gotify_url = get_setting_safe("gotify_url", "")
        gotify_token = get_setting_safe("gotify_token", "", mask=True)
        gotify_enabled = get_setting_safe("gotify_enabled", False)
        if isinstance(gotify_enabled, str):
            gotify_enabled = gotify_enabled.lower() in ("true", "1", "yes")

        frontend_domain = get_setting_safe("frontend_domain", "http://localhost:3222")
        backend_domain = get_setting_safe("backend_domain", "http://localhost:4222")
        nuxt_public_api_url = get_setting_safe("nuxt_public_api_url", "http://localhost:4222")

        imdb_lists = get_setting_safe("imdb_lists", "")
        trakt_lists = get_setting_safe("trakt_lists", "")
        trakt_special_lists = get_setting_safe("trakt_special_lists", "")

        trakt_special_items_limit = get_setting_safe("trakt_special_items_limit", 20)
        try:
            trakt_special_items_limit = int(trakt_special_items_limit)
        except (ValueError, TypeError):
            trakt_special_items_limit = 20  # best-effort; invalid value ignored

        letterboxd_lists = get_setting_safe("letterboxd_lists", "")
        anilist_lists = get_setting_safe("anilist_lists", "")
        mdblist_lists = get_setting_safe("mdblist_lists", "")
        stevenlu_lists = get_setting_safe("stevenlu_lists", "")
        tmdb_key = get_setting_safe("tmdb_key", "", mask=True)
        tmdb_lists = get_setting_safe("tmdb_lists", "")
        tvdb_lists = get_setting_safe("tvdb_lists", "")
        simkl_lists = get_setting_safe("simkl_lists", "")

        return {
            # Seerr Configuration
            "overseerr_url": seerr_url or "",
            "overseerr_api_key": seerr_api_key or "",
            "overseerr_user_id": user_id or "1",
            "overseerr_4k": is_4k,
            # Sync Settings
            "sync_interval": sync_interval,
            "auto_sync": automated_mode,
            "timezone": timezone,
            # Notifications
            "discord_webhook": discord_webhook,
            "discord_enabled": bool(discord_webhook),
            "gotify_url": gotify_url or "",
            "gotify_token": gotify_token or "",
            "gotify_enabled": bool(gotify_url),
            # Trakt API
            "trakt_client_id": trakt_client_id,
            # Service Endpoints
            "frontend_domain": frontend_domain,
            "backend_domain": backend_domain,
            "nuxt_public_api_url": nuxt_public_api_url,
            # Content Sources
            "imdb_lists": imdb_lists,
            "trakt_lists": trakt_lists,
            "trakt_special_lists": trakt_special_lists,
            "trakt_special_items_limit": trakt_special_items_limit,
            "letterboxd_lists": letterboxd_lists,
            "anilist_lists": anilist_lists,
            "mdblist_lists": mdblist_lists,
            "stevenlu_lists": stevenlu_lists,
            "tmdb_key": tmdb_key,
            "tmdb_lists": tmdb_lists,
            "tvdb_lists": tvdb_lists,
            "simkl_lists": simkl_lists,
        }
    except Exception as e:
        logging.exception(f"Error loading settings: {e}")
        return {
            # Seerr Configuration
            "overseerr_url": "",
            "overseerr_api_key": "",
            "overseerr_user_id": "1",
            "overseerr_4k": False,
            # Sync Settings
            "sync_interval": 24,
            "auto_sync": True,
            "timezone": "UTC",
            # Notifications
            "discord_webhook": "",
            "discord_enabled": False,
            "gotify_url": "",
            "gotify_token": "",
            "gotify_enabled": False,
            # Trakt API
            "trakt_client_id": "",
            # Service Endpoints
            "frontend_domain": "http://localhost:3222",
            "backend_domain": "http://localhost:4222",
            "nuxt_public_api_url": "http://localhost:4222",
            # Content Sources
            "imdb_lists": "",
            "trakt_lists": "",
            "trakt_special_lists": "",
            "trakt_special_items_limit": 20,
            "letterboxd_lists": "",
            "anilist_lists": "",
            "mdblist_lists": "",
            "stevenlu_lists": "",
            "tmdb_key": "",
            "tmdb_lists": "",
            "tvdb_lists": "",
            "simkl_lists": "",
        }


@app.post("/api/settings/config")
async def update_settings(settings: dict):
    """
    Update application settings - saves to database with encryption for sensitive fields.
    Changes take effect immediately (no restart required).

    Note: Masked values (****...) from sensitive fields are automatically detected
    and skipped to preserve existing encrypted values in the database.
    """
    try:
        from list_sync.config import ConfigManager, is_masked_value
        from list_sync.encryption import should_encrypt
        from list_sync.utils.settings_validation import validate_settings

        config = ConfigManager()

        logging.info(f"Saving {len(settings)} settings to database")

        # Several of these settings name something the server later requests, so
        # they get the same checks the setup wizard applies. Without them this
        # endpoint is a way to store exactly what the wizard refuses.
        #
        # A masked placeholder means "leave this one alone" - save_setting skips
        # it below, so validating it would reject the mask rather than the value
        # actually in the database.
        changing = {
            key: value for key, value in settings.items() if not (should_encrypt(key) and is_masked_value(str(value)))
        }
        errors = validate_settings(changing)
        if errors:
            logging.warning(f"Rejected settings update: {errors}")
            raise HTTPException(
                status_code=400,
                detail={"message": "Some settings were rejected", "errors": errors},
            )

        # Save all settings to database
        # The save_setting method will automatically skip masked placeholders
        # for sensitive fields to prevent overwriting real API keys
        for key, value in settings.items():
            config.save_setting(key, value)

        # Also update sync_interval table for compatibility
        if "sync_interval" in settings:
            try:
                interval = int(settings["sync_interval"])
                configure_sync_interval(interval)
            except (ValueError, TypeError, DatabaseError) as e:
                logging.debug("Failed to configure sync interval: %s", e)

        logging.info(f"Settings update complete: {len(settings)} fields processed")

        return {
            "success": True,
            "message": "Settings saved successfully to database. Changes are active immediately!",
            "settings_updated": len(settings),
        }
    except HTTPException:
        # A rejected setting is a deliberate 400, not a server fault.
        raise
    except Exception as e:
        logging.exception(f"Error updating settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/notifications/test")
async def test_notification(payload: dict = None):
    """Send a test notification to verify webhook configuration (Discord or Gotify)"""
    try:
        payload = payload or {}
        service = str(payload.get("service") or "discord").lower()

        if service == "gotify":
            url = (payload.get("url") or os.getenv("GOTIFY_URL", "")).strip()
            token = (payload.get("token") or os.getenv("GOTIFY_TOKEN", "")).strip()

            if not url:
                raise HTTPException(
                    status_code=400,
                    detail="Gotify URL is required. Please provide a URL or set GOTIFY_URL in your environment variables.",
                )
            if not token:
                raise HTTPException(
                    status_code=400,
                    detail="Gotify token is required. Please provide a token or set GOTIFY_TOKEN in your environment variables.",
                )

            # The URL arrives from the caller and the server then requests it, so
            # anything other than a valid Gotify server URL turns this endpoint
            # into an open request proxy. Validate before requesting.
            from list_sync.utils.settings_validation import validate_gotify_url

            gotify_error = validate_gotify_url(url)
            if gotify_error:
                logging.warning(f"Blocked Gotify test: {gotify_error}")
                raise HTTPException(status_code=400, detail=gotify_error)

            from datetime import datetime

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                response = requests.post(
                    f"{url.rstrip('/')}/message",
                    params={"token": token},
                    json={
                        "title": "🧪 Gotify Integration Test",
                        "message": "If you see this message, Gotify notifications are working correctly! ✅",
                        "priority": 0,
                    },
                    timeout=10,
                )
                response.raise_for_status()
                return {
                    "success": True,
                    "message": "Test notification sent successfully! Check your Gotify server.",
                    "timestamp": current_time,
                }
            except requests.exceptions.Timeout:
                raise HTTPException(status_code=504, detail="Gotify request timed out")
            except requests.exceptions.RequestException as e:
                error_msg = f"Failed to send Gotify notification: {e!s}"
                if hasattr(e, "response") and e.response is not None:
                    error_msg += f" (Status: {e.response.status_code})"
                raise HTTPException(status_code=500, detail=error_msg)

        # Get Discord webhook URL from request body or environment
        webhook_url = None
        if payload and "webhook_url" in payload:
            webhook_url = payload["webhook_url"]

        if not webhook_url:
            webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")

        if not webhook_url:
            raise HTTPException(
                status_code=400,
                detail="Discord webhook URL is required. Please provide a webhook URL or set DISCORD_WEBHOOK_URL in your environment variables.",
            )

        # The URL arrives from the caller and the server then requests it, so
        # anything other than a real Discord webhook host turns this endpoint
        # into an open request proxy. Discord webhooks only live on Discord.
        from list_sync.utils.settings_validation import validate_discord_webhook

        webhook_error = validate_discord_webhook(webhook_url)
        if webhook_error:
            logging.warning(f"Blocked Discord webhook test: {webhook_error}")
            raise HTTPException(status_code=400, detail=webhook_error)

        # Try to use the discord-webhook library if available
        try:
            from datetime import datetime

            from discord_webhook import DiscordEmbed, DiscordWebhook

            # Create webhook instance - explicitly set content to None to avoid duplicate messages
            webhook = DiscordWebhook(url=webhook_url, username="ListSync Test", content=None)

            # Create embed with test message
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            embed = DiscordEmbed(
                title="🧪 Discord Integration Test",
                description="If you see this message, Discord notifications are working correctly! ✅",
                color=10181046,  # Purple color
            )

            embed.add_embed_field(
                name="Test Time",
                value=current_time,
                inline=True,
            )

            embed.add_embed_field(
                name="Status",
                value="✅ Connected",
                inline=True,
            )

            embed.set_footer(text="ListSync Notification System")
            embed.set_timestamp()

            # Add embed to webhook (only embed, no content)
            webhook.add_embed(embed)

            # Send webhook
            response = webhook.execute()

            return {
                "success": True,
                "message": "Test notification sent successfully! Check your Discord channel.",
                "timestamp": current_time,
            }

        except ImportError:
            # Fallback to using requests directly
            from datetime import datetime

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Only send embed, no content to avoid duplicate messages
            payload = {
                "embeds": [
                    {
                        "title": "🧪 Discord Integration Test",
                        "description": "If you see this message, Discord notifications are working correctly! ✅",
                        "color": 10181046,
                        "fields": [
                            {
                                "name": "Test Time",
                                "value": current_time,
                                "inline": True,
                            },
                            {
                                "name": "Status",
                                "value": "✅ Connected",
                                "inline": True,
                            },
                        ],
                        "footer": {
                            "text": "ListSync Notification System",
                        },
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                ],
            }

            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()

            return {
                "success": True,
                "message": "Test notification sent successfully! Check your Discord channel.",
                "timestamp": current_time,
            }

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Discord webhook request timed out")
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to send Discord notification: {e!s}"
        if hasattr(e, "response") and e.response is not None:
            error_msg += f" (Status: {e.response.status_code})"
        raise HTTPException(status_code=500, detail=error_msg)
    except HTTPException:
        # A rejected webhook URL is a deliberate 400, not a server fault.
        raise
    except Exception as e:
        import traceback

        error_detail = f"Failed to send test notification: {e!s}\n{traceback.format_exc()}"
        logging.exception(error_detail)
        raise HTTPException(status_code=500, detail=f"Failed to send test notification: {e!s}")


@app.get("/api/sync-history")
async def get_sync_history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    type: str | None = Query(None, regex="^(full|single)$"),
    start_date: str | None = None,
    end_date: str | None = None,
):
    """
    Get list of sync sessions with filtering and pagination.

    Parameters:
    - limit: Maximum number of sessions to return (1-100, default 50)
    - offset: Pagination offset (default 0)
    - type: Filter by sync type ('full' or 'single')
    - start_date: Filter sessions after this date (ISO format)
    - end_date: Filter sessions before this date (ISO format)
    """
    try:
        sessions = get_sync_sessions(sync_type=type)["sessions"]

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                sessions = [s for s in sessions if datetime.fromisoformat(s["start_timestamp"]) >= start_dt]
            except (ValueError, TypeError) as e:
                logging.debug("Invalid start_date filter %s: %s", start_date, e)

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
                sessions = [s for s in sessions if datetime.fromisoformat(s["start_timestamp"]) <= end_dt]
            except (ValueError, TypeError) as e:
                logging.debug("Invalid end_date filter %s: %s", end_date, e)

        def is_valid_session(session):
            has_lists = bool(session.get("lists"))
            has_items = bool(session.get("items"))
            has_results = any(session.get("results", {}).values())
            return has_lists or has_items or has_results

        sessions = [s for s in sessions if is_valid_session(s)]
        sessions.sort(key=lambda x: x.get("start_timestamp") or "", reverse=True)

        total = len(sessions)
        sessions = sessions[offset : offset + limit]

        return {
            "sessions": sessions,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logging.exception(f"Error loading sync history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sync-history/stats")
async def get_sync_history_stats():
    """Get aggregate statistics about sync history."""
    try:
        return query_sync_history_stats()
    except Exception as e:
        logging.exception(f"Error loading sync history stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sync-history/{session_id}")
async def get_sync_session(session_id: str):
    """Get detailed information about a specific sync session."""
    session = get_sync_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.get("/api/logs/live")
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


@app.get("/api/logs/backend")
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


@app.get("/api/logs/rotation-info")
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


@app.get("/api/logs/rotate")
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


@app.get("/api/sync-history/{session_id}/raw-logs")
async def get_sync_session_raw_logs(session_id: str):
    """Get raw log lines for a specific sync session using the live-tail reader."""
    session = get_sync_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    start_timestamp = session.get("start_timestamp")
    end_timestamp = session.get("end_timestamp")
    try:
        start_time = datetime.fromisoformat(start_timestamp) if start_timestamp else None
        end_time = datetime.fromisoformat(end_timestamp) if end_timestamp else None
    except (ValueError, TypeError):
        start_time = end_time = None

    response = get_log_entries(limit=1000000, offset=0, sort_order="asc")
    session_lines = []
    for entry in response.entries:
        try:
            line_time = datetime.fromisoformat(entry.timestamp)
        except (ValueError, TypeError):
            continue
        if start_time and line_time < start_time:
            continue
        if end_time and line_time > end_time:
            continue
        session_lines.append(entry.raw_line)

    return {
        "session_id": session_id,
        "lines": session_lines,
        "line_count": len(session_lines),
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
    }


# ============================================================================
# Image Caching and Proxy Endpoints - Trakt API Compliance
# ============================================================================

# Magic bytes for the formats posters actually arrive in. Names match what
# imghdr.what() returned, because the caller interpolates the result straight
# into an image/{type} media type.
_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
)


def sniff_image_type(data: bytes):
    """
    Identify an image format from its leading bytes.

    Replaces imghdr.what(), which was removed from the standard library in
    Python 3.13. Returns the same lowercase format names, and None when the
    data isn't a format we recognise, so the caller's Content-Type fallback
    still runs.

    Args:
        data (bytes): The start of the image file

    Returns:
        Optional[str]: Format name such as 'jpeg', or None if unrecognised
    """
    if not data:
        return None

    # WebP is a RIFF container, so the marker is not at the start.
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"

    for signature, name in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return name

    return None


@app.get("/api/images/proxy")
async def proxy_image(url: str = Query(..., description="Image URL to proxy/cache")):
    """
    Proxy and cache images from external sources (Trakt, TMDB, etc.).
    This ensures compliance with Trakt's image caching requirements.
    Images are stored in data/images/ folder and served from filesystem.

    FLOW:
    1. Check if image is cached in database
    2. If cached, verify file exists and serve from filesystem
    3. If not cached or file missing:
       - Download from original URL (Trakt, TMDB, etc.)
       - Save to data/images/ with hash-based filename
       - Store metadata in database
       - Serve from filesystem
    4. All subsequent requests serve from local cache (NO HOTLINKING)

    Args:
        url: The original image URL to proxy

    Returns:
        The cached image file with proper headers
    """
    import os

    import requests

    from list_sync.database import get_cached_image, save_cached_image

    try:
        # This endpoint fetches a caller-supplied URL and returns the body, so
        # without a check it is a read primitive against anything the server
        # can reach. Posters come from public CDNs, so private and reserved
        # addresses are refused outright.
        from list_sync.utils.url_safety import validate_outbound_url

        allowed, reason = validate_outbound_url(url, allow_private=False)
        if not allowed:
            logging.warning(f"Blocked image proxy request: {reason}")
            raise HTTPException(status_code=400, detail=f"Invalid image URL: {reason}")

        # Check if we have this image cached
        cached = get_cached_image(url)
        if cached:
            local_path = cached.get("local_path")

            # Verify file exists
            if local_path and os.path.exists(local_path):
                # Serve file from filesystem (NO HOTLINKING - Trakt API compliant)
                logging.debug(f"Serving cached image from: {local_path}")

                # Generate ETag from file modification time for efficient caching
                try:
                    mtime = os.path.getmtime(local_path)
                    etag = f'W/"{int(mtime)}"'
                    last_modified = datetime.fromtimestamp(mtime).strftime("%a, %d %b %Y %H:%M:%S GMT")
                except OSError as e:
                    logging.debug("Failed to get file mtime for %s: %s", local_path, e)
                    etag = None
                    last_modified = None

                headers = {
                    "Cache-Control": "public, max-age=31536000, immutable",  # 1 year - aggressive caching
                    "X-Image-Source": cached.get("source", "unknown"),
                    "X-Image-Cached": "true",
                }

                if etag:
                    headers["ETag"] = etag
                if last_modified:
                    headers["Last-Modified"] = last_modified

                return FileResponse(
                    local_path,
                    media_type=cached.get("mime_type") or "image/webp",
                    headers=headers,
                )
            # File missing but DB record exists - log and re-download
            logging.warning(f"Cached image file missing, re-downloading: {url}")

        # Download the image from original source (Trakt, TMDB, etc.).
        # Redirects are not followed: a permitted public URL is free to answer
        # with a 302 to a private address, which would defeat the check above.
        logging.info(f"Downloading image from source: {url}")
        response = requests.get(
            url,
            timeout=30,
            allow_redirects=False,
            headers={
                "User-Agent": "ListSync/1.0.0",
            },
        )

        if response.status_code in (301, 302, 303, 307, 308):
            redirect_target = response.headers.get("Location", "")
            allowed, reason = validate_outbound_url(redirect_target, allow_private=False)
            if not allowed:
                logging.warning(f"Blocked image proxy redirect to {redirect_target}: {reason}")
                raise HTTPException(status_code=400, detail=f"Unsafe redirect: {reason}")
            logging.info(f"Following image redirect to: {redirect_target}")
            response = requests.get(
                redirect_target,
                timeout=30,
                allow_redirects=False,
                headers={
                    "User-Agent": "ListSync/1.0.0",
                },
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to fetch image: {response.status_code}",
            )

        image_data = response.content

        # Validate image data
        if not image_data or len(image_data) == 0:
            raise HTTPException(status_code=500, detail="Empty image data received")

        # Enforce reasonable file size limit (10MB)
        max_size = 10 * 1024 * 1024  # 10MB
        if len(image_data) > max_size:
            logging.warning(f"Image too large ({len(image_data)} bytes), skipping cache: {url}")
            # Serve directly without caching
            return Response(
                content=image_data,
                media_type="image/webp",
                headers={"Cache-Control": "no-cache"},
            )

        # Detect image type from actual data (most reliable method)
        image_type = sniff_image_type(image_data)
        if not image_type:
            # Fallback: try to detect from URL or Content-Type header
            content_type = response.headers.get("Content-Type", "")
            if "webp" in content_type:
                image_type = "webp"
            elif "jpeg" in content_type or "jpg" in content_type:
                image_type = "jpeg"
            elif "png" in content_type:
                image_type = "png"
            else:
                image_type = "webp"  # Default to webp for Trakt images

        mime_type = f"image/{image_type}"

        # Determine source from URL
        if "trakt.tv" in url or "walter" in url:
            source = "trakt"
        elif "tmdb.org" in url or "themoviedb.org" in url:
            source = "tmdb"
        else:
            source = "unknown"

        # Save to cache (saves to data/images/ filesystem and updates database)
        logging.info(f"Saving {len(image_data)} bytes to cache as {image_type}")
        image_id = save_cached_image(url, image_data, mime_type, source)

        # Get the saved image record to get local_path
        cached = get_cached_image(url)
        if cached and cached.get("local_path"):
            local_path = cached["local_path"]

            # Serve the newly saved file
            # Generate ETag for newly saved file
            try:
                mtime = os.path.getmtime(local_path)
                etag = f'W/"{int(mtime)}"'
                last_modified = datetime.fromtimestamp(mtime).strftime("%a, %d %b %Y %H:%M:%S GMT")
            except OSError as e:
                logging.debug("Failed to get file mtime for %s: %s", local_path, e)
                etag = None
                last_modified = None

            headers = {
                "Cache-Control": "public, max-age=31536000, immutable",  # 1 year - aggressive caching
                "X-Image-Source": source,
                "X-Image-Cached": "false",  # First time, so newly cached
            }

            if etag:
                headers["ETag"] = etag
            if last_modified:
                headers["Last-Modified"] = last_modified

            return FileResponse(
                local_path,
                media_type=mime_type,
                headers=headers,
            )
        # Fallback: serve from memory if file save failed
        logging.warning(f"Failed to get local_path after save, serving from memory: {url}")
        return Response(
            content=image_data,
            media_type=mime_type,
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-Image-Source": source,
                "X-Image-Cached": "false",
            },
        )

    except HTTPException:
        # A rejected URL is a deliberate 400, not a server fault - let it through
        # rather than have the catch-all below turn it into a 500.
        raise
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching image {url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch image: {e!s}")
    except Exception as e:
        logging.error(f"Error proxying image {url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/images/cache/stats")
async def get_image_cache_stats():
    """
    Get statistics about cached images.

    Returns:
        dict: Statistics including total images, size, breakdown by source
    """
    from list_sync.database import get_cached_image_stats

    try:
        stats = get_cached_image_stats()
        return stats
    except Exception as e:
        logging.exception(f"Error getting image cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/images/cache/cleanup")
async def cleanup_image_cache(hours: int = Query(720, description="Remove images not accessed in X hours")):
    """
    Clean up expired cached images.
    Removes both database records and files from filesystem.

    Args:
        hours: Remove images not accessed in this many hours (default: 720 = 30 days)

    Returns:
        dict: Cleanup results
    """
    from list_sync.database import cleanup_expired_images

    try:
        if hours < 24:
            raise HTTPException(status_code=400, detail="Hours must be at least 24")

        deleted_count = cleanup_expired_images(hours)
        return {
            "success": True,
            "deleted_count": deleted_count,
            "hours": hours,
            "message": f"Removed {deleted_count} expired images",
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error cleaning up image cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/images/cache/cleanup")
async def cleanup_image_cache(hours: int = Query(24, description="Remove images older than this many hours")):
    """Clean up expired cached images."""
    from list_sync.database import cleanup_expired_images

    try:
        deleted_count = cleanup_expired_images(hours)
        return {
            "message": f"Cleaned up {deleted_count} expired images",
            "deleted_count": deleted_count,
        }
    except Exception as e:
        logging.exception(f"Error cleaning up image cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/images/cache/list")
async def list_cached_images(limit: int = Query(50, ge=1, le=1000)):
    """List cached images for debugging."""
    try:
        images = fetch_cached_images(limit)

        return {"images": images, "total": len(images)}
    except Exception as e:
        logging.exception(f"Error listing cached images: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    logging.info("🚀 Starting ListSync Web UI API Server...")
    logging.info("📊 Dashboard will be available at: http://localhost:3222")
    logging.info("🔗 API documentation at: http://localhost:4222/docs")

    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=4222,
        reload=True,
        log_level="info",
    )
