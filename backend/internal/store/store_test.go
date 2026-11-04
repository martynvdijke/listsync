package store

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"testing"
)

func createTestDatabase(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "list_sync.db")
	db, err := sql.Open("sqlite", "file:"+path)
	if err != nil {
		t.Fatalf("open test db: %v", err)
	}
	defer db.Close()

	schema := `
		CREATE TABLE lists (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			list_type TEXT NOT NULL,
			list_id TEXT NOT NULL,
			list_url TEXT,
			item_count INTEGER DEFAULT 0,
			last_synced TIMESTAMP,
			user_id TEXT DEFAULT '1'
		);
		CREATE TABLE overseerr_users (
			id TEXT PRIMARY KEY,
			display_name TEXT NOT NULL
		);
		CREATE TABLE synced_items (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			title TEXT NOT NULL,
			media_type TEXT NOT NULL,
			year INTEGER,
			imdb_id TEXT,
			tmdb_id TEXT,
			overseerr_id INTEGER,
			status TEXT,
			last_synced TIMESTAMP,
			poster_url TEXT
		);
		CREATE TABLE item_lists (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			item_id INTEGER NOT NULL,
			list_type TEXT NOT NULL,
			list_id TEXT NOT NULL,
			synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);
		CREATE TABLE sync_history (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			session_id TEXT UNIQUE NOT NULL,
			sync_type TEXT NOT NULL,
			in_progress INTEGER DEFAULT 1,
			start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			end_time TIMESTAMP,
			status TEXT
		);
		CREATE TABLE app_settings (
			key TEXT PRIMARY KEY,
			value TEXT NOT NULL
		);
		CREATE TABLE setup_status (
			id INTEGER PRIMARY KEY,
			is_completed INTEGER DEFAULT 0
		);
	`
	if _, err := db.Exec(schema); err != nil {
		t.Fatalf("create schema: %v", err)
	}
	return path
}

func TestOpenRequiresListSyncSchema(t *testing.T) {
	path := filepath.Join(t.TempDir(), "empty.db")
	db, err := sql.Open("sqlite", "file:"+path)
	if err != nil {
		t.Fatalf("open empty db: %v", err)
	}
	db.Close()

	if _, err := Open(path, ""); err == nil {
		t.Fatal("Open() expected an error for a database without the lists table")
	}
}

func TestListsAndItems(t *testing.T) {
	path := createTestDatabase(t)
	db, err := sql.Open("sqlite", "file:"+path)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	_, err = db.Exec(`
		INSERT INTO lists (list_type, list_id, list_url, item_count, last_synced, user_id)
		VALUES ('imdb', 'ur35378749', 'https://www.imdb.com/user/ur35378749/watchlist', 2, '2026-11-03 12:00:00', '1'),
		       ('trakt', '123', 'https://trakt.tv/lists/123', 0, NULL, '2');
		INSERT INTO overseerr_users (id, display_name) VALUES ('1', 'Martijn');
		INSERT INTO synced_items (title, media_type, year, imdb_id, tmdb_id, overseerr_id, status, last_synced, poster_url)
		VALUES ('Arrival', 'movie', 2016, 'tt2543164', '329865', 55, 'requested', '2026-11-03 12:00:00', 'https://img/arrival.jpg'),
		       ('Severance', 'tv', 2022, 'tt11280740', '95396', 56, 'available', '2026-11-03 11:00:00', NULL);
		INSERT INTO item_lists (item_id, list_type, list_id) VALUES (1, 'imdb', 'ur35378749'), (2, 'imdb', 'ur35378749');
	`)
	db.Close()
	if err != nil {
		t.Fatalf("seed db: %v", err)
	}

	st, err := Open(path, "")
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer st.Close()

	lists, err := st.Lists(context.Background())
	if err != nil {
		t.Fatalf("Lists() error = %v", err)
	}
	if len(lists) != 2 {
		t.Fatalf("len(Lists()) = %d, want 2", len(lists))
	}
	if lists[0].ListID != "ur35378749" || lists[0].ItemCount != 2 {
		t.Fatalf("first list = %#v", lists[0])
	}
	if lists[0].UserDisplayName == nil || *lists[0].UserDisplayName != "Martijn" {
		t.Fatalf("first list display name = %#v", lists[0].UserDisplayName)
	}
	if lists[1].UserDisplayName != nil {
		t.Fatalf("second list display name = %#v, want nil", lists[1].UserDisplayName)
	}

	items, err := st.ListItems(context.Background(), "imdb", "ur35378749")
	if err != nil {
		t.Fatalf("ListItems() error = %v", err)
	}
	if len(items) != 2 || items[0].Title != "Arrival" || items[0].PosterURL == nil {
		t.Fatalf("items = %#v", items)
	}
	if items[1].Title != "Severance" || items[1].PosterURL != nil {
		t.Fatalf("second item = %#v", items[1])
	}
}

func TestLatestSyncAndSetupStatus(t *testing.T) {
	path := createTestDatabase(t)
	db, err := sql.Open("sqlite", "file:"+path)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	_, err = db.Exec(`
		INSERT INTO sync_history (session_id, sync_type, in_progress, start_time, end_time, status)
		VALUES ('20261103_120000_abcd', 'full', 0, '2026-11-03 12:00:00', '2026-11-03 12:01:00', 'completed');
		INSERT INTO setup_status (id, is_completed) VALUES (1, 1);
		INSERT INTO app_settings (key, value) VALUES ('one', '1'), ('two', '2');
	`)
	db.Close()
	if err != nil {
		t.Fatalf("seed db: %v", err)
	}

	envFile := filepath.Join(t.TempDir(), ".env")
	if err := os.WriteFile(envFile, []byte("A=1\n"), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}

	st, err := Open(path, envFile)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer st.Close()

	latest, err := st.LatestSync(context.Background())
	if err != nil {
		t.Fatalf("LatestSync() error = %v", err)
	}
	if latest == nil || latest.SessionID != "20261103_120000_abcd" || latest.InProgress {
		t.Fatalf("latest = %#v", latest)
	}

	status, err := st.SetupStatus(context.Background())
	if err != nil {
		t.Fatalf("SetupStatus() error = %v", err)
	}
	if !status.IsComplete || !status.HasEnv || status.SettingsCount != 2 || status.NeedsMigration {
		t.Fatalf("status = %#v", status)
	}
}

func TestDisplayNameAndConstructListURL(t *testing.T) {
	if got := DisplayName(List{ListURL: "https://www.imdb.com/list/ls06450451/"}); got != "ls06450451" {
		t.Fatalf("DisplayName() = %q", got)
	}
	if got := DisplayName(List{ListID: "ls06450451"}); got != "ls06450451" {
		t.Fatalf("DisplayName() fallback = %q", got)
	}
	if got := ConstructListURL("imdb", "ur123"); got != "https://www.imdb.com/user/ur123/watchlist" {
		t.Fatalf("ConstructListURL(imdb) = %q", got)
	}
	if got := ConstructListURL("trakt", "trending:movies"); got != "https://trakt.tv/movies/trending" {
		t.Fatalf("ConstructListURL(trakt) = %q", got)
	}
}
