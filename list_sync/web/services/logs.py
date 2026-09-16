"""services.logs — moved verbatim from api_server.py (modularize-api-server)."""

import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator
from datetime import datetime

from list_sync.web.common import _LOG_CATEGORY_KEYWORDS, _LOG_LINE_RE, LogEntry, LogStreamResponse


def get_line_number(entry):
    """Extract line number from log entry ID for secondary sorting"""
    try:
        # ID format is "log-{line_number}"
        return int(entry.id.split("-")[1])
    except (IndexError, ValueError):
        return 0


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
