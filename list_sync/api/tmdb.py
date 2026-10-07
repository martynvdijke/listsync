"""
TMDB API client for resolving external IDs to TMDB IDs.

IMDb lists give us IMDb IDs, but Seerr is addressed by TMDB ID, so
something has to bridge the two. ListSync has always used Trakt for that, but
Trakt now requires a paid VIP subscription to register an API application,
which puts exact ID resolution behind a paywall.

TMDB's own /find endpoint does the same job from a free API key, and in one
hop rather than two. Without either, matching falls back to fuzzy title search,
which mismatches remakes, sequels and common titles.
"""

import logging
from typing import Any
from urllib.parse import quote

import requests

TMDB_API_BASE = "https://api.themoviedb.org/3"

# Poster images are served from TMDB's CDN at a chosen width. We proxy them
# through our own image cache for the same reason we did with Trakt: no
# hotlinking, and the browser only ever talks to our origin.
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

# TMDB returns results grouped by media type; these are the groups we care
# about, in the order we prefer them for a given requested type.
_RESULT_KEYS = {
    "movie": ("movie_results", "tv_results"),
    "tv": ("tv_results", "movie_results"),
}


def is_available() -> bool:
    """Whether a TMDB API key is configured."""
    from ..config import get_tmdb_api_key

    return bool(get_tmdb_api_key())


def resolve_imdb_id(imdb_id: str, media_type: str = "movie") -> dict[str, Any] | None:
    """
    Resolve an IMDb ID to a TMDB ID using TMDB's /find endpoint.

    This is an exact lookup on the external ID, not a search, so a result is
    always the right title.

    Args:
        imdb_id (str): IMDb ID, e.g. "tt0111161"
        media_type (str): "movie" or "tv" - decides which result group is
            preferred when a title appears in both

    Returns:
        Optional[Dict[str, Any]]: {"tmdb_id": int, "media_type": str, "title": str}
            or None if unresolved or no API key is configured
    """
    from ..config import get_tmdb_api_key

    api_key = get_tmdb_api_key()
    if not api_key:
        return None

    if not imdb_id or not imdb_id.startswith("tt"):
        logging.debug(f"Not an IMDb ID, skipping TMDB lookup: {imdb_id}")
        return None

    url = f"{TMDB_API_BASE}/find/{imdb_id}"
    params = {"api_key": api_key, "external_source": "imdb_id"}

    try:
        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 401:
            logging.error(
                "TMDB rejected the API key (401). Check TMDB_KEY - "
                "a free key is available at https://www.themoviedb.org/settings/api",
            )
            return None

        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logging.warning(f"TMDB lookup failed for {imdb_id}: {e}")
        return None
    except ValueError as e:
        logging.warning(f"TMDB returned invalid JSON for {imdb_id}: {e}")
        return None

    # Prefer the group matching the type we're looking for, then fall back to
    # the other - IMDb sometimes classifies a title differently from TMDB.
    for key in _RESULT_KEYS.get(media_type, _RESULT_KEYS["movie"]):
        results = data.get(key) or []
        if not results:
            continue

        match = results[0]
        tmdb_id = match.get("id")
        if tmdb_id is None:
            continue

        resolved_type = "tv" if key == "tv_results" else "movie"
        title = match.get("title") or match.get("name")

        if resolved_type != media_type:
            logging.info(
                f"TMDB resolved {imdb_id} as {resolved_type}, not {media_type} - using {resolved_type}",
            )

        return {
            "tmdb_id": int(tmdb_id),
            "media_type": resolved_type,
            "title": title,
        }

    logging.info(f"TMDB has no entry for IMDb ID {imdb_id}")
    return None


