"""common — moved verbatim from api_server.py (modularize-api-server)."""

import logging
import os
import re
from collections import Counter
from datetime import datetime
from typing import Any

import psutil
from pydantic import BaseModel

from list_sync.database import DB_FILE, get_all_synced_items, get_sync_info, get_synced_items_quality_rows


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
