package api_test

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/martynvdijke/listsync/backend/internal/api"
	"github.com/martynvdijke/listsync/backend/internal/store"
)

type fakeStore struct {
	lists      []store.List
	items      []store.Item
	latest     *store.SyncSummary
	setup      store.SetupStatus
	pingErr    error
	listsErr   error
	itemsErr   error
	latestErr  error
	setupErr   error
	lastType   string
	lastListID string
}

func (f *fakeStore) Ping(context.Context) error { return f.pingErr }

func (f *fakeStore) Lists(context.Context) ([]store.List, error) {
	return f.lists, f.listsErr
}

func (f *fakeStore) ListItems(_ context.Context, listType, listID string) ([]store.Item, error) {
	f.lastType, f.lastListID = listType, listID
	return f.items, f.itemsErr
}

func (f *fakeStore) LatestSync(context.Context) (*store.SyncSummary, error) {
	return f.latest, f.latestErr
}

func (f *fakeStore) SetupStatus(context.Context) (store.SetupStatus, error) {
	return f.setup, f.setupErr
}

func newHandler(t *testing.T, st api.Store, opts api.Options) http.Handler {
	t.Helper()
	handler, err := api.New(st, opts)
	if err != nil {
		t.Fatalf("api.New() error = %v", err)
	}
	return handler
}

func decode(t *testing.T, recorder *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var body map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response %q: %v", recorder.Body.String(), err)
	}
	return body
}

func ptr[T any](value T) *T { return &value }

func TestHealth(t *testing.T) {
	handler := newHandler(t, &fakeStore{
		latest: &store.SyncSummary{
			SessionID: "session-1",
			Status:    ptr("completed"),
			StartTime: ptr("2026-11-03 12:00:00"),
			EndTime:   ptr("2026-11-03 12:01:00"),
		},
	}, api.Options{})

	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/system/health", nil))

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	body := decode(t, recorder)
	if body["database"] != true || body["sync_status"] != "idle" || body["last_sync"] != "2026-11-03 12:01:00" {
		t.Fatalf("body = %#v", body)
	}
}

func TestListsShape(t *testing.T) {
	handler := newHandler(t, &fakeStore{
		lists: []store.List{{
			ListType:        "imdb",
			ListID:          "ur35378749",
			ListURL:         "https://www.imdb.com/user/ur35378749/watchlist",
			ItemCount:       228,
			LastSynced:      ptr("2026-11-03 12:00:00"),
			UserID:          "1",
			UserDisplayName: ptr("Martijn"),
		}},
	}, api.Options{})

	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/lists", nil))

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	body := decode(t, recorder)
	lists, ok := body["lists"].([]any)
	if !ok || len(lists) != 1 {
		t.Fatalf("lists = %#v", body["lists"])
	}
	list := lists[0].(map[string]any)
	if list["id"] != float64(1) || list["list_type"] != "imdb" || list["display_name"] != "watchlist" {
		t.Fatalf("list = %#v", list)
	}
	if list["user_display_name"] != "Martijn" || list["item_count"] != float64(228) {
		t.Fatalf("list = %#v", list)
	}
}

func TestListItemsDecodesEncodedURL(t *testing.T) {
	fake := &fakeStore{items: []store.Item{
		{ID: 1, Title: "Arrival", MediaType: "movie", PosterURL: ptr("https://img/arrival.jpg")},
		{ID: 2, Title: "Severance", MediaType: "tv"},
	}}
	handler := newHandler(t, fake, api.Options{})

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/api/lists/imdb/https%3A%2F%2Fwww.imdb.com%2Flist%2Fls123/items?limit=1", nil)
	handler.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	if fake.lastType != "imdb" || fake.lastListID != "https://www.imdb.com/list/ls123" {
		t.Fatalf("parsed list = %q/%q", fake.lastType, fake.lastListID)
	}
	body := decode(t, recorder)
	items := body["items"].([]any)
	if len(items) != 1 || body["total"] != float64(2) || body["has_more"] != true {
		t.Fatalf("body = %#v", body)
	}
	if items[0].(map[string]any)["poster_url"] != "https://img/arrival.jpg" {
		t.Fatalf("item = %#v", items[0])
	}
}

func TestAuthToken(t *testing.T) {
	handler := newHandler(t, &fakeStore{}, api.Options{APIToken: "secret"})

	health := httptest.NewRecorder()
	handler.ServeHTTP(health, httptest.NewRequest(http.MethodGet, "/api/system/health", nil))
	if health.Code != http.StatusOK {
		t.Fatalf("public health status = %d", health.Code)
	}

	unauthorized := httptest.NewRecorder()
	handler.ServeHTTP(unauthorized, httptest.NewRequest(http.MethodGet, "/api/lists", nil))
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized status = %d", unauthorized.Code)
	}

	authorizedRequest := httptest.NewRequest(http.MethodGet, "/api/lists", nil)
	authorizedRequest.Header.Set("Authorization", "Bearer secret")
	authorized := httptest.NewRecorder()
	handler.ServeHTTP(authorized, authorizedRequest)
	if authorized.Code != http.StatusOK {
		t.Fatalf("authorized status = %d, body = %s", authorized.Code, authorized.Body.String())
	}
}

func TestLegacyFallback(t *testing.T) {
	legacy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/unknown" {
			t.Errorf("legacy path = %q", r.URL.Path)
		}
		_, _ = io.WriteString(w, `{"from":"legacy"}`)
	}))
	defer legacy.Close()

	handler := newHandler(t, &fakeStore{}, api.Options{LegacyAPIURL: legacy.URL})
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/unknown", nil))

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	if strings.TrimSpace(recorder.Body.String()) != `{"from":"legacy"}` {
		t.Fatalf("body = %q", recorder.Body.String())
	}
}

func TestCORSAllowedOrigin(t *testing.T) {
	handler := newHandler(t, &fakeStore{}, api.Options{AllowedOrigins: []string{"https://listsync.vandijke.xyz"}})
	request := httptest.NewRequest(http.MethodGet, "/api/lists", nil)
	request.Header.Set("Origin", "https://listsync.vandijke.xyz")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)

	if got := recorder.Header().Get("Access-Control-Allow-Origin"); got != "https://listsync.vandijke.xyz" {
		t.Fatalf("Access-Control-Allow-Origin = %q", got)
	}
}

func TestInternalErrorShape(t *testing.T) {
	handler := newHandler(t, &fakeStore{listsErr: errors.New("database down")}, api.Options{})
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/lists", nil))

	if recorder.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d", recorder.Code)
	}
	if body := decode(t, recorder); body["detail"] != "internal server error" {
		t.Fatalf("body = %#v", body)
	}
}
