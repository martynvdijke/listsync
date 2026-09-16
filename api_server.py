#!/usr/bin/env python3
"""Compatibility entrypoint for the ListSync Web UI API.

The application now lives in ``list_sync/web`` — ``create_app()`` plus domain
routers under ``list_sync/web/routers`` and services under
``list_sync/web/services``. This module is a thin shim so the deployed command
``uvicorn api_server:app`` keeps resolving (see the ``modularize-api-server``
change). It intentionally holds no routes.
"""

import logging

import uvicorn

from list_sync.database import DB_FILE, init_database
from list_sync.web.app import create_app, startup_event, unhandled_exception_handler
from list_sync.web.services.images import sniff_image_type

app = create_app()

# Re-exported for existing callers/tests that reference them through api_server.
__all__ = [
    "DB_FILE",
    "app",
    "create_app",
    "init_database",
    "sniff_image_type",
    "startup_event",
    "unhandled_exception_handler",
]


if __name__ == "__main__":
    logging.info("🚀 Starting ListSync Web UI API Server...")
    logging.info("📊 Dashboard will be available at: http://localhost:3222")
    logging.info("🔗 API documentation at: http://localhost:4222/docs")

    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=4222,
        reload=True,
        log_level="info",
    )
