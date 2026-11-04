package api_test

import (
	"database/sql"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/martynvdijke/listsync/backend/internal/api"
	"github.com/martynvdijke/listsync/backend/internal/store"
)

// TestReadOnlyAPIWithSQLite exercises the real store against a temporary
// ListSync schema and the real API handler over HTTP. The existing server tests
// use a fake store; this test catches schema/query/wiring mistakes that a fake
// cannot.
func TestReadOnlyAPIWithSQLite(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "list_sync.db")
	createIntegrationDatabase(t, dbPath)

	envFile := filepath.Join(t.TempDir(), ".env")
	if err := os.WriteFile(envFile, []byte("A=1\n"), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}

	st, err := store.Open(dbPath, envFile)
	if err != nil {
		t.Fatalf("store.Open() error = %v", err)
	}
	t.Cleanup(func() { _ = st.Close() })

	var legacyRequestURI string
	legacy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		legacyRequestURI = r.URL.RequestURI()
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"from":"python"}`)
	}))
	t.Cleanup(legacy.Close)

	handler, err := api.New(st, api.Options{
		APIToken:       "secret",
		AllowedOrigins: []string{"https://listsync.vandijke.xyz"},
		LegacyAPIURL:   legacy.URL,
	})
	if err != nil {
		t.Fatalf("api.New() error = %v", err)
	}

	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	client := server.Client()

	t.Run("health is public", func(t *testing.T) {
		status, body := integrationGet(t, client, server.URL+"/api/system/health", "")
		if status != http.StatusOK {
			t.Fatalf("status = %d, body = %s", status, body)
		}
		response := decodeJSON(t, body)
		if response["database"] != true || response["process"] != true || response["sync_status"] != "idle" {
			t.Fatalf("health = %#v", response)
		}
		if response["last_sync"] != "2026-11-03T12:01:00Z" {
			t.Fatalf("last_sync = %#v", response["last_sync"])
		}
	})

	t.Run("lists require a token", func(t *testing.T) {
		status, body := integrationGet(t, client, server.URL+"/api/lists", "")
		if status != http.StatusUnauthorized {
			t.Fatalf("status = %d, body = %s", status, body)
		}
		if decodeJSON(t, body)["detail"] != "Missing or invalid API token" {
			t.Fatalf("body = %s", body)
		}
	})

	t.Run("lists read from sqlite", func(t *testing.T) {
		status, body := integrationGet(t, client, server.URL+"/api/lists", "secret")
		if status != http.StatusOK {
			t.Fatalf("status = %d, body = %s", status, body)
		}
		response := decodeJSON(t, body)
		lists, ok := response["lists"].([]any)
		if !ok || len(lists) != 2 {
			t.Fatalf("lists = %#v", response["lists"])
		}
		first := lists[0].(map[string]any)
		if first["id"] != float64(1) || first["list_type"] != "imdb" || first["display_name"] != "watchlist" {
			t.Fatalf("first list = %#v", first)
		}
		if first["user_display_name"] != "Martijn" || first["item_count"] != float64(2) {
			t.Fatalf("first list = %#v", first)
		}
	})

	t.Run("encoded list URL reads items", func(t *testing.T) {
		listID := url.PathEscape("https://www.imdb.com/user/ur35378749/watchlist")
		if !strings.Contains(listID, "%2F") {
			t.Fatalf("url.PathEscape() did not encode slashes: %q", listID)
		}
		status, body := integrationGet(t, client, server.URL+"/api/lists/imdb/"+listID+"/items?limit=1", "secret")
		if status != http.StatusOK {
			t.Fatalf("status = %d, body = %s", status, body)
		}
		response := decodeJSON(t, body)
		items, ok := response["items"].([]any)
		if !ok || len(items) != 1 {
			t.Fatalf("items = %#v", response["items"])
		}
		if response["total"] != float64(2) || response["limit"] != float64(1) || response["has_more"] != true {
			t.Fatalf("pagination = %#v", response)
		}
		first := items[0].(map[string]any)
		if first["title"] != "Arrival" || first["poster_url"] != "https://img/arrival.jpg" {
			t.Fatalf("first item = %#v", first)
		}
	})

	t.Run("setup status reads sqlite", func(t *testing.T) {
		status, body := integrationGet(t, client, server.URL+"/api/setup/status", "secret")
		if status != http.StatusOK {
			t.Fatalf("status = %d, body = %s", status, body)
		}
		response := decodeJSON(t, body)
		if response["is_complete"] != true || response["has_env"] != true || response["settings_count"] != float64(2) || response["needs_migration"] != false {
			t.Fatalf("setup status = %#v", response)
		}
	})

	t.Run("unimplemented route falls back to python", func(t *testing.T) {
		status, body := integrationGet(t, client, server.URL+"/api/unknown?x=1", "secret")
		if status != http.StatusOK {
			t.Fatalf("status = %d, body = %s", status, body)
		}
		if strings.TrimSpace(string(body)) != `{"from":"python"}` {
			t.Fatalf("body = %q", body)
		}
		if legacyRequestURI != "/api/unknown?x=1" {
			t.Fatalf("legacy request URI = %q", legacyRequestURI)
		}
	})

	t.Run("allowed origin is reflected", func(t *testing.T) {
		request, err := http.NewRequest(http.MethodOptions, server.URL+"/api/lists", nil)
		if err != nil {
			t.Fatalf("new request: %v", err)
		}
		request.Header.Set("Origin", "https://listsync.vandijke.xyz")
		request.Header.Set("Access-Control-Request-Method", http.MethodGet)
		response, err := client.Do(request)
		if err != nil {
			t.Fatalf("preflight: %v", err)
		}
		defer response.Body.Close()
		if response.StatusCode != http.StatusNoContent {
			t.Fatalf("status = %d", response.StatusCode)
		}
		if got := response.Header.Get("Access-Control-Allow-Origin"); got != "https://listsync.vandijke.xyz" {
			t.Fatalf("Access-Control-Allow-Origin = %q", got)
		}
	})
}

func createIntegrationDatabase(t *testing.T, path string) {
	t.Helper()

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

	if _, err := db.Exec(`
		INSERT INTO overseerr_users (id, display_name) VALUES ('1', 'Martijn');
		INSERT INTO lists (list_type, list_id, list_url, item_count, last_synced, user_id)
		VALUES ('imdb', 'https://www.imdb.com/user/ur35378749/watchlist', 'https://www.imdb.com/user/ur35378749/watchlist', 2, '2026-11-03 12:00:00', '1'),
		       ('trakt', '123', 'https://trakt.tv/lists/123', 0, NULL, '2');
		INSERT INTO synced_items (title, media_type, year, imdb_id, tmdb_id, overseerr_id, status, last_synced, poster_url)
		VALUES ('Arrival', 'movie', 2016, 'tt2543164', '329865', 55, 'requested', '2026-11-03 12:00:00', 'https://img/arrival.jpg'),
		       ('Severance', 'tv', 2022, 'tt11280740', '95396', 56, 'available', '2026-11-03 11:00:00', NULL);
		INSERT INTO item_lists (item_id, list_type, list_id)
		VALUES (1, 'imdb', 'https://www.imdb.com/user/ur35378749/watchlist'), (2, 'imdb', 'https://www.imdb.com/user/ur35378749/watchlist');
		INSERT INTO sync_history (session_id, sync_type, in_progress, start_time, end_time, status)
		VALUES ('20261103_120000_abcd', 'full', 0, '2026-11-03 12:00:00', '2026-11-03 12:01:00', 'completed');
		INSERT INTO setup_status (id, is_completed) VALUES (1, 1);
		INSERT INTO app_settings (key, value) VALUES ('one', '1'), ('two', '2');
	`); err != nil {
		t.Fatalf("seed database: %v", err)
	}
}

func integrationGet(t *testing.T, client *http.Client, target, token string) (int, []byte) {
	t.Helper()

	request, err := http.NewRequest(http.MethodGet, target, nil)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	response, err := client.Do(request)
	if err != nil {
		t.Fatalf("GET %s: %v", target, err)
	}
	defer response.Body.Close()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("read response: %v", err)
	}
	return response.StatusCode, body
}

func decodeJSON(t *testing.T, body []byte) map[string]any {
	t.Helper()

	var value map[string]any
	if err := json.Unmarshal(body, &value); err != nil {
		t.Fatalf("decode response %q: %v", body, err)
	}
	return value
}
