"""routers.system — moved verbatim from api_server.py (modularize-api-server)."""

from fastapi import APIRouter

from datetime import datetime
import logging
import os

from fastapi import HTTPException
import requests

from list_sync.config import load_env_config
from list_sync.database import DB_FILE
from list_sync.database import check_database_connection
from list_sync.database import configure_sync_interval
from list_sync.database import load_sync_interval
from list_sync.utils.timezone_utils import get_current_timezone_info
from list_sync.utils.timezone_utils import list_supported_abbreviations
from list_sync.utils.timezone_utils import normalize_timezone_input
from list_sync.web.common import SystemStatus
from list_sync.web.common import build_log_info
from list_sync.web.common import find_listsync_processes

router = APIRouter()
@router.get("/api/system/status")
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


@router.get("/api/system/processes")
async def get_processes():
    """Get ListSync process information"""
    return find_listsync_processes()


@router.get("/api/system/logs")
async def get_log_info():
    """Get log file analysis"""
    return build_log_info()


@router.get("/api/system/database/test")
async def test_database():
    """Test database connectivity"""
    try:
        check_database_connection()
        return {"connected": True}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.get("/api/system/health")
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


@router.get("/api/setup/status")
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


@router.post("/api/setup/migrate-from-env")
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


@router.post("/api/setup/test/overseerr")
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


@router.get("/api/overseerr/users")
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


@router.post("/api/overseerr/users/sync")
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


@router.post("/api/setup/test/trakt")
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


@router.post("/api/setup/step1/essential")
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


@router.post("/api/setup/step2/configuration")
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


@router.post("/api/setup/step3/content-sources")
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


@router.post("/api/setup/complete")
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


@router.get("/api/sync-interval")
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


@router.put("/api/sync-interval")
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


@router.post("/api/sync-interval/sync-from-env")
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


@router.get("/api/overseerr/status")
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


@router.get("/api/system/time")
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


@router.get("/api/timezone/supported")
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


@router.get("/api/timezone/current")
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


@router.post("/api/timezone/validate")
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


@router.get("/api/overseerr/config")
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
