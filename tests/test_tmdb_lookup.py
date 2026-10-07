"""Check title search, details and metadata lookups via TMDB.

These replace the Trakt search/metadata path: the sync pipeline resolves
titles to TMDB IDs and the web UI reads posters/ratings/genres from TMDB.
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def stub(n, a=()):
    m = types.ModuleType(n)
    for x in a:
        setattr(m, x, type(x, (), {}))
    sys.modules[n] = m
    return m


for n in ("seleniumbase", "bs4", "halo"):
    try:
        __import__(n)
    except ImportError:
        stub(n, ("SB", "BeautifulSoup", "Halo"))
c = stub("cryptography")
f = stub("cryptography.fernet", ("Fernet", "InvalidToken"))
c.fernet = f
d = stub("dotenv")
d.load_dotenv = lambda *a, **k: None
d.set_key = lambda *a, **k: None

import logging

logging.disable(logging.CRITICAL)

import requests

import list_sync.config as cfg
from list_sync.api import tmdb

fail = []


def check(label, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        fail.append(label)


class R:
    def __init__(self, status, body=None):
        self.status_code = status
        self._b = body

    def json(self):
        if self._b is None:
            raise ValueError("no json")
        return self._b

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


captured = {}


def fake_get(url, params=None, timeout=None):
    captured["url"] = url
    captured["params"] = params
    return fake_get.response


requests.get = fake_get

cfg.get_tmdb_api_key = lambda: "TESTKEY"

MOVIE_DETAILS = {
    "id": 278,
    "title": "The Shawshank Redemption",
    "release_date": "1994-10-14",
    "overview": "Two imprisoned men bond over a number of years.",
    "vote_average": 8.7,
    "genres": [{"id": 18, "name": "Drama"}, {"id": 80, "name": "Crime"}],
    "poster_path": "/abc.jpg",
    "imdb_id": "tt0111161",
}
TV_DETAILS = {
    "id": 1396,
    "name": "Breaking Bad",
    "first_air_date": "2008-01-20",
    "overview": "A chemistry teacher turns to crime.",
    "vote_average": 8.9,
    "genres": [{"id": 18, "name": "Drama"}],
    "poster_path": "/bb.jpg",
}
SEARCH_MOVIE = {
    "results": [
        {"id": 999, "title": "Wrong Remake", "release_date": "2000-01-01"},
        {"id": 278, "title": "The Shawshank Redemption", "release_date": "1994-10-14"},
    ]
}
SEARCH_TV = {"results": [{"id": 1396, "name": "Breaking Bad", "first_air_date": "2008-01-20"}]}

# --- title search, movie: exact year preferred over the first result ---
fake_get.response = R(200, SEARCH_MOVIE)
got = tmdb.search_by_title("The Shawshank Redemption", 1994, "movie")
check("search movie tmdb_id", got["tmdb_id"], 278)
check("search movie type", got["media_type"], "movie")
check("search movie title", got["title"], "The Shawshank Redemption")
check("search movie endpoint", captured["url"], "https://api.themoviedb.org/3/search/movie")
check("search movie query", captured["params"]["query"], "The Shawshank Redemption")
check("search movie year param", captured["params"]["year"], 1994)
check("search movie api key", captured["params"]["api_key"], "TESTKEY")

# --- title search, tv: uses the tv endpoint and first_air_date_year ---
fake_get.response = R(200, SEARCH_TV)
got = tmdb.search_by_title("Breaking Bad", 2008, "tv")
check("search tv tmdb_id", got["tmdb_id"], 1396)
check("search tv type", got["media_type"], "tv")
check("search tv title", got["title"], "Breaking Bad")
check("search tv endpoint", captured["url"], "https://api.themoviedb.org/3/search/tv")
check("search tv year param", captured["params"]["first_air_date_year"], 2008)

# --- title search: no year still returns the first result ---
fake_get.response = R(200, SEARCH_MOVIE)
got = tmdb.search_by_title("The Shawshank Redemption", None, "movie")
check("search no year -> first result", got["tmdb_id"], 999)
check("search no year omits param", "year" in captured["params"], False)

# --- title search: empty / error / no key ---
fake_get.response = R(200, {"results": []})
check("search no results -> None", tmdb.search_by_title("Nope", 2000, "movie"), None)
fake_get.response = R(401, {"status_message": "Invalid API key"})
check("search 401 -> None", tmdb.search_by_title("X", 2000, "movie"), None)
check("search empty title -> None", tmdb.search_by_title("", 2000, "movie"), None)

# --- details: movie ---
fake_get.response = R(200, MOVIE_DETAILS)
got = tmdb.get_details(278, "movie")
check("details movie endpoint", captured["url"], "https://api.themoviedb.org/3/movie/278")
check("details movie title", got["title"], "The Shawshank Redemption")
check("details movie year", got["year"], 1994)
check("details movie rating", got["rating"], 8.7)
check("details movie genres", got["genres"], ["Drama", "Crime"])
check("details movie poster", got["poster_path"], "/abc.jpg")
check("details movie imdb", got["imdb_id"], "tt0111161")

# --- details: tv ---
fake_get.response = R(200, TV_DETAILS)
got = tmdb.get_details(1396, "tv")
check("details tv endpoint", captured["url"], "https://api.themoviedb.org/3/tv/1396")
check("details tv title", got["title"], "Breaking Bad")
check("details tv year", got["year"], 2008)

# --- metadata: poster proxied through our own image cache ---
fake_get.response = R(200, MOVIE_DETAILS)
got = tmdb.get_metadata(tmdb_id=278, media_type="movie")
check("metadata rating", got["rating"], 8.7)
check("metadata overview", got["overview"], "Two imprisoned men bond over a number of years.")
check("metadata genres", got["genres"], ["Drama", "Crime"])
check("metadata poster is proxy", got["poster_url"].startswith("/api/images/proxy?url="), True)
check("metadata poster encodes tmdb url", "image.tmdb.org%2Ft%2Fp%2Fw500%2Fabc.jpg" in got["poster_url"], True)

# --- metadata: no poster path -> no poster url ---
no_poster = dict(MOVIE_DETAILS, poster_path=None)
fake_get.response = R(200, no_poster)
check("metadata no poster -> None", tmdb.get_metadata(tmdb_id=278, media_type="movie")["poster_url"], None)

# --- metadata: IMDb-only input resolves via /find first ---
FIND = {"movie_results": [{"id": 278, "title": "The Shawshank Redemption"}], "tv_results": []}
calls = []


def routed_get(url, params=None, timeout=None):
    calls.append(url)
    if "/find/" in url:
        return R(200, FIND)
    return R(200, MOVIE_DETAILS)


requests.get = routed_get
got = tmdb.get_metadata(imdb_id="tt0111161", media_type="movie")
check("metadata imdb-only resolves", got["tmdb_id"], 278)
check("metadata imdb-only used /find", any("/find/tt0111161" in u for u in calls), True)
check("metadata imdb-only used details", any(u.endswith("/movie/278") for u in calls), True)

# --- get_year: from a direct TMDB id ---
requests.get = fake_get
fake_get.response = R(200, MOVIE_DETAILS)
check("get_year movie", tmdb.get_year(tmdb_id=278, media_type="movie"), 1994)
fake_get.response = R(200, TV_DETAILS)
check("get_year tv", tmdb.get_year(tmdb_id=1396, media_type="tv"), 2008)
check("get_year no id -> None", tmdb.get_year(media_type="movie"), None)

# --- error handling ---
fake_get.response = R(500, None)
check("details 500 -> None", tmdb.get_details(278, "movie"), None)
fake_get.response = R(200, None)
check("details bad json -> None", tmdb.get_details(278, "movie"), None)


def boom(*a, **k):
    raise requests.exceptions.ConnectionError("refused")


requests.get = boom
check("details network error -> None", tmdb.get_details(278, "movie"), None)
check("search network error -> None", tmdb.search_by_title("X", 2000, "movie"), None)
requests.get = fake_get

# --- no api key configured: every lookup is a clean no-op ---
cfg.get_tmdb_api_key = lambda: None
check("no key -> unavailable", tmdb.is_available(), False)
check("no key search -> None", tmdb.search_by_title("X", 2000, "movie"), None)
check("no key details -> None", tmdb.get_details(278, "movie"), None)
check("no key metadata -> None", tmdb.get_metadata(tmdb_id=278, media_type="movie"), None)

print()
print("FAILED:", fail if fail else "none")
sys.exit(1 if fail else 0)
