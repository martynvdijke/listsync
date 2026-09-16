"""routers.collections — moved verbatim from api_server.py (modularize-api-server)."""

import asyncio
import logging
import multiprocessing

from fastapi import APIRouter, HTTPException, Query, Request

from list_sync.web.services.sync_runner import _run_collection_sync_in_subprocess

router = APIRouter()


@router.get("/api/collections")
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


@router.get("/api/collections/random")
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


@router.get("/api/collections/popular")
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


@router.get("/api/collections/synced")
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


@router.get("/api/collections/{franchise_name}")
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


@router.get("/api/collections/{franchise_name}/movies")
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


@router.get("/api/collections/{franchise_name}/poster")
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


@router.post("/api/collections/posters/batch")
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


@router.post("/api/collections/{franchise_name}/sync")
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
