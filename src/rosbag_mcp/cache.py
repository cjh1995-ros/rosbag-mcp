"""Tiered caching system for rosbag access.

Provides connection pooling (reusable AnyReader handles), metadata caching,
topic timestamp indexing, and size-aware SLRU eviction.
"""

from __future__ import annotations

import bisect
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Hashable, TypeVar

from rosbags.highlevel import AnyReader

logger = logging.getLogger(__name__)

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


# ---------------------------------------------------------------------------
# BagKey — identity of a bag on disk (invalidates when file changes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BagKey:
    realpath: str
    size: int
    mtime_ns: int


def bag_key_for(path: str | Path) -> BagKey:
    """Build a BagKey from a filesystem path (resolves symlinks)."""
    rp = os.path.realpath(str(path))
    st = os.stat(rp)
    return BagKey(realpath=rp, size=st.st_size, mtime_ns=st.st_mtime_ns)


# ---------------------------------------------------------------------------
# SizeAwareSLRU — segmented LRU with per-entry byte accounting
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry(Generic[V]):
    value: V
    size_bytes: int
    expires_at: float | None
    hits: int = 0


class SizeAwareSLRU(Generic[K, V]):
    """Segmented LRU (probation → protected) with size-based eviction and TTL.

    * New entries land in *probation*.
    * A second access promotes to *protected*.
    * Evictions drain probation first, then protected.
    """

    def __init__(self, max_bytes: int, protected_ratio: float = 0.8) -> None:
        self.max_bytes = max_bytes
        self._protected_max = int(max_bytes * protected_ratio)
        self._prob: OrderedDict[K, _CacheEntry[V]] = OrderedDict()
        self._prot: OrderedDict[K, _CacheEntry[V]] = OrderedDict()
        self._prob_bytes = 0
        self._prot_bytes = 0
        self.hits = 0
        self.misses = 0

    # -- public API ----------------------------------------------------------

    @property
    def total_bytes(self) -> int:
        return self._prob_bytes + self._prot_bytes

    def get(self, key: K) -> V | None:
        now = time.monotonic()

        # Check protected first (hot segment)
        entry = self._prot.get(key)
        if entry is not None:
            if entry.expires_at is not None and now >= entry.expires_at:
                self._del_prot(key)
                self.misses += 1
                return None
            entry.hits += 1
            self._prot.move_to_end(key)
            self.hits += 1
            return entry.value

        # Check probation
        entry = self._prob.get(key)
        if entry is None:
            self.misses += 1
            return None
        if entry.expires_at is not None and now >= entry.expires_at:
            self._del_prob(key)
            self.misses += 1
            return None

        # Promote to protected on second hit
        self._del_prob(key)
        entry.hits += 1
        self._prot[key] = entry
        self._prot_bytes += entry.size_bytes
        self._enforce()
        self.hits += 1
        return entry.value

    def put(self, key: K, value: V, size_bytes: int, ttl_s: float | None = None) -> None:
        expires_at = None if ttl_s is None else (time.monotonic() + ttl_s)
        # Remove from both segments if present
        if key in self._prot:
            self._del_prot(key)
        if key in self._prob:
            self._del_prob(key)
        entry = _CacheEntry(value=value, size_bytes=size_bytes, expires_at=expires_at)
        self._prob[key] = entry
        self._prob_bytes += entry.size_bytes
        self._enforce()

    def delete(self, key: K) -> None:
        if key in self._prot:
            self._del_prot(key)
        elif key in self._prob:
            self._del_prob(key)

    def clear(self) -> None:
        self._prob.clear()
        self._prot.clear()
        self._prob_bytes = 0
        self._prot_bytes = 0

    # -- internals -----------------------------------------------------------

    def _del_prob(self, key: K) -> None:
        entry = self._prob.pop(key)
        self._prob_bytes -= entry.size_bytes

    def _del_prot(self, key: K) -> None:
        entry = self._prot.pop(key)
        self._prot_bytes -= entry.size_bytes

    def _enforce(self) -> None:
        # Evict from probation first, then protected, until under budget.
        while self.total_bytes > self.max_bytes and self._prob:
            k = next(iter(self._prob))
            self._del_prob(k)
        while self.total_bytes > self.max_bytes and self._prot:
            k = next(iter(self._prot))
            self._del_prot(k)


# ---------------------------------------------------------------------------
# TopicTimeIndex — sorted nanosecond timestamps for fast point lookups
# ---------------------------------------------------------------------------


@dataclass
class TopicTimeIndex:
    timestamps_ns: list[int] = field(default_factory=list)

    @property
    def size_bytes(self) -> int:
        # 8 bytes per int64 + list overhead
        return len(self.timestamps_ns) * 8 + 56

    def find_nearest(self, target_ns: int, tolerance_ns: int) -> int | None:
        """Return index of closest timestamp within tolerance, or None."""
        ts = self.timestamps_ns
        if not ts:
            return None
        idx = bisect.bisect_left(ts, target_ns)
        best_idx = None
        best_diff = tolerance_ns + 1
        for candidate in (idx - 1, idx):
            if 0 <= candidate < len(ts):
                diff = abs(ts[candidate] - target_ns)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = candidate
        return best_idx if best_diff <= tolerance_ns else None

    def find_range(self, start_ns: int, end_ns: int) -> tuple[int, int]:
        """Return (start_idx, end_idx) slice covering [start_ns, end_ns]."""
        ts = self.timestamps_ns
        lo = bisect.bisect_left(ts, start_ns)
        hi = bisect.bisect_right(ts, end_ns)
        return lo, hi


