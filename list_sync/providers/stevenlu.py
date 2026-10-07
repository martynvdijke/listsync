"""
Steven Lu popular movies provider for ListSync.
"""

import logging
from typing import Any

import requests

from . import register_provider


@register_provider("stevenlu")
def fetch_stevenlu_list(list_id=None) -> list[dict[str, Any]]:
    """
    Fetch Steven Lu's popular movies list from the JSON endpoint

    Args:
        list_id: JSON URL or preset identifier (e.g., "stevenlu", "movies-metacritic-min70.json", or full URL)

    Returns:
        List[Dict[str, Any]]: List of media items
    """
    media_items = []

    # Determine the JSON URL
    if not list_id or list_id == "stevenlu":
        # Default to original list
        json_url = "https://s3.amazonaws.com/popular-movies/movies.json"
    elif list_id.startswith("http://") or list_id.startswith("https://"):
        # Full URL provided
        json_url = list_id
    elif list_id.endswith(".json"):
        # Just the filename, construct full URL
        json_url = f"https://movies.stevenlu.com/{list_id}"
    else:
        # Preset identifier, construct URL
        json_url = (
            f"https://movies.stevenlu.com/{list_id}.json"
            if not list_id.endswith(".json")
            else f"https://movies.stevenlu.com/{list_id}"
        )

    logging.info(f"Fetching Steven Lu movies from: {json_url}")

    try:
        response = requests.get(json_url, timeout=10)
        response.raise_for_status()  # Raise exception for HTTP errors

        movies_data = response.json()
        logging.info(f"Found {len(movies_data)} movies in Steven Lu's list")

        # Enrich missing years via TMDB. The StevenLu payload carries a TMDB
        # (and IMDb) ID but no release year, so one details lookup fills it in.
        from list_sync.api import tmdb as tmdb_api

        logging.info("Enriching items with year data from TMDB API...")
        items_enriched = 0

        for idx, movie in enumerate(movies_data):
            try:
                title = movie.get("title", "").strip()
                imdb_id = movie.get("imdb_id")
                tmdb_id = movie.get("tmdb_id")

                if not title:
                    logging.warning(f"Skipping movie with empty title: {movie}")
                    continue

                # Enrich with year data from TMDB when any ID is available
                year = None
                if tmdb_api.is_available() and (tmdb_id or imdb_id):
                    try:
                        year = tmdb_api.get_year(tmdb_id=tmdb_id, imdb_id=imdb_id, media_type="movie")
                        if year:
                            items_enriched += 1
                    except Exception as e:
                        logging.debug(f"Could not enrich '{title}' (TMDB: {tmdb_id}, IMDB: {imdb_id}) with year: {e}")

                # All items from this source are movies
                media_items.append(
                    {
                        "title": title,
                        "imdb_id": imdb_id,
                        "tmdb_id": tmdb_id,
                        "media_type": "movie",
                        "year": year,  # Enriched from Trakt API
                    }
                )

                # Log progress every 50 items
                if len(media_items) % 50 == 0:
                    year_str = f"({year})" if year else "(year unknown)"
                    logging.info(
                        f"Progress: {len(media_items)}/{len(movies_data)} items processed, {items_enriched} enriched with year data"
                    )
                elif len(media_items) <= 3:
                    year_str = f"({year})" if year else "(year unknown)"
                    logging.info(f"Added movie: {title} {year_str} (IMDB: {imdb_id}, TMDB: {tmdb_id})")

            except Exception as e:
                logging.warning(f"Failed to parse movie data: {e!s}")
                continue

        logging.info(f"Steven Lu list fetched successfully. Found {len(media_items)} movies.")
        logging.info(f"Successfully enriched {items_enriched}/{len(media_items)} items with year data from TMDB API")
        return media_items

    except Exception as e:
        logging.exception(f"Error fetching Steven Lu list from {json_url}: {e!s}")
        raise