def _get_json(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """GET a TMDB path, returning parsed JSON or None on any failure."""
    url = f"{TMDB_API_BASE}{path}"
    try:
        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 401:
            logging.error(
                "TMDB rejected the API key (401). Check TMDB_KEY - "
                "a free key is available at https://www.themoviedb.org/settings/api",
            )
            return None

        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.warning(f"TMDB request failed ({url}): {e}")
        return None
    except ValueError as e:
        logging.warning(f"TMDB returned invalid JSON ({url}): {e}")
        return None


def _media_kind(media_type: str) -> str:
    """Map ListSync's media types to TMDB's path segment."""
    return "tv" if media_type == "tv" else "movie"


def _year_from_date(value: str | None) -> int | None:
    """Pull a 4-digit year off a TMDB date string like '1994-10-14'."""
    if value and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def search_by_title(title: str, year: int | None, media_type: str) -> dict[str, Any] | None:
    """
    Resolve a title (and optional year) to a TMDB ID via TMDB's search API.

    This is the title-based counterpart to resolve_imdb_id, replacing the
    Trakt search ListSync used before. An exact year match is preferred when
    one is supplied; otherwise the most popular result wins.

    Returns:
        Optional[Dict[str, Any]]: {"tmdb_id": int, "media_type": str, "title": str}
            or None if unresolved or no API key is configured
    """
    from ..config import get_tmdb_api_key

    api_key = get_tmdb_api_key()
    if not api_key or not title:
        return None

    kind = _media_kind(media_type)
    params: dict[str, Any] = {"api_key": api_key, "query": title, "include_adult": "false"}
    if year:
        params["year" if kind == "movie" else "first_air_date_year"] = int(year)

    data = _get_json(f"/search/{kind}", params)
    results = (data or {}).get("results") or []
    if not results:
        logging.info(f"TMDB found no results for '{title}' ({year}) [{media_type}]")
        return None

    chosen = None
    if year:
        for result in results:
            date = result.get("release_date") or result.get("first_air_date") or ""
            if date[:4] == str(year):
                chosen = result
                break
    if chosen is None:
        chosen = results[0]

    tmdb_id = chosen.get("id")
    if tmdb_id is None:
        return None

    return {
        "tmdb_id": int(tmdb_id),
        "media_type": kind,
        "title": chosen.get("title") or chosen.get("name"),
    }


def get_details(tmdb_id: int | None, media_type: str = "movie") -> dict[str, Any] | None:
    """
    Fetch TMDB details for a numeric TMDB ID.

    Returns the standard fields the UI and the sync pipeline need, normalized
    across movies and shows.

    Returns:
        Optional[Dict[str, Any]]: title, year, overview, rating (0-10), genres,
            poster_path, imdb_id and the ids themselves, or None on failure.
    """
    from ..config import get_tmdb_api_key

    api_key = get_tmdb_api_key()
    if not api_key or tmdb_id is None:
        return None

    try:
        tmdb_id = int(tmdb_id)
    except (ValueError, TypeError):
        logging.warning(f"Invalid TMDB ID for details lookup: {tmdb_id}")
        return None

    kind = _media_kind(media_type)
    data = _get_json(f"/{kind}/{tmdb_id}", {"api_key": api_key})
    if not data:
        return None

    if kind == "tv":
        title = data.get("name")
        year = _year_from_date(data.get("first_air_date"))
    else:
        title = data.get("title")
        year = _year_from_date(data.get("release_date"))

    genres = [genre["name"] for genre in (data.get("genres") or []) if genre.get("name")]

    return {
        "tmdb_id": tmdb_id,
        "media_type": kind,
        "title": title,
        "year": year,
        "overview": data.get("overview"),
        "rating": data.get("vote_average"),
        "genres": genres,
        "poster_path": data.get("poster_path"),
        "imdb_id": data.get("imdb_id"),
    }


def _resolve_to_tmdb(tmdb_id: int | None, imdb_id: str | None, media_type: str) -> tuple[int | None, str]:
    """Fill in a missing TMDB ID from an IMDb ID when possible."""
    if tmdb_id is None and imdb_id:
        resolved = resolve_imdb_id(imdb_id, media_type)
        if resolved:
            return resolved["tmdb_id"], resolved["media_type"]
    return tmdb_id, media_type


def get_year(tmdb_id: int | None = None, imdb_id: str | None = None, media_type: str = "movie") -> int | None:
    """
    Resolve just the release year for a title, via TMDB.

    Used to enrich providers (e.g. StevenLu) that supply an ID but no year.
    Accepts a TMDB ID directly, or an IMDb ID to resolve first.

    Returns:
        Optional[int]: the year, or None if unavailable
    """
    tmdb_id, media_type = _resolve_to_tmdb(tmdb_id, imdb_id, media_type)
    if tmdb_id is None:
        return None

    details = get_details(tmdb_id, media_type)
    return details.get("year") if details else None


def get_metadata(
    tmdb_id: int | None = None, imdb_id: str | None = None, media_type: str = "movie"
) -> dict[str, Any] | None:
    """
    Fetch poster, rating, overview and genres for a title from TMDB.

    This replaces get_trakt_metadata for the web UI. The poster is returned as
    a same-origin proxy URL so the image cache stays the only thing talking to
    the CDN.

    Returns:
        Optional[Dict[str, Any]]: metadata including poster_url, rating,
            overview and genres, or None if unavailable
    """
    tmdb_id, media_type = _resolve_to_tmdb(tmdb_id, imdb_id, media_type)
    if tmdb_id is None:
        logging.debug(f"No TMDB ID for metadata lookup (tmdb={tmdb_id}, imdb={imdb_id})")
        return None

    details = get_details(tmdb_id, media_type)
    if not details:
        return None

    poster_url = None
    if details.get("poster_path"):
        full_url = f"{TMDB_IMAGE_BASE}{details['poster_path']}"
        poster_url = f"/api/images/proxy?url={quote(full_url, safe='')}"

    return {
        "title": details.get("title"),
        "year": details.get("year"),
        "overview": details.get("overview"),
        "rating": details.get("rating"),
        "genres": details.get("genres", []),
        "poster_url": poster_url,
        "tmdb_id": details.get("tmdb_id"),
        "imdb_id": details.get("imdb_id") or imdb_id,
    }
