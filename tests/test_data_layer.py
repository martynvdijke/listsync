"""Data-layer boundary and round-trip tests."""

import os
import sys
import tempfile
import types

tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for name in ("seleniumbase", "bs4", "dotenv"):
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            mod = types.ModuleType(name)
            for attr in ("SB", "BeautifulSoup", "load_dotenv", "set_key", "find_dotenv"):
                setattr(mod, attr, lambda *a, **k: None)
            sys.modules[name] = mod

import list_sync.database as db

db.DB_FILE = os.path.join(tmp, "list_sync.db")
db.init_database()

import sqlite3

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


# --- source-scan guard ---
import pathlib

REPO = pathlib.Path(__file__).parent.parent
# every .py under list_sync/ except database.py
list_sync_files = [p for p in (REPO / "list_sync").rglob("*.py") if p.name != "database.py"]
extra_files = [REPO / "api_server.py", REPO / "start_api.py"]
for f in list_sync_files + extra_files:
    if not f.exists():
        continue
    text = f.read_text(errors="ignore")
    has_connect = "sqlite3.connect(" in text
    has_import = "import sqlite3" in text
    check(f"no sqlite3.connect in {f.relative_to(REPO)}", has_connect, False)
    check(f"no import sqlite3 in {f.relative_to(REPO)}", has_import, False)

# exactly one normalize_list_id
count = 0
for f in [REPO / "api_server.py"] + list((REPO / "list_sync").rglob("*.py")):
    if not f.exists():
        continue
    if "def normalize_list_id" in f.read_text(errors="ignore"):
        count += 1
check("single normalize_list_id", count, 1)

# --- round-trip ---
# DatabaseError alias
check_true("DatabaseError is sqlite3.Error", db.DatabaseError is sqlite3.Error)
check_true("get_db_connection exists", hasattr(db, "get_db_connection"))

# Insert data
db.save_list_id("ls999", "imdb", user_id="1")
db.save_list_id("ls998", "imdb")
db.save_sync_result("Test Movie", "movie", "tt123", 101, "requested", year=2020, tmdb_id="500")
db.save_sync_result("Another Film", "movie", "tt456", 102, "requested", year=2021, tmdb_id="501")
db.save_sync_result("Synced One", "tv", "tt789", 103, "synced", year=2022)

# count after at least one save
# Check functions return expected shapes
lt = db.get_last_synced_time()
check_true("get_last_synced_time not None", lt is not None)

all_items = db.get_all_synced_items()
check_true("get_all_synced_items >=3", len(all_items) >= 3)

quality = db.get_synced_items_quality_rows()
check_true("quality rows >=3", len(quality) >= 3)

try:
    db.check_database_connection()
    check_true("check_database_connection no error", True)
except Exception as e:
    check("check_database_connection", str(e), "no error")

raw_lists = db.get_raw_lists()
check_true("get_raw_lists >=2", len(raw_lists) >= 2)

# poster urls
item_ids = [r[0] for r in all_items]
posters = db.get_poster_urls(item_ids)
check_true("get_poster_urls dict", isinstance(posters, dict))
check("get_poster_urls empty", db.get_poster_urls([]), {})

# count_item_lists maybe 0 initially but should be int
cnt = db.count_item_lists()
check_true("count_item_lists int", isinstance(cnt, int))

# insert item_lists row manually
with sqlite3.connect(db.DB_FILE) as conn:
    cur = conn.cursor()
    # ensure item_lists table exists (init should create it)
    try:
        cur.execute(
            "INSERT INTO item_lists (item_id, list_type, list_id, synced_at) VALUES (?,?,?,CURRENT_TIMESTAMP)",
            (item_ids[0], "imdb", "ls999"),
        )
        conn.commit()
    except Exception:
        pass

cnt2 = db.count_item_lists()
check_true("count_item_lists after insert >=1", cnt2 >= 1)

mapping = db.get_item_lists_for_items(item_ids[:1])
check_true("get_item_lists_for_items has key", item_ids[0] in mapping)
check("get_item_lists_for_items empty", db.get_item_lists_for_items([]), {})
if item_ids[0] in mapping:
    check_true("item_lists shape", "list_type" in mapping[item_ids[0]][0])

tmdb_map, poster_map = db.get_item_tmdb_and_posters(item_ids)
check_true("tmdb_map has entry", len(tmdb_map) >= 1)
check_true("poster_map has entry", len(poster_map) >= 1)
check("tmdb_and_posters empty", db.get_item_tmdb_and_posters([]), ({}, {}))

qr = db.query_requested_items("", "", "", 10, 0)
check_true("query_requested_items has items", "items" in qr and "total_items" in qr and "total_count" in qr)
check_true("query_requested_items total_count >=2", qr["total_count"] >= 2)
# search filter
qr2 = db.query_requested_items("Test Movie", "", "", 10, 0)
check_true("query search filters", qr2["total_items"] >= 1)

hist = db.get_historic_enrichment_rows()
check_true("historic rows >=3", len(hist) >= 3)
check_true("historic 8-tuple", len(hist[0]) == 8)

# cached images
db.save_cached_image("http://example.com/img1.jpg", b"fakeimage", mime_type="image/jpeg", source="test")
imgs = db.fetch_cached_images(10)
check_true("fetch_cached_images >=1", len(imgs) >= 1)

# replace_lists
db.replace_lists([{"type": "imdb", "id": "ls111"}, {"type": "trakt", "id": "222"}])
rl = db.get_raw_lists()
ids = [(r[0], r[1]) for r in rl]
check_true("replace_lists has ls111", ("imdb", "ls111") in ids)
check_true("replace_lists has trakt 222", ("trakt", "222") in ids)
check("replace_lists count 2", len(rl), 2)

print()
print("FAILED:", fail if fail else "none")
sys.exit(1 if fail else 0)
