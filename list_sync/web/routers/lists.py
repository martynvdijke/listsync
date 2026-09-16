"""routers.lists — moved verbatim from api_server.py (modularize-api-server)."""

import logging
from datetime import UTC

from fastapi import APIRouter, HTTPException, Query, Request

from list_sync.config import load_env_config
from list_sync.database import (
    count_item_lists,
    delete_list,
    get_item_lists_for_items,
    get_item_tmdb_and_posters,
    get_list_items,
    get_poster_urls,
    get_raw_lists,
    load_list_ids,
    normalize_list_id,
    save_list_id,
    update_list_user_id,
)
from list_sync.web.common import (
    ListAdd,
    ListUserUpdate,
    _describe_overseerr_user,
    _overseerr_user_names,
    _validate_overseerr_user,
    get_deduplicated_items,
)

router = APIRouter()


@router.get("/api/lists")
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


@router.get("/api/lists/debug")
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


@router.patch("/api/lists/{list_type}/{list_id:path}/user")
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


@router.post("/api/lists")
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


@router.get("/api/lists/{list_type}/{list_id:path}/items")
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


@router.delete("/api/lists/{list_type}/{list_id:path}")
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


@router.get("/api/items")
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


_metadata_cache = {}


_cache_ttl = 3600  # 1 hour in seconds


@router.post("/api/items/enriched/clear-cache")
async def clear_enriched_cache():
    """Clear the metadata cache (useful after fixing data issues)"""
    global _metadata_cache
    cache_size = len(_metadata_cache)
    _metadata_cache = {}
    logging.info(f"Cleared metadata cache ({cache_size} entries)")
    return {"message": f"Cleared {cache_size} cached entries", "success": True}


@router.get("/api/items/enriched")
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


@router.post("/api/media/request")
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
