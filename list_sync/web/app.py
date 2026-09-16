"""FastAPI application for the ListSync Web UI API.

The app is assembled here from domain routers (see ``list_sync/web/routers``) and
non-HTTP logic lives in ``list_sync/web/services``. ``api_server.py`` is a thin
compatibility shim exposing ``app`` so ``uvicorn api_server:app`` keeps working.
"""

import logging
import os
import time
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from list_sync.database import init_database

# Global variable to track server start time
SERVER_START_TIME = None


async def startup_event():
    """Set the server start time when the FastAPI app starts"""
    global SERVER_START_TIME

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # Ensure database schema is up to date (creates new tables/columns if missing)
    try:
        init_database()
        logging.info("Database initialized / schema verified successfully at startup")
    except Exception as e:
        logging.exception(f"Failed to initialize database on startup: {e}")
        raise

    SERVER_START_TIME = time.time()
    logging.info(f"🚀 API Server started at: {datetime.fromtimestamp(SERVER_START_TIME).isoformat()}")
    logging.info("📊 Dashboard available at: http://localhost:3222")


def get_allowed_origins():
    """Get allowed origins from environment or use defaults"""
    env_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")

    if env_origins:
        # If environment variable is set, use it (comma-separated)
        return [origin.strip() for origin in env_origins.split(",")]

    # Default origins for development
    default_origins = [
        "http://localhost:3222",
        "http://localhost:4222",
        "http://0.0.0.0:3222",
        "http://0.0.0.0:4222",
        "http://127.0.0.1:3222",
        "http://127.0.0.1:4222",
    ]

    # Add common local network patterns
    for i in range(1, 255):
        default_origins.extend(
            [
                f"http://192.168.1.{i}:3222",
                f"http://192.168.1.{i}:4222",
            ]
        )

    return default_origins


async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Importable and callable without starting background work or binding a port.
    """
    # Imported inside the factory so the routers (and their service dependencies)
    # are only loaded when an app is actually built.
    from list_sync.web.routers import (  # noqa: PLC0415
        analytics,
        collections,
        images,
        lists,
        logs,
        settings,
        sync,
        sync_history,
        system,
    )

    app = FastAPI(
        title="ListSync Web UI API",
        description="REST API for ListSync media synchronization dashboard",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_event_handler("startup", startup_event)

    # Registration order mirrors the original single-module decorator order so
    # route precedence is unchanged.
    for router in (
        analytics.router,
        system.router,
        lists.router,
        sync.router,
        collections.router,
        logs.router,
        settings.router,
        sync_history.router,
        images.router,
    ):
        app.include_router(router)

    return app
