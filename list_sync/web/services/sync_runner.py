"""services.sync_runner — moved verbatim from api_server.py (modularize-api-server)."""

from datetime import datetime
import asyncio
import json
import logging
import multiprocessing
import os
import signal

from fastapi import HTTPException
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
