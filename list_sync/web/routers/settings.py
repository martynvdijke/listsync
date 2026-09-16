"""routers.settings — moved verbatim from api_server.py (modularize-api-server)."""

import logging
import os

import requests
from fastapi import APIRouter, HTTPException

from list_sync.database import DatabaseError, configure_sync_interval

router = APIRouter()


@router.get("/api/settings/config")
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


@router.post("/api/settings/config")
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


@router.post("/api/notifications/test")
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
