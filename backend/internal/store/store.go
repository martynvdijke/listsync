package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	_ "modernc.org/sqlite"
)

// ErrNotFound is returned when a requested row does not exist.
var ErrNotFound = errors.New("not found")

// List is the database representation of a configured list.
type List struct {
	ID              int64
	ListType        string
	ListID          string
	ListURL         string
	ItemCount       int
	LastSynced      *string
	UserID          string
	UserDisplayName *string
}

// Item is one synced item belonging to a list.
type Item struct {
	ID          int64   `json:"id"`
	Title       string  `json:"title"`
	MediaType   string  `json:"media_type"`
	Year        *int64  `json:"year"`
	IMDbID      *string `json:"imdb_id"`
	TMDbID      *string `json:"tmdb_id"`
	OverseerrID *int64  `json:"overseerr_id"`
	Status      *string `json:"status"`
	LastSynced  *string `json:"last_synced"`
	PosterURL   *string `json:"poster_url"`
}

// SyncSummary is the small subset of sync_history the health and status
// endpoints need. It is intentionally not the full session shape the Python
// report API returns.
type SyncSummary struct {
	SessionID  string
	SyncType   string
	Status     *string
	StartTime  *string
	EndTime    *string
	InProgress bool
}

// SetupStatus mirrors GET /api/setup/status.
type SetupStatus struct {
	IsComplete     bool
	HasEnv         bool
	SettingsCount  int
	NeedsMigration bool
}

// Store is a read-first SQLite store for the Go API.
type Store struct {
	db      *sql.DB
	envFile string
}

// Open opens the existing ListSync SQLite database.
//
// The Go service is being introduced beside the Python service. It does not
// create or migrate the schema yet; it verifies that the database it was
// pointed at is a ListSync database and then serves reads from it.
func Open(path, envFile string) (*Store, error) {
	if strings.TrimSpace(path) == "" {
		return nil, fmt.Errorf("database path is empty")
	}

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, fmt.Errorf("create database directory: %w", err)
	}

	dsn := "file:" + path + "?_pragma=busy_timeout(5000)&_pragma=foreign_keys(1)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open sqlite database: %w", err)
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)

	store := &Store{db: db, envFile: envFile}
	if err := store.Ping(context.Background()); err != nil {
		_ = db.Close()
		return nil, err
	}
	if err := store.requireSchema(context.Background()); err != nil {
		_ = db.Close()
		return nil, err
	}
	return store, nil
}

// Close releases the database connection.
func (s *Store) Close() error {
	return s.db.Close()
}

// Ping checks that SQLite answers.
func (s *Store) Ping(ctx context.Context) error {
	if err := s.db.PingContext(ctx); err != nil {
		return fmt.Errorf("sqlite ping: %w", err)
	}
	return nil
}

func (s *Store) requireSchema(ctx context.Context) error {
	var name string
	err := s.db.QueryRowContext(ctx, "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'lists'").Scan(&name)
	if errors.Is(err, sql.ErrNoRows) {
		return fmt.Errorf("database does not contain the ListSync lists table")
	}
	if err != nil {
		return fmt.Errorf("inspect database schema: %w", err)
	}
	return nil
}

// Lists returns every configured list in the same order as the Python query.
func (s *Store) Lists(ctx context.Context) ([]List, error) {
	users, _ := s.overseerrUsers(ctx)

	rows, err := s.db.QueryContext(ctx, `
		SELECT id, list_type, list_id, COALESCE(list_url, ''),
		       COALESCE(item_count, 0), last_synced, COALESCE(user_id, '1')
		FROM lists
		ORDER BY id
	`)
	if err != nil {
		return nil, fmt.Errorf("query lists: %w", err)
	}
	defer rows.Close()

	lists := make([]List, 0)
	for rows.Next() {
		var list List
		if err := rows.Scan(
			&list.ID,
			&list.ListType,
			&list.ListID,
			&list.ListURL,
			&list.ItemCount,
			&list.LastSynced,
			&list.UserID,
		); err != nil {
			return nil, fmt.Errorf("scan list: %w", err)
		}
		if displayName, ok := users[list.UserID]; ok {
			list.UserDisplayName = &displayName
		}
		lists = append(lists, list)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate lists: %w", err)
	}
	return lists, nil
}

func (s *Store) overseerrUsers(ctx context.Context) (map[string]string, error) {
	rows, err := s.db.QueryContext(ctx, "SELECT id, display_name FROM overseerr_users")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	users := make(map[string]string)
	for rows.Next() {
		var id, displayName string
		if err := rows.Scan(&id, &displayName); err != nil {
			return nil, err
		}
		users[id] = displayName
	}
	return users, rows.Err()
}

