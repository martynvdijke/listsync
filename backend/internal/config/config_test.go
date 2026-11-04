package config

import "testing"

func TestLoadDefaults(t *testing.T) {
	t.Setenv("LISTS_SYNC_HOST", "")
	t.Setenv("LISTS_SYNC_PORT", "")
	t.Setenv("LISTS_SYNC_DB", "")
	t.Setenv("LISTS_SYNC_ENV_FILE", "")
	t.Setenv("LISTS_SYNC_API_TOKEN", "")
	t.Setenv("CORS_ALLOWED_ORIGINS", "")
	t.Setenv("LISTS_SYNC_LEGACY_API_URL", "")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if cfg.Addr() != "127.0.0.1:4222" {
		t.Fatalf("Addr() = %q, want 127.0.0.1:4222", cfg.Addr())
	}
	if cfg.DatabasePath != "data/list_sync.db" {
		t.Fatalf("DatabasePath = %q", cfg.DatabasePath)
	}
	if cfg.LegacyAPIURL != "" {
		t.Fatalf("LegacyAPIURL = %q, want empty", cfg.LegacyAPIURL)
	}
}

func TestLoadParsesValues(t *testing.T) {
	t.Setenv("LISTS_SYNC_HOST", "0.0.0.0")
	t.Setenv("LISTS_SYNC_PORT", "4321")
	t.Setenv("LISTS_SYNC_DB", "/tmp/listsync.db")
	t.Setenv("LISTS_SYNC_API_TOKEN", "  secret  ")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://one.example, https://two.example ")
	t.Setenv("LISTS_SYNC_LEGACY_API_URL", "http://127.0.0.1:4223/")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if cfg.Addr() != "0.0.0.0:4321" {
		t.Fatalf("Addr() = %q", cfg.Addr())
	}
	if cfg.APIToken != "secret" {
		t.Fatalf("APIToken = %q", cfg.APIToken)
	}
	if len(cfg.AllowedOrigins) != 2 {
		t.Fatalf("AllowedOrigins = %#v", cfg.AllowedOrigins)
	}
	if cfg.LegacyAPIURL != "http://127.0.0.1:4223" {
		t.Fatalf("LegacyAPIURL = %q", cfg.LegacyAPIURL)
	}
}

func TestLoadRejectsInvalidPort(t *testing.T) {
	t.Setenv("LISTS_SYNC_PORT", "not-a-port")
	if _, err := Load(); err == nil {
		t.Fatal("Load() expected an error for invalid port")
	}
}

func TestLoadRejectsInvalidLegacyURL(t *testing.T) {
	t.Setenv("LISTS_SYNC_LEGACY_API_URL", "ftp://example.com")
	if _, err := Load(); err == nil {
		t.Fatal("Load() expected an error for invalid legacy URL")
	}
}
