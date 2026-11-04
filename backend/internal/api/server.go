package api

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/martynvdijke/listsync/backend/internal/store"
)

// Store is the read surface the API needs. Keeping it small makes the Go API
// testable without a database and makes the next migration slice explicit.
type Store interface {
	Ping(ctx context.Context) error
	Lists(ctx context.Context) ([]store.List, error)
	ListItems(ctx context.Context, listType, listID string) ([]store.Item, error)
	LatestSync(ctx context.Context) (*store.SyncSummary, error)
	SetupStatus(ctx context.Context) (store.SetupStatus, error)
}

// Options configures the HTTP API.
type Options struct {
	APIToken       string
	AllowedOrigins []string
	LegacyAPIURL   string
	Logger         *slog.Logger
}

// New builds the Go API handler.
func New(st Store, opts Options) (http.Handler, error) {
	logger := opts.Logger
	if logger == nil {
		logger = slog.Default()
	}

	server := &server{
		store:          st,
		token:          strings.TrimSpace(opts.APIToken),
		allowedOrigins: make(map[string]struct{}, len(opts.AllowedOrigins)),
		logger:         logger,
	}
	for _, origin := range opts.AllowedOrigins {
		server.allowedOrigins[strings.TrimRight(origin, "/")] = struct{}{}
	}

	if opts.LegacyAPIURL != "" {
		target, err := url.Parse(opts.LegacyAPIURL)
		if err != nil {
			return nil, fmt.Errorf("parse legacy API URL: %w", err)
		}
		proxy := httputil.NewSingleHostReverseProxy(target)
		proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
			logger.Error("legacy API proxy failed", "path", r.URL.Path, "error", err)
			writeError(w, http.StatusBadGateway, "legacy API unavailable")
		}
		server.legacy = proxy
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", server.handleLiveness)
	mux.HandleFunc("GET /api/system/health", server.handleHealth)
	mux.HandleFunc("GET /api/system/database/test", server.handleDatabaseTest)
	mux.HandleFunc("GET /api/setup/status", server.handleSetupStatus)
	mux.HandleFunc("GET /api/lists", server.handleLists)
	mux.HandleFunc("GET /api/lists/debug", server.handleListsDebug)
	mux.HandleFunc("GET /api/lists/", server.handleListSubresource)
	mux.HandleFunc("/api/lists/", server.handleLegacy)
	mux.HandleFunc("/api/", server.handleLegacy)
	mux.HandleFunc("/", server.handleRoot)

	return server.wrap(mux), nil
}

type server struct {
	store          Store
	token          string
	allowedOrigins map[string]struct{}
	legacy         http.Handler
	logger         *slog.Logger
}

func (s *server) wrap(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		s.setCORS(w, r)
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		if !s.authorized(r) {
			w.Header().Set("WWW-Authenticate", "Bearer")
			writeError(w, http.StatusUnauthorized, "Missing or invalid API token")
			return
		}

		recorder := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		start := time.Now()
		next.ServeHTTP(recorder, r)
		s.logger.Debug("request",
			"method", r.Method,
			"path", r.URL.Path,
			"status", recorder.status,
			"duration_ms", time.Since(start).Milliseconds(),
		)
	})
}

func (s *server) setCORS(w http.ResponseWriter, r *http.Request) {
	origin := strings.TrimRight(r.Header.Get("Origin"), "/")
	if origin == "" {
		return
	}
	if _, ok := s.allowedOrigins[origin]; !ok {
		return
	}
	w.Header().Set("Access-Control-Allow-Origin", origin)
	w.Header().Set("Access-Control-Allow-Credentials", "true")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Authorization, Content-Type")
	w.Header().Add("Vary", "Origin")
}

func (s *server) authorized(r *http.Request) bool {
	if s.token == "" || !strings.HasPrefix(r.URL.Path, "/api/") || r.URL.Path == "/api/system/health" {
		return true
	}
	scheme, value, ok := strings.Cut(r.Header.Get("Authorization"), " ")
	if !ok || !strings.EqualFold(scheme, "Bearer") {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(strings.TrimSpace(value)), []byte(s.token)) == 1
}

func (s *server) handleLiveness(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok"})
}

func (s *server) handleRoot(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"service": "listsync-go",
		"status":  "ok",
	})
}

func (s *server) handleHealth(w http.ResponseWriter, r *http.Request) {
	dbConnected := s.store.Ping(r.Context()) == nil

	latest, err := s.store.LatestSync(r.Context())
	if err != nil {
		s.logger.Error("load latest sync for health", "error", err)
	}

	status := "unknown"
	var lastSync any
	var nextSync any
	if latest != nil {
		if latest.InProgress {
			status = "in_progress"
		} else {
			status = "idle"
		}
		if latest.EndTime != nil {
			lastSync = *latest.EndTime
		} else if latest.StartTime != nil {
			lastSync = *latest.StartTime
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"database":    dbConnected,
		"process":     true,
		"sync_status": status,
		"last_sync":   lastSync,
		"next_sync":   nextSync,
	})
}

