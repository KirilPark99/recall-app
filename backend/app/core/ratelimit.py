"""Простой in-memory rate limiter (скользящее окно, один процесс)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.errors import ApiError

_lock = threading.Lock()
_buckets: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    with _lock:
        bucket = _buckets[key]
        while bucket and bucket[0] <= now - window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise ApiError(429, "RATE_LIMITED", "Слишком много запросов. Попробуйте позже.", headers={"Retry-After": str(window_seconds)})
        bucket.append(now)


def clear_rate_limits() -> None:
    with _lock:
        _buckets.clear()
