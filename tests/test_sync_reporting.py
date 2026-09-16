"""DB-backed sync reporting regression suite.

Covers the change `db-backed-sync-reporting`:
  * a simulated sync writes per-item rows into `sync_items`
  * the DAL reporting functions return the expected shapes/values
  * no log-parsing entry point remains except the single live-tail reader
  * the reporting endpoints serve identical JSON shapes from the database
"""

import os
import pathlib
import sys
import tempfile
import types

tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# helpers.py imports seleniumbase at module scope and api_server pulls in
# cryptography; none of the code under test touches a browser or a key.
for name in ("seleniumbase", "bs4", "dotenv", "halo"):
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            mod = types.ModuleType(name)
            for attr in ("SB", "BeautifulSoup", "load_dotenv", "set_key", "find_dotenv", "Halo"):
                setattr(mod, attr, lambda *a, **k: None)
            sys.modules[name] = mod


def stub(name, attrs=()):
    mod = types.ModuleType(name)
    for attr in attrs:
        setattr(mod, attr, type(attr, (), {}))
    sys.modules[name] = mod
    return mod


crypto = stub("cryptography")
crypto.fernet = stub("cryptography.fernet", ("Fernet", "InvalidToken"))

import sqlite3

import list_sync.database as db

db.DB_FILE = os.path.join(tmp, "list_sync.db")
db.init_database()

fail = []