func (s *server) handleDatabaseTest(w http.ResponseWriter, r *http.Request) {
	if err := s.store.Ping(r.Context()); err != nil {
		writeJSON(w, http.StatusOK, map[string]any{
			"connected": false,
			"error":     err.Error(),
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"connected": true})
}

func (s *server) handleSetupStatus(w http.ResponseWriter, r *http.Request) {
	status, err := s.store.SetupStatus(r.Context())
	if err != nil {
		s.internalError(w, r, "load setup status", err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"is_complete":     status.IsComplete,
		"has_env":         status.HasEnv,
		"needs_migration": status.NeedsMigration,
		"settings_count":  status.SettingsCount,
	})
}

func (s *server) handleLists(w http.ResponseWriter, r *http.Request) {
	rows, err := s.store.Lists(r.Context())
	if err != nil {
		s.internalError(w, r, "load lists", err)
		return
	}

	lists := make([]map[string]any, 0, len(rows))
	for index, list := range rows {
		listURL := list.ListURL
		if listURL == "" {
			listURL = store.ConstructListURL(list.ListType, list.ListID)
		}
		lists = append(lists, map[string]any{
			"id":                index + 1,
			"list_type":         list.ListType,
			"list_id":           list.ListID,
			"list_url":          listURL,
			"display_name":      store.DisplayName(list),
			"item_count":        list.ItemCount,
			"last_synced":       list.LastSynced,
			"user_id":           list.UserID,
			"user_display_name": list.UserDisplayName,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"lists": lists})
}

func (s *server) handleListsDebug(w http.ResponseWriter, r *http.Request) {
	rows, err := s.store.Lists(r.Context())
	if err != nil {
		s.internalError(w, r, "load debug lists", err)
		return
	}

	lists := make([]map[string]any, 0, len(rows))
	raw := make([]map[string]any, 0, len(rows))
	for _, list := range rows {
		listURL := list.ListURL
		if listURL == "" {
			listURL = store.ConstructListURL(list.ListType, list.ListID)
		}
		lists = append(lists, map[string]any{
			"type":        list.ListType,
			"id":          list.ListID,
			"url":         listURL,
			"item_count":  list.ItemCount,
			"last_synced": list.LastSynced,
			"user_id":     list.UserID,
		})
		raw = append(raw, map[string]any{
			"list_type":   list.ListType,
			"list_id":     list.ListID,
			"list_url":    listURL,
			"item_count":  list.ItemCount,
			"last_synced": list.LastSynced,
		})
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"lists":             lists,
		"total_count":       len(lists),
		"raw_database_data": raw,
	})
}

func (s *server) handleListSubresource(w http.ResponseWriter, r *http.Request) {
	listType, listID, ok := parseListItemsPath(r)
	if !ok {
		// Unknown GET under /api/lists/ stays with the legacy API during the
		// migration instead of returning a misleading 404.
		s.handleLegacy(w, r)
		return
	}

	limit := 20
	if rawLimit := r.URL.Query().Get("limit"); rawLimit != "" {
		parsed, err := strconv.Atoi(rawLimit)
		if err != nil || parsed < 1 || parsed > 100 {
			writeError(w, http.StatusBadRequest, "limit must be between 1 and 100")
			return
		}
		limit = parsed
	}

	items, err := s.store.ListItems(r.Context(), listType, listID)
	if err != nil {
		s.internalError(w, r, "load list items", err)
		return
	}

	total := len(items)
	if len(items) > limit {
		items = items[:limit]
	}
	if items == nil {
		items = []store.Item{}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items":    items,
		"total":    total,
		"limit":    limit,
		"has_more": total > limit,
	})
}

// parseListItemsPath reads the raw escaped path because full list URLs are
// encoded as one segment by the Nuxt client (`%2F`). Go's URL.Path decodes
// those slashes, so using it here would split a single list ID into many path
// segments.
func parseListItemsPath(r *http.Request) (string, string, bool) {
	escaped := r.URL.EscapedPath()
	const prefix = "/api/lists/"
	if !strings.HasPrefix(escaped, prefix) || !strings.HasSuffix(escaped, "/items") {
		return "", "", false
	}

	rest := strings.TrimSuffix(strings.TrimPrefix(escaped, prefix), "/items")
	slash := strings.IndexByte(rest, '/')
	if slash <= 0 || slash == len(rest)-1 {
		return "", "", false
	}

	listType, err := url.PathUnescape(rest[:slash])
	if err != nil {
		return "", "", false
	}
	listID, err := url.PathUnescape(rest[slash+1:])
	if err != nil || listID == "" {
		return "", "", false
	}
	return listType, listID, true
}

func (s *server) handleLegacy(w http.ResponseWriter, r *http.Request) {
	if s.legacy == nil {
		writeError(w, http.StatusNotFound, "not found")
		return
	}
	s.legacy.ServeHTTP(w, r)
}

func (s *server) internalError(w http.ResponseWriter, r *http.Request, operation string, err error) {
	s.logger.Error(operation, "path", r.URL.Path, "error", err)
	writeError(w, http.StatusInternalServerError, "internal server error")
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]any{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil && !errors.Is(err, context.Canceled) {
		slog.Default().Warn("write JSON response", "error", err)
	}
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(status int) {
	r.status = status
	r.ResponseWriter.WriteHeader(status)
}
