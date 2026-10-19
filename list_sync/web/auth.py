"""Optional shared-secret authentication for the ListSync API.

The Nuxt server proxies browser requests and adds the bearer token server-side,
so the token never reaches the browser. The backend enforces the token whenever
``LISTS_SYNC_API_TOKEN`` is set. Health checks stay public so container
orchestrators can probe liveness without credentials.
"""

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Probes must work without credentials so Docker/compose health checks keep
# working when a token is configured.
PUBLIC_PATHS = frozenset({"/api/system/health"})


def configured_token() -> str:
    """Return the configured API token, or an empty string when auth is off."""
    return os.getenv("LISTS_SYNC_API_TOKEN", "").strip()


def _bearer_token(request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


class ApiTokenMiddleware(BaseHTTPMiddleware):
    """Reject API requests without a valid bearer token when one is configured."""

    async def dispatch(self, request, call_next):
        token = configured_token()
        if (
            not token
            or request.method == "OPTIONS"
            or request.url.path in PUBLIC_PATHS
            or not request.url.path.startswith("/api/")
        ):
            return await call_next(request)

        supplied = _bearer_token(request)
        if not supplied or not hmac.compare_digest(supplied, token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid API token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