# ---------------------------------------------------------------------------
# BagHandle — one open bag with its per-bag caches
# ---------------------------------------------------------------------------


class BagHandle:
    """Wraps a bag path with metadata caches.  Re-opens AnyReader on each scan."""

    def __init__(self, key: BagKey, path: str) -> None:
        self.key = key
        self.path = path
        self.last_used = time.monotonic()

        # Cached metadata (tiny, never evicted while handle alive)
        self.meta: dict[str, Any] = {}  # bag_info, schemas, etc.

        # Per-topic timestamp indexes (built during full scans)
        self.topic_indexes: dict[str, TopicTimeIndex] = {}

        # Cached connections info
        self._connections: list[Any] | None = None

    def touch(self) -> None:
        self.last_used = time.monotonic()

    def open_reader(self) -> AnyReader:
        """Create and enter a new AnyReader context for iteration."""
        reader = AnyReader([Path(self.path)])
        reader.__enter__()
        # Cache connections on first open
        if self._connections is None:
            self._connections = list(reader.connections)
        return reader

    @staticmethod
    def close_reader(reader: AnyReader) -> None:
        """Exit reader context."""
        try:
            reader.__exit__(None, None, None)
        except Exception:
            pass

    @property
    def connections(self) -> list[Any]:
        """Get connection list (opens reader briefly if needed)."""
        if self._connections is None:
            reader = self.open_reader()
            self._connections = list(reader.connections)
            self.close_reader(reader)
        return self._connections

    def get_or_build_index(self, topic: str) -> TopicTimeIndex | None:
        """Return cached topic index, or None if not yet built."""
        return self.topic_indexes.get(topic)

    def store_index(self, topic: str, index: TopicTimeIndex) -> None:
        self.topic_indexes[topic] = index
        logger.debug(
            "Cached time index for %s: %d timestamps (%.1f KB)",
            topic,
            len(index.timestamps_ns),
            index.size_bytes / 1024,
        )


# ---------------------------------------------------------------------------
# BagCacheManager — the top-level singleton
# ---------------------------------------------------------------------------


class BagCacheManager:
    """Manages open bag handles with LRU eviction and metadata caching."""

    def __init__(
        self,
        max_open: int = 3,
        idle_ttl_s: float = 300.0,
    ) -> None:
        self.max_open = max_open
        self.idle_ttl_s = idle_ttl_s
        self._handles: OrderedDict[BagKey, BagHandle] = OrderedDict()

    def get_handle(self, bag_path: str) -> BagHandle:
        """Get or create a BagHandle for the given path."""
        bag_path = os.path.expanduser(bag_path)
        key = bag_key_for(bag_path)

        # Check existing handle — validate key hasn't changed
        handle = self._handles.get(key)
        if handle is not None:
            handle.touch()
            self._handles.move_to_end(key)
            return handle

        # Check if same realpath exists under a stale key (file changed)
        for old_key in list(self._handles):
            if old_key.realpath == key.realpath and old_key != key:
                logger.info("Bag file changed on disk, invalidating cache: %s", bag_path)
                self._close_handle(old_key)
                break

        # Evict idle handles
        self._evict_idle()

        # Evict LRU if at capacity
        while len(self._handles) >= self.max_open:
            oldest_key = next(iter(self._handles))
            logger.debug("Evicting LRU bag handle: %s", oldest_key.realpath)
            self._close_handle(oldest_key)

        # Create new handle
        handle = BagHandle(key, bag_path)
        self._handles[key] = handle
        logger.info("Opened bag handle: %s", bag_path)
        return handle

    def invalidate(self, bag_path: str) -> None:
        """Close and remove handle for a specific path."""
        bag_path = os.path.expanduser(bag_path)
        try:
            key = bag_key_for(bag_path)
            self._close_handle(key)
        except (FileNotFoundError, OSError):
            pass

    def clear(self) -> None:
        """Close all handles and clear caches."""
        for key in list(self._handles):
            self._close_handle(key)
        logger.info("Cleared all bag handles")

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        return {
            "open_handles": len(self._handles),
            "max_open": self.max_open,
            "bags": [
                {
                    "path": h.path,
                    "indexed_topics": list(h.topic_indexes.keys()),
                    "cached_meta_keys": list(h.meta.keys()),
                    "idle_s": round(time.monotonic() - h.last_used, 1),
                }
                for h in self._handles.values()
            ],
        }

    def _close_handle(self, key: BagKey) -> None:
        handle = self._handles.pop(key, None)
        if handle is not None:
            logger.debug("Closed bag handle: %s", handle.path)

    def _evict_idle(self) -> None:
        now = time.monotonic()
        to_close = [k for k, h in self._handles.items() if (now - h.last_used) >= self.idle_ttl_s]
        for k in to_close:
            logger.debug("Evicting idle bag handle: %s", k.realpath)
            self._close_handle(k)
