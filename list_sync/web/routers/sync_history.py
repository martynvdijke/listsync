"""routers.sync_history — moved verbatim from api_server.py (modularize-api-server)."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from list_sync.database import get_sync_history_stats as query_sync_history_stats
from list_sync.database import get_sync_session_by_id, get_sync_sessions
from list_sync.web.services.logs import get_log_entries

router = APIRouter()


@router.get("/api/sync-history")
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


@router.get("/api/sync-history/stats")
async def get_sync_history_stats():
    """Get aggregate statistics about sync history."""
    try:
        return query_sync_history_stats()
    except Exception as e:
        logging.exception(f"Error loading sync history stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/sync-history/{session_id}")
async def get_sync_session(session_id: str):
    """Get detailed information about a specific sync session."""
    session = get_sync_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/api/sync-history/{session_id}/raw-logs")
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
