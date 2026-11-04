package config

import (
	"fmt"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config is the runtime configuration for the Go API process.
//
// It deliberately mirrors the environment variables the Python service already
// uses so the Go process can be dropped in beside it without changing the Nuxt
// proxy or the container layout.
type Config struct {
	Host            string
	Port            int
	DatabasePath    string
	EnvFile         string
	APIToken        string
	AllowedOrigins  []string
	LegacyAPIURL    string
	ShutdownTimeout time.Duration
}

// Addr returns the host:port the HTTP server should bind.
func (c Config) Addr() string {
	return net.JoinHostPort(c.Host, strconv.Itoa(c.Port))
}

// Load reads configuration from the environment.
func Load() (Config, error) {
	cfg := Config{
		Host:            envOr("LISTS_SYNC_HOST", "127.0.0.1"),
		DatabasePath:    envOr("LISTS_SYNC_DB", "data/list_sync.db"),
		EnvFile:         envOr("LISTS_SYNC_ENV_FILE", ".env"),
		APIToken:        strings.TrimSpace(os.Getenv("LISTS_SYNC_API_TOKEN")),
		AllowedOrigins:  splitList(os.Getenv("CORS_ALLOWED_ORIGINS")),
		LegacyAPIURL:    strings.TrimRight(strings.TrimSpace(os.Getenv("LISTS_SYNC_LEGACY_API_URL")), "/"),
		ShutdownTimeout: 10 * time.Second,
	}

	rawPort := envOr("LISTS_SYNC_PORT", "4222")
	port, err := strconv.Atoi(rawPort)
	if err != nil || port < 1 || port > 65535 {
		return Config{}, fmt.Errorf("LISTS_SYNC_PORT must be a number between 1 and 65535, got %q", rawPort)
	}
	cfg.Port = port

	if cfg.DatabasePath == "" {
		return Config{}, fmt.Errorf("LISTS_SYNC_DB must not be empty")
	}

	if cfg.LegacyAPIURL != "" {
		parsed, err := url.Parse(cfg.LegacyAPIURL)
		if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
			return Config{}, fmt.Errorf("LISTS_SYNC_LEGACY_API_URL must be an absolute http(s) URL, got %q", cfg.LegacyAPIURL)
		}
	}

	return cfg, nil
}

func envOr(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func splitList(value string) []string {
	parts := strings.Split(value, ",")
	result := make([]string, 0, len(parts))
	for _, part := range parts {
		if trimmed := strings.TrimSpace(part); trimmed != "" {
			result = append(result, trimmed)
		}
	}
	return result
}
