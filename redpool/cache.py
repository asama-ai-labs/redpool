# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

import logging
import threading
import time
from typing import Callable, Dict, Generic, Optional, Tuple, TypeVar

from redpool import metrics

K = TypeVar("K")  # Key type
V = TypeVar("V")  # Value type


class InMemoryCache(Generic[K, V]):
    """A thread-safe in-memory cache with TTL support."""

    def __init__(self, ttl_seconds: int = 300, name: str = "default"):
        """Initialize the cache

        Args:
            ttl_seconds: Time to live in seconds for cache entries
            name: Label used for Prometheus cache metrics
        """
        self._cache: Dict[K, Tuple[V, float]] = {}
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._name = name
        self._last_sweep = time.time()
        self.logger = logging.getLogger("redpool.cache")

    def get(self, key: K) -> Optional[V]:
        """Get a value from the cache.

        Args:
            key: The cache key

        Returns:
            The cached value if found and not expired, None otherwise
        """
        with self._lock:
            if key not in self._cache:
                self.logger.debug(f"Cache MISS: {key}")
                metrics.CACHE_OPS.labels(
                    cache=self._name, op="get", result="miss"
                ).inc()
                return None

            value, timestamp = self._cache[key]
            if time.time() - timestamp > self._ttl_seconds:
                self.logger.debug(f"Cache EXPIRED: {key}")
                del self._cache[key]
                metrics.CACHE_OPS.labels(
                    cache=self._name, op="get", result="expired"
                ).inc()
                return None

            self.logger.debug(f"Cache HIT: {key}")
            metrics.CACHE_OPS.labels(cache=self._name, op="get", result="hit").inc()
            return value

    def set(self, key: K, value: V) -> None:
        """Set a value in the cache.

        Args:
            key: The cache key
            value: The value to cache
        """
        with self._lock:
            self.logger.debug(f"Cache SET: {key}")
            now = time.time()
            if now - self._last_sweep >= self._ttl_seconds:
                self._sweep_expired(now)
                self._last_sweep = now
            self._cache[key] = (value, now)
            metrics.CACHE_OPS.labels(cache=self._name, op="set", result="ok").inc()

    def _sweep_expired(self, now: float) -> None:
        """Drop every expired entry. Caller must hold ``self._lock``.

        Without this, an entry that is never read again stays in memory
        forever, which matters when keys are per credential or session token.
        """
        expired = [
            k for k, (_, ts) in self._cache.items() if now - ts > self._ttl_seconds
        ]
        for k in expired:
            del self._cache[k]

    def delete(self, key: K) -> None:
        """Delete a value from the cache.

        Args:
            key: The cache key to delete
        """
        with self._lock:
            self._cache.pop(key, None)

    def delete_matching(self, predicate: Callable[[K], bool]) -> int:
        """Delete every entry whose key satisfies *predicate*; return the count."""
        with self._lock:
            doomed = [k for k in self._cache if predicate(k)]
            for k in doomed:
                del self._cache[k]
            return len(doomed)

    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self.logger.debug(f"Cache CLEAR: Removing {len(self._cache)} entries")
            self._cache.clear()

    def get_or_set(self, key: K, value_func: Callable[[], V]) -> V:
        """Get a value from the cache, or compute and store it.

        The value_func is called outside the lock to avoid holding
        it during potentially slow computations.

        Args:
            key: The cache key
            value_func: Function to call to generate the value if not in cache

        Returns:
            The cached or newly generated value
        """
        value = self.get(key)
        if value is not None:
            return value
        value = value_func()
        self.set(key, value)
        return value