// ListItems returns all items joined through item_lists.
func (s *Store) ListItems(ctx context.Context, listType, listID string) ([]Item, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT si.id, si.title, si.media_type, si.year, si.imdb_id, si.tmdb_id,
		       si.overseerr_id, si.status, si.last_synced, si.poster_url
		FROM synced_items si
		INNER JOIN item_lists il ON si.id = il.item_id
		WHERE il.list_type = ? AND il.list_id = ?
		ORDER BY si.last_synced DESC, si.id DESC
	`, listType, listID)
	if err != nil {
		return nil, fmt.Errorf("query list items: %w", err)
	}
	defer rows.Close()

	items := make([]Item, 0)
	for rows.Next() {
		var item Item
		if err := rows.Scan(
			&item.ID,
			&item.Title,
			&item.MediaType,
			&item.Year,
			&item.IMDbID,
			&item.TMDbID,
			&item.OverseerrID,
			&item.Status,
			&item.LastSynced,
			&item.PosterURL,
		); err != nil {
			return nil, fmt.Errorf("scan list item: %w", err)
		}
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate list items: %w", err)
	}
	return items, nil
}

// LatestSync returns the newest sync_history row, if one exists.
func (s *Store) LatestSync(ctx context.Context) (*SyncSummary, error) {
	var summary SyncSummary
	var inProgress int
	err := s.db.QueryRowContext(ctx, `
		SELECT session_id, sync_type, status, start_time, end_time, COALESCE(in_progress, 0)
		FROM sync_history
		ORDER BY start_time DESC, id DESC
		LIMIT 1
	`).Scan(
		&summary.SessionID,
		&summary.SyncType,
		&summary.Status,
		&summary.StartTime,
		&summary.EndTime,
		&inProgress,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("query latest sync: %w", err)
	}
	summary.InProgress = inProgress != 0
	return &summary, nil
}

// SetupStatus returns the setup wizard state.
func (s *Store) SetupStatus(ctx context.Context) (SetupStatus, error) {
	status := SetupStatus{}
	_ = s.db.QueryRowContext(ctx, "SELECT is_completed FROM setup_status WHERE id = 1").Scan(&status.IsComplete)
	_ = s.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM app_settings").Scan(&status.SettingsCount)

	if s.envFile != "" {
		if _, err := os.Stat(s.envFile); err == nil {
			status.HasEnv = true
		}
	}
	status.NeedsMigration = status.HasEnv && !status.IsComplete && status.SettingsCount < 5
	return status, nil
}

// DisplayName returns the short label the dashboard shows for a list.
func DisplayName(list List) string {
	value := list.ListURL
	if value == "" {
		value = list.ListID
	}
	value = strings.TrimRight(value, "/")
	if strings.Contains(value, "://") {
		if parsed, err := url.Parse(value); err == nil {
			parts := strings.Split(strings.Trim(parsed.Path, "/"), "/")
			if len(parts) > 0 && parts[len(parts)-1] != "" {
				return parts[len(parts)-1]
			}
		}
	}
	return value
}

// ConstructListURL provides the same fallback URL the Python service uses when
// older rows have no list_url stored.
func ConstructListURL(listType, listID string) string {
	if strings.HasPrefix(listID, "http://") || strings.HasPrefix(listID, "https://") {
		return listID
	}
	switch strings.ToLower(listType) {
	case "imdb":
		if listID == "top" || listID == "boxoffice" || listID == "moviemeter" || listID == "tvmeter" {
			return "https://www.imdb.com/chart/" + listID
		}
		if strings.HasPrefix(listID, "ur") {
			return "https://www.imdb.com/user/" + listID + "/watchlist"
		}
		return "https://www.imdb.com/list/" + listID
	case "trakt", "trakt_special":
		if strings.Contains(listID, ":") {
			parts := strings.SplitN(listID, ":", 2)
			if len(parts) == 2 {
				if strings.EqualFold(parts[1], "movies") {
					return "https://trakt.tv/movies/" + parts[0]
				}
				if strings.EqualFold(parts[1], "shows") || strings.EqualFold(parts[1], "tv") {
					return "https://trakt.tv/shows/" + parts[0]
				}
			}
		}
		return "https://trakt.tv/lists/" + listID
	case "letterboxd":
		return "https://letterboxd.com/" + listID
	case "mdblist":
		return "https://mdblist.com/lists/" + listID
	}
	return listID
}
