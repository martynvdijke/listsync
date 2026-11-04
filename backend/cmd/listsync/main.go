package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/martynvdijke/listsync/backend/internal/api"
	"github.com/martynvdijke/listsync/backend/internal/config"
	"github.com/martynvdijke/listsync/backend/internal/store"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	cfg, err := config.Load()
	if err != nil {
		logger.Error("load configuration", "error", err)
		os.Exit(1)
	}

	db, err := store.Open(cfg.DatabasePath, cfg.EnvFile)
	if err != nil {
		logger.Error("open database", "path", cfg.DatabasePath, "error", err)
		os.Exit(1)
	}
	defer db.Close()

	handler, err := api.New(db, api.Options{
		APIToken:       cfg.APIToken,
		AllowedOrigins: cfg.AllowedOrigins,
		LegacyAPIURL:   cfg.LegacyAPIURL,
		Logger:         logger,
	})
	if err != nil {
		logger.Error("configure API", "error", err)
		os.Exit(1)
	}

	server := &http.Server{
		Addr:              cfg.Addr(),
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      60 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	go func() {
		logger.Info("ListSync Go API listening",
			"addr", cfg.Addr(),
			"database", cfg.DatabasePath,
			"legacy_api", cfg.LegacyAPIURL,
		)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("HTTP server failed", "error", err)
			stop()
		}
	}()

	<-ctx.Done()
	logger.Info("shutting down")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error("graceful shutdown failed", "error", err)
		os.Exit(1)
	}
}
