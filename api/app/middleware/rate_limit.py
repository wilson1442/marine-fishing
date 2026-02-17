"""Sliding-window in-memory rate limiter middleware (120 req/min per client)."""

import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Sliding window: map client_key -> list of request timestamps
_windows: dict[str, list[float]] = defaultdict(list)

RATE_LIMIT = 120          # requests
WINDOW_SECONDS = 60       # per minute
_CLEANUP_INTERVAL = 300   # prune stale keys every 5 min
_last_cleanup = 0.0

# Paths exempt from rate limiting
_EXEMPT_PREFIXES = (
    "/weather/marine/tiles/",   # tile endpoints — high-volume by design
    "/api/v1/weather/marine/tiles/",
)


def _client_key(request: Request) -> str:
    """Identify client by API key (if present) or IP address."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"key:{api_key[:16]}"
    if request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"


def _is_same_origin(request: Request) -> bool:
    return request.headers.get("Sec-Fetch-Site") == "same-origin"


def _cleanup_stale(now: float):
    """Remove keys whose last request is older than the window."""
    global _last_cleanup
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    stale = [k for k, v in _windows.items() if not v or v[-1] < now - WINDOW_SECONDS]
    for k in stale:
        del _windows[k]


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip rate limiting for same-origin web frontend and tile endpoints
        if _is_same_origin(request):
            return await call_next(request)
        for prefix in _EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        now = time.time()
        _cleanup_stale(now)

        key = _client_key(request)
        window = _windows[key]

        # Prune timestamps outside the current window
        cutoff = now - WINDOW_SECONDS
        while window and window[0] < cutoff:
            window.pop(0)

        remaining = max(0, RATE_LIMIT - len(window))

        if remaining == 0:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={
                    "X-RateLimit-Limit": str(RATE_LIMIT),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(WINDOW_SECONDS),
                },
            )

        window.append(now)
        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(remaining - 1)
        return response
