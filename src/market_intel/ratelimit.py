from __future__ import annotations

import threading
import time

from .errors import UpstreamError


class RateLimiter:
    """Thread-safe pacing limiter: calls are spaced at least ``1/rate`` seconds apart."""

    def __init__(self, rate_per_sec: float) -> None:
        self._interval = 1.0 / rate_per_sec
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            self._next = max(now, self._next) + self._interval
        if wait > 0:
            time.sleep(wait)


class CircuitBreaker:
    """Stops calling an upstream that keeps failing, so we don't make an IP ban or rate-limit
    worse. The cache then serves stale data until the cooldown ends."""

    def __init__(self, name: str, threshold: int, cooldown_s: float) -> None:
        self.name = name
        self._threshold = threshold
        self._cooldown = cooldown_s
        self._failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self._open_until

    def before(self) -> None:
        if self.is_open:
            raise UpstreamError(f"{self.name}: circuit open after repeated failures; retry later")

    def success(self) -> None:
        with self._lock:
            self._failures = 0

    def failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._open_until = time.monotonic() + self._cooldown
                self._failures = 0
