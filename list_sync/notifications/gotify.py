"""
Gotify notifications for ListSync.
"""

import logging
import os

import requests

from ..utils.url_safety import validate_outbound_url


def get_gotify_config() -> tuple[str, str] | None:
    """
    Get the Gotify server URL and app token from database config or environment.

    Returns:
        tuple[str, str] or None: (url, token) if configured, else None
    """
    # Database first (dashboard-managed), then the environment fallback.
    try:
        from ..config import ConfigManager
        config = ConfigManager()

        enabled = config.get_setting("gotify_enabled")
        if enabled and str(enabled).lower() in ("true", "1", "yes"):
            url = config.get_setting("gotify_url")
            token = config.get_setting("gotify_token")
            if url and token:
                return str(url), str(token)
    except Exception as e:
        logging.debug(f"Could not load Gotify config from database: {e}")

    url = os.getenv("GOTIFY_URL")
    token = os.getenv("GOTIFY_TOKEN")
    if url and token:
        return url, token
    return None


def send_to_gotify(summary_text, sync_results=None, url: str | None = None,
                   token: str | None = None, automated: bool = False,
                   is_single_list: bool = False, priority: int = 0) -> None:
    """Send a sync summary to a Gotify server."""
    if not url or not token:
        config = get_gotify_config()
        if not config:
            return
        url, token = config

    # This value can arrive from an environment variable or a hand-edited
    # database row, so it is checked here as well as at the write paths. A
    # self-hosted Gotify normally lives on a private address, so private is
    # allowed; a cloud metadata endpoint never is.
    allowed, reason = validate_outbound_url(url, allow_private=True)
    if not allowed:
        logging.error(f"Refusing to send Gotify notification: {reason}")
        return

    if is_single_list:
        title = "📋 ListSync Single List Complete"
    else:
        title = "🎬 ListSync Sync Complete"

    try:
        response = requests.post(
            f"{url.rstrip('/')}/message",
            params={"token": token},
            json={"title": title, "message": summary_text, "priority": priority},
            timeout=10,
        )
        response.raise_for_status()
        logging.info("Gotify notification sent successfully")
    except Exception as e:
        logging.exception(f"Failed to send Gotify notification: {e}")
