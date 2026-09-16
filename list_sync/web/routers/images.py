"""routers.images — moved verbatim from api_server.py (modularize-api-server)."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse

from list_sync.database import fetch_cached_images
from list_sync.web.services.images import sniff_image_type

router = APIRouter()


@router.get("/api/images/proxy")
async def proxy_image(url: str = Query(..., description="Image URL to proxy/cache")):
    """
    Proxy and cache images from external sources (Trakt, TMDB, etc.).
    This ensures compliance with Trakt's image caching requirements.
    Images are stored in data/images/ folder and served from filesystem.

    FLOW:
    1. Check if image is cached in database
    2. If cached, verify file exists and serve from filesystem
    3. If not cached or file missing:
       - Download from original URL (Trakt, TMDB, etc.)
       - Save to data/images/ with hash-based filename
       - Store metadata in database
       - Serve from filesystem
    4. All subsequent requests serve from local cache (NO HOTLINKING)

    Args:
        url: The original image URL to proxy

    Returns:
        The cached image file with proper headers
    """
    import os

    import requests

    from list_sync.database import get_cached_image, save_cached_image

    try:
        # This endpoint fetches a caller-supplied URL and returns the body, so
        # without a check it is a read primitive against anything the server
        # can reach. Posters come from public CDNs, so private and reserved
        # addresses are refused outright.
        from list_sync.utils.url_safety import validate_outbound_url

        allowed, reason = validate_outbound_url(url, allow_private=False)
        if not allowed:
            logging.warning(f"Blocked image proxy request: {reason}")
            raise HTTPException(status_code=400, detail=f"Invalid image URL: {reason}")

        # Check if we have this image cached
        cached = get_cached_image(url)
        if cached:
            local_path = cached.get("local_path")

            # Verify file exists
            if local_path and os.path.exists(local_path):
                # Serve file from filesystem (NO HOTLINKING - Trakt API compliant)
                logging.debug(f"Serving cached image from: {local_path}")

                # Generate ETag from file modification time for efficient caching
                try:
                    mtime = os.path.getmtime(local_path)
                    etag = f'W/"{int(mtime)}"'
                    last_modified = datetime.fromtimestamp(mtime).strftime("%a, %d %b %Y %H:%M:%S GMT")
                except OSError as e:
                    logging.debug("Failed to get file mtime for %s: %s", local_path, e)
                    etag = None
                    last_modified = None

                headers = {
                    "Cache-Control": "public, max-age=31536000, immutable",  # 1 year - aggressive caching
                    "X-Image-Source": cached.get("source", "unknown"),
                    "X-Image-Cached": "true",
                }

                if etag:
                    headers["ETag"] = etag
                if last_modified:
                    headers["Last-Modified"] = last_modified

                return FileResponse(
                    local_path,
                    media_type=cached.get("mime_type") or "image/webp",
                    headers=headers,
                )
            # File missing but DB record exists - log and re-download
            logging.warning(f"Cached image file missing, re-downloading: {url}")

        # Download the image from original source (Trakt, TMDB, etc.).
        # Redirects are not followed: a permitted public URL is free to answer
        # with a 302 to a private address, which would defeat the check above.
        logging.info(f"Downloading image from source: {url}")
        response = requests.get(
            url,
            timeout=30,
            allow_redirects=False,
            headers={
                "User-Agent": "ListSync/1.0.0",
            },
        )

        if response.status_code in (301, 302, 303, 307, 308):
            redirect_target = response.headers.get("Location", "")
            allowed, reason = validate_outbound_url(redirect_target, allow_private=False)
            if not allowed:
                logging.warning(f"Blocked image proxy redirect to {redirect_target}: {reason}")
                raise HTTPException(status_code=400, detail=f"Unsafe redirect: {reason}")
            logging.info(f"Following image redirect to: {redirect_target}")
            response = requests.get(
                redirect_target,
                timeout=30,
                allow_redirects=False,
                headers={
                    "User-Agent": "ListSync/1.0.0",
                },
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to fetch image: {response.status_code}",
            )

        image_data = response.content

        # Validate image data
        if not image_data or len(image_data) == 0:
            raise HTTPException(status_code=500, detail="Empty image data received")

        # Enforce reasonable file size limit (10MB)
        max_size = 10 * 1024 * 1024  # 10MB
        if len(image_data) > max_size:
            logging.warning(f"Image too large ({len(image_data)} bytes), skipping cache: {url}")
            # Serve directly without caching
            return Response(
                content=image_data,
                media_type="image/webp",
                headers={"Cache-Control": "no-cache"},
            )

        # Detect image type from actual data (most reliable method)
        image_type = sniff_image_type(image_data)
        if not image_type:
            # Fallback: try to detect from URL or Content-Type header
            content_type = response.headers.get("Content-Type", "")
            if "webp" in content_type:
                image_type = "webp"
            elif "jpeg" in content_type or "jpg" in content_type:
                image_type = "jpeg"
            elif "png" in content_type:
                image_type = "png"
            else:
                image_type = "webp"  # Default to webp for Trakt images

        mime_type = f"image/{image_type}"

        # Determine source from URL
        if "trakt.tv" in url or "walter" in url:
            source = "trakt"
        elif "tmdb.org" in url or "themoviedb.org" in url:
            source = "tmdb"
        else:
            source = "unknown"

        # Save to cache (saves to data/images/ filesystem and updates database)
        logging.info(f"Saving {len(image_data)} bytes to cache as {image_type}")
        image_id = save_cached_image(url, image_data, mime_type, source)

        # Get the saved image record to get local_path
        cached = get_cached_image(url)
        if cached and cached.get("local_path"):
            local_path = cached["local_path"]

            # Serve the newly saved file
            # Generate ETag for newly saved file
            try:
                mtime = os.path.getmtime(local_path)
                etag = f'W/"{int(mtime)}"'
                last_modified = datetime.fromtimestamp(mtime).strftime("%a, %d %b %Y %H:%M:%S GMT")
            except OSError as e:
                logging.debug("Failed to get file mtime for %s: %s", local_path, e)
                etag = None
                last_modified = None

            headers = {
                "Cache-Control": "public, max-age=31536000, immutable",  # 1 year - aggressive caching
                "X-Image-Source": source,
                "X-Image-Cached": "false",  # First time, so newly cached
            }

            if etag:
                headers["ETag"] = etag
            if last_modified:
                headers["Last-Modified"] = last_modified

            return FileResponse(
                local_path,
                media_type=mime_type,
                headers=headers,
            )
        # Fallback: serve from memory if file save failed
        logging.warning(f"Failed to get local_path after save, serving from memory: {url}")
        return Response(
            content=image_data,
            media_type=mime_type,
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-Image-Source": source,
                "X-Image-Cached": "false",
            },
        )

    except HTTPException:
        # A rejected URL is a deliberate 400, not a server fault - let it through
        # rather than have the catch-all below turn it into a 500.
        raise
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching image {url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch image: {e!s}")
    except Exception as e:
        logging.error(f"Error proxying image {url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/images/cache/stats")
async def get_image_cache_stats():
    """
    Get statistics about cached images.

    Returns:
        dict: Statistics including total images, size, breakdown by source
    """
    from list_sync.database import get_cached_image_stats

    try:
        stats = get_cached_image_stats()
        return stats
    except Exception as e:
        logging.exception(f"Error getting image cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/images/cache/cleanup")
async def cleanup_image_cache(hours: int = Query(720, description="Remove images not accessed in X hours")):
    """
    Clean up expired cached images.
    Removes both database records and files from filesystem.

    Args:
        hours: Remove images not accessed in this many hours (default: 720 = 30 days)

    Returns:
        dict: Cleanup results
    """
    from list_sync.database import cleanup_expired_images

    try:
        if hours < 24:
            raise HTTPException(status_code=400, detail="Hours must be at least 24")

        deleted_count = cleanup_expired_images(hours)
        return {
            "success": True,
            "deleted_count": deleted_count,
            "hours": hours,
            "message": f"Removed {deleted_count} expired images",
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error cleaning up image cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/images/cache/cleanup")
async def cleanup_image_cache(hours: int = Query(24, description="Remove images older than this many hours")):
    """Clean up expired cached images."""
    from list_sync.database import cleanup_expired_images

    try:
        deleted_count = cleanup_expired_images(hours)
        return {
            "message": f"Cleaned up {deleted_count} expired images",
            "deleted_count": deleted_count,
        }
    except Exception as e:
        logging.exception(f"Error cleaning up image cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/images/cache/list")
async def list_cached_images(limit: int = Query(50, ge=1, le=1000)):
    """List cached images for debugging."""
    try:
        images = fetch_cached_images(limit)

        return {"images": images, "total": len(images)}
    except Exception as e:
        logging.exception(f"Error listing cached images: {e}")
        raise HTTPException(status_code=500, detail=str(e))
