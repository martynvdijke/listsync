"""routers.sync — moved verbatim from api_server.py (modularize-api-server)."""

from fastapi import APIRouter

from datetime import UTC
from datetime import datetime
import logging
import signal

from fastapi import HTTPException
import psutil

from list_sync.web.common import find_listsync_processes

router = APIRouter()
@router.post("/api/sync/trigger")
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


@router.post("/api/sync/single")
async def trigger_single_list_sync_endpoint(sync_request: dict):
    """Endpoint for single list sync requests - redirects to main trigger endpoint"""
    # Redirect to the main trigger endpoint with the same payload
    return await trigger_manual_sync(sync_request)


@router.get("/api/sync/status")
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


@router.post("/api/sync/{job_id}/cancel")
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


@router.get("/api/sync/status/live")
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