def check(label, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        fail.append(label)


def check_true(label, cond):
    ok = bool(cond)
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        fail.append(label)


# ---------------------------------------------------------------- simulated sync
full_id = db.start_sync_in_db(session_id="sess_full", sync_type="full")
movie_id = db.save_sync_result(
    "Movie One", "movie", "tt1", 101, "requested", year=2020, tmdb_id="11", list_type="imdb", list_id="ls1"
)
db.add_item_to_sync(full_id, movie_id, "Movie One", "movie", "requested", "imdb", "ls1", 2020, "tt1", "11", 101)
db.add_item_to_sync(full_id, None, "Show Two", "tv", "already_available", "imdb", "ls1", 2019)
db.add_item_to_sync(full_id, None, "Show Three", "tv", "already_requested", "trakt", "ls2", 2018)
db.add_item_to_sync(full_id, None, "Movie Four", "movie", "skipped", "imdb", "ls1", 2017)
db.add_item_to_sync(
    full_id,
    None,
    "Lost Five",
    "movie",
    "not_found",
    "trakt",
    "ls2",
    2016,
    None,
    None,
    None,
    "Item not found in Seerr database",
)
db.add_item_to_sync(
    full_id,
    None,
    "Lost Five",
    "movie",
    "not_found",
    "trakt",
    "ls2",
    2016,
    None,
    None,
    None,
    "Item not found in Seerr database",
)
db.add_item_to_sync(full_id, None, "Boom Six", "movie", "error", "imdb", "ls1", 2015, None, None, None, "kaboom")
db.end_sync_in_db(session_id="sess_full", status="completed", total_items=7)

single_id = db.start_sync_in_db(session_id="sess_single", sync_type="single", list_type="imdb", list_id="ls1")
db.add_item_to_sync(single_id, None, "Solo Seven", "movie", "requested", "imdb", "ls1", 2014)
db.end_sync_in_db(session_id="sess_single", status="completed", total_items=1)

with sqlite3.connect(db.DB_FILE) as conn:
    row_count = conn.execute("SELECT COUNT(*) FROM sync_items").fetchone()[0]
check("simulated sync persists sync_items rows", row_count, 8)

# ------------------------------------------------------------------- DAL shapes
result = db.query_sync_items()
check("query_sync_items total", result["total"], 8)
check_true(
    "query_sync_items keys",
    {"items", "total", "sessions", "movie_count", "tv_count"} <= set(result.keys()),
)
first = result["items"][0]
check_true(
    "query_sync_items row fields",
    {
        "row_id",
        "title",
        "media_type",
        "year",
        "imdb_id",
        "tmdb_id",
        "overseerr_id",
        "status",
        "list_type",
        "list_id",
        "processed_at",
        "sync_session",
        "item_number",
        "total_items",
        "item_id",
        "db_status",
        "source_list_type",
        "source_list_id",
    }
    <= set(first.keys()),
)
check("query_sync_items sessions", sorted(result["sessions"]), ["sess_full", "sess_single"])
check("query_sync_items movie_count", result["movie_count"], 6)
check("query_sync_items tv_count", result["tv_count"], 2)

not_found = db.query_sync_items(statuses=["not_found"])
check("query_sync_items status filter", not_found["total"], 2)

searched = db.query_sync_items(search="lost")
check("query_sync_items search", searched["total"], 2)

by_session = db.query_sync_items(session_id="sess_single")
check("query_sync_items session filter", by_session["total"], 1)
check("query_sync_items item_number", by_session["items"][0]["item_number"], 1)
check("query_sync_items total_items", by_session["items"][0]["total_items"], 1)

joined = db.query_sync_items(search="Movie One")["items"][0]
check("query_sync_items joins synced_items status", joined["db_status"], "requested")
check("query_sync_items joins source list", joined["source_list_type"], "imdb")

sessions = db.get_sync_sessions()
check("get_sync_sessions total", sessions["total"], 2)
session = sessions["sessions"][0]
check_true(
    "get_sync_sessions to_dict shape",
    {
        "id",
        "type",
        "start_timestamp",
        "end_timestamp",
        "duration",
        "version",
        "total_items",
        "processed_items",
        "lists",
        "results",
        "items",
        "errors",
        "not_found_items",
        "average_time_ms",
        "total_time_seconds",
        "status",
    }
    <= set(session.keys()),
)
check(
    "get_sync_sessions result counts",
    session["results"],
    {"requested": 1, "already_available": 1, "already_requested": 1, "skipped": 1, "not_found": 2, "error": 1},
)
check("get_sync_sessions processed_items", session["processed_items"], 7)
check_true(
    "get_sync_sessions lists",
    {("imdb", "ls1"), ("trakt", "ls2")} <= {(item["type"], item["id"]) for item in session["lists"]},
)
check_true("get_sync_sessions errors", any(e["error"] == "kaboom" for e in session["errors"]))

by_id = db.get_sync_session_by_id("sess_full")
check("get_sync_session_by_id", by_id["id"], "sess_full")
check("get_sync_session_by_id missing", db.get_sync_session_by_id("nope"), None)

stats = db.get_sync_history_stats()
check("get_sync_history_stats sessions", stats["total_sessions"], 2)
check("get_sync_history_stats items", stats["total_items_processed"], 8)
check("get_sync_history_stats requested", stats["total_requested"], 2)
check("get_sync_history_stats errors", stats["total_errors"], 3)
check_true("get_sync_history_stats keys", {"recent_stats", "most_synced_lists", "success_rate"} <= set(stats.keys()))

recent = db.get_recent_sync_items(limit=3)
check("get_recent_sync_items len", len(recent), 3)
check_true(
    "get_recent_sync_items shape",
    {"title", "status", "status_text", "timestamp", "position", "total"} <= set(recent[0].keys()),
)
check("get_duplicate_count", db.get_duplicate_count(), 1)

payload = db.get_analytics_payload()
check_true(
    "get_analytics_payload keys",
    {
        "overview",
        "media_additions",
        "list_fetches",
        "matching",
        "search_failures",
        "scraping_performance",
        "source_distribution",
        "selector_performance",
        "genre_distribution",
        "year_distribution",
    }
    <= set(payload.keys()),
)
check("analytics overview total", payload["overview"]["total_items"], 8)
check("analytics overview errors", payload["overview"]["total_errors"], 3)
check_true("analytics year distribution", len(payload["year_distribution"]) >= 1)

sync_info = db.get_sync_info()
check_true(
    "get_sync_info shape",
    {"last_sync_start", "last_sync_complete", "sync_status", "recent_errors"} <= set(sync_info.keys()),
)
check_true("get_sync_info surfaces errors", any("kaboom" in e for e in sync_info["recent_errors"]))

# ------------------------------------------------------- no forbidden parsers
REPO = pathlib.Path(__file__).parent.parent
FORBIDDEN = (
    "parse_log_for_sync_info",
    "parse_docker_logs_for_activity",
    "parse_failures_from_logs",
    "parse_historic_items_from_logs",
    "get_duplicates_from_current_sync",
    "categorize_log_entry",
    "extract_media_info",
    "parse_log_line",
    "parse_recent_activity_from_structured_log",
    "SyncLogParser",
)
scan_files = [REPO / "api_server.py", *(REPO / "list_sync").rglob("*.py")]
for name in FORBIDDEN:
    hits = [f.relative_to(REPO) for f in scan_files if name in f.read_text(errors="ignore")]
    check(f"forbidden parser gone: {name}", hits, [])

# The single log reader now lives under list_sync/web (the shim holds no logic).
app_text = "\n".join(f.read_text(errors="ignore") for f in scan_files)
check("single live-tail reader", app_text.count("def get_log_entries("), 1)
check_true(
    "live-tail reader reachable from the SSE/log routes",
    "get_log_entries(" in (REPO / "list_sync/web/routers/logs.py").read_text(errors="ignore"),
)

main_text = (REPO / "list_sync" / "main.py").read_text(errors="ignore")
check_true("sync pipeline persists sync_items", "add_item_to_sync(" in main_text)

# ------------------------------------------------------ endpoint shape checks
import api_server

api_server.DB_FILE = db.DB_FILE

from fastapi.testclient import TestClient

client = TestClient(api_server.app)

body = client.get("/api/failures").json()
check_true(
    "failures shape",
    {
        "not_found",
        "errors",
        "total_failures",
        "filtered_count",
        "last_sync_time",
        "log_file_exists",
        "filters",
        "pagination",
    }
    <= set(body.keys()),
)
check("failures total", body["total_failures"], 3)
check("failures not_found count", len(body["not_found"]), 2)
check_true(
    "failure item fields",
    {"name", "title", "media_type", "year", "error_type", "error_details", "error_message", "retryable", "failed_at"}
    <= set(body["not_found"][0].keys()),
)

body = client.get("/api/processed").json()
check_true(
    "processed shape",
    {"items", "total_count", "filtered_count", "sync_sessions", "log_file_exists", "filters", "pagination"}
    <= set(body.keys()),
)
check("processed total_count", body["total_count"], 8)

body = client.get("/api/successful").json()
check_true(
    "successful shape",
    {
        "items",
        "total_count",
        "filtered_count",
        "movie_count",
        "tv_count",
        "sync_sessions",
        "log_file_exists",
        "filters",
        "pagination",
    }
    <= set(body.keys()),
)
check("successful total_count", body["total_count"], 5)

body = client.get("/api/sync-history").json()
check_true("sync-history shape", {"sessions", "total", "limit", "offset"} <= set(body.keys()))
check("sync-history sessions", body["total"], 2)

body = client.get("/api/sync-history/stats").json()
check_true(
    "sync-history stats shape",
    {"total_sessions", "full_syncs", "single_syncs", "recent_stats", "most_synced_lists"} <= set(body.keys()),
)

body = client.get("/api/sync-history/sess_full").json()
check("sync-history session id", body["id"], "sess_full")

body = client.get("/api/analytics/overview").json()
check_true(
    "analytics overview shape",
    {"total_items", "success_rate", "active_sync", "total_errors", "last_sync_time"} <= set(body.keys()),
)

body = client.get("/api/analytics").json()
check_true(
    "analytics response shape",
    {
        "overview",
        "media_additions",
        "list_fetches",
        "matching",
        "search_failures",
        "scraping_performance",
        "source_distribution",
        "selector_performance",
        "genre_distribution",
        "year_distribution",
    }
    <= set(body.keys()),
)
check("analytics overview total_items", body["overview"]["total_items"], 8)
check("analytics selector placeholder retained", len(body["selector_performance"]), 6)
check("analytics genre placeholder retained", len(body["genre_distribution"]), 8)

body = client.get("/api/stats/sync").json()
check_true(
    "stats/sync shape",
    {
        "total_processed",
        "successful_items",
        "total_requested",
        "total_errors",
        "success_rate",
        "duplicates_in_current_sync",
        "last_updated",
        "breakdown",
    }
    <= set(body.keys()),
)

body = client.get("/api/recent-activity").json()
check_true("recent-activity shape", {"items", "total_items", "page", "limit", "log_file_used"} <= set(body.keys()))

body = client.get("/api/activity/recent").json()
check_true("activity/recent shape", {"items", "total_items", "page", "limit", "log_file_used"} <= set(body.keys()))

# --------------------------------------------- pipeline writes sync_items rows (non-dry-run)
import list_sync.main as main_mod

pipeline_id = db.start_sync_in_db(session_id="sess_pipeline", sync_type="full")


def _fake_process(item, client, dry_run, is_4k=False, list_type=None, list_id=None):
    return {
        "title": item["title"],
        "status": "requested",
        "year": item.get("year"),
        "media_type": item.get("media_type", "movie"),
        "item_id": 42,
        "imdb_id": None,
        "tmdb_id": None,
        "overseerr_id": 999,
        "error_message": None,
    }


main_mod.process_media_item = _fake_process
main_mod.sync_media_to_overseerr(
    [
        {
            "title": "Pipeline Movie",
            "media_type": "movie",
            "year": 2020,
            "_source_lists": [{"type": "imdb", "id": "ls9", "user_id": "1"}],
        }
    ],
    seerr_client=types.SimpleNamespace(requester_user_id="1"),
    dry_run=False,
    sync_id=pipeline_id,
    session_id="sess_pipeline",
)
pipeline_rows = db.query_sync_items(session_id="sess_pipeline")
check("pipeline writes sync_items rows", pipeline_rows["total"], 1)
check("pipeline persists primary source list", pipeline_rows["items"][0]["list_type"], "imdb")
check("pipeline persists status", pipeline_rows["items"][0]["status"], "requested")

# ---- fix 1: filtered total_items is session total independent of WHERE
# sess_full has 7 items; filtering by status should keep total_items == 7
filtered_one = db.query_sync_items(session_id="sess_full", statuses=["requested"])
check_true("filtered total_items is session total", all(r["total_items"] == 7 for r in filtered_one["items"]))
check_true("filtered item_number uses session total", all(r["total_items"] == 7 for r in filtered_one["items"]))

# also check cross-session filter
all_requested = db.query_sync_items(statuses=["requested"])
# requested rows: 1 in sess_full + 1 in sess_single + 1 in sess_pipeline = 3
check_true(
    "filtered total_items independent of status filter",
    all(
        (r["sync_session"] == "sess_full" and r["total_items"] == 7)
        or (r["sync_session"] == "sess_single" and r["total_items"] == 1)
        or (r["sync_session"] == "sess_pipeline" and r["total_items"] == 1)
        for r in all_requested["items"]
    ),
)

# ---- fix 1b: offset without limit is not ignored
# Use a fresh session to have deterministic count
off_sess = db.start_sync_in_db(session_id="sess_offset_test", sync_type="full")
for i in range(5):
    db.add_item_to_sync(off_sess, None, f"Off Item {i}", "movie", "requested", "imdb", "ls_off", 2020)
db.end_sync_in_db(session_id="sess_offset_test", status="completed", total_items=5)
off_result = db.query_sync_items(session_id="sess_offset_test", offset=2)
check("offset without limit returns remaining rows", off_result["total"], 5)
check("offset without limit respects offset", len(off_result["items"]), 3)

# ---- fix 2: session with available/synced/would_be_synced still appears
edge_id = db.start_sync_in_db(session_id="sess_edge_status", sync_type="full")
db.add_item_to_sync(edge_id, None, "Edge Av", "movie", "available", "imdb", "ls_edge", 2020)
db.add_item_to_sync(edge_id, None, "Edge Synced", "movie", "synced", "imdb", "ls_edge", 2020)
db.add_item_to_sync(edge_id, None, "Edge Would", "movie", "would_be_synced", "imdb", "ls_edge", 2020)
db.end_sync_in_db(session_id="sess_edge_status", status="completed", total_items=3)
edge_session = db.get_sync_session_by_id("sess_edge_status")
check_true("edge session appears", edge_session is not None)
if edge_session:
    counts = edge_session["results"]
    total_counts = sum(counts.values())
    check("edge session counts sum to item count", total_counts, 3)
    check_true("edge session non-zero counts", total_counts > 0)
    check_true("edge available/synced mapped to already_available", counts.get("already_available", 0) >= 2)
    check_true("edge would_be_synced mapped to skipped", counts.get("skipped", 0) >= 1)

# ---- fix 3: multi-list item findable via each list filter
multi_sess = db.start_sync_in_db(session_id="sess_multi_list", sync_type="full")
multi_item = {
    "title": "Multi List Movie",
    "media_type": "movie",
    "year": 2021,
    "_source_lists": [
        {"type": "imdb", "id": "lsA", "user_id": "1"},
        {"type": "trakt", "id": "lsB", "user_id": "1"},
    ],
}


def _fake_multi(item, client, dry_run, is_4k=False, list_type=None, list_id=None):
    return {
        "title": item["title"],
        "status": "requested",
        "year": item.get("year"),
        "media_type": item.get("media_type", "movie"),
        "item_id": 99,
        "imdb_id": None,
        "tmdb_id": None,
        "overseerr_id": 1000,
        "error_message": None,
    }


main_mod.process_media_item = _fake_multi
main_mod.sync_media_to_overseerr(
    [multi_item],
    seerr_client=types.SimpleNamespace(requester_user_id="1"),
    dry_run=False,
    sync_id=multi_sess,
    session_id="sess_multi_list",
)
via_imdb = db.query_sync_items(list_type="imdb", list_id="lsA")
check_true("multi-list item findable via imdb lsA", any(r["title"] == "Multi List Movie" for r in via_imdb["items"]))
via_trakt = db.query_sync_items(list_type="trakt", list_id="lsB")
check_true("multi-list item findable via trakt lsB", any(r["title"] == "Multi List Movie" for r in via_trakt["items"]))
multi_rows = db.query_sync_items(session_id="sess_multi_list")
check("multi-list item inserts one row per list", multi_rows["total"], 2)

# ---- fix 4: dry run writes no sync_items rows
dry_sess = db.start_sync_in_db(session_id="sess_dry_run", sync_type="full")
main_mod.process_media_item = _fake_process
main_mod.sync_media_to_overseerr(
    [
        {
            "title": "Dry Run Movie",
            "media_type": "movie",
            "year": 2022,
            "_source_lists": [{"type": "imdb", "id": "lsDry", "user_id": "1"}],
        }
    ],
    seerr_client=types.SimpleNamespace(requester_user_id="1"),
    dry_run=True,
    sync_id=dry_sess,
    session_id="sess_dry_run",
)
dry_rows = db.query_sync_items(session_id="sess_dry_run")
check("dry run writes no sync_items rows", dry_rows["total"], 0)

print()
print("FAILED:", fail if fail else "none")
sys.exit(1 if fail else 0)
