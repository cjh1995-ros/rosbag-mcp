"""Tiered caching system for rosbag access.

Provides connection pooling (reusable AnyReader handles), metadata caching,
and topic timestamp indexing.
"""

from __future__ import annotations

import bisect
import logging
import os
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator

from rosbags.highlevel import AnyReader

logger = logging.getLogger(__name__)


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
# MessageCache — per-handle message storage with size gating
# ---------------------------------------------------------------------------

_DEFAULT_MAX_BYTES = 512 * 1024 * 1024  # 512 MB total
_DEFAULT_MAX_PER_TOPIC = 50 * 1024 * 1024  # 50 MB per topic
_RAW_SIZE_GATE = 100_000  # 100 KB — skip caching if first message exceeds this


class MessageCache:
    """Size-gated per-topic message cache.

    Stores deserialized messages for topics whose raw payload is small enough.
    Serves time-filtered queries via binary search on cached timestamps.
    """

    def __init__(
        self,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        max_per_topic: int = _DEFAULT_MAX_PER_TOPIC,
    ) -> None:
        self.max_bytes = max_bytes
        self.max_per_topic = max_per_topic
        self._topics: dict[str, list[Any]] = {}
        self._topic_bytes: dict[str, int] = {}
        self._total_bytes = 0

    def has(self, topic: str) -> bool:
        return topic in self._topics

    def can_cache(self, raw_msg_size: int, msg_count: int) -> bool:
        if raw_msg_size > _RAW_SIZE_GATE:
            return False
        estimated = raw_msg_size * msg_count
        if estimated > self.max_per_topic:
            return False
        if self._total_bytes + estimated > self.max_bytes:
            return False
        return True

    def budget_ok(self, collected_bytes: int) -> bool:
        if collected_bytes > self.max_per_topic:
            return False
        if self._total_bytes + collected_bytes > self.max_bytes:
            return False
        return True

    def commit(self, topic: str, messages: list[Any], bytes_used: int) -> None:
        self._topics[topic] = messages
        self._topic_bytes[topic] = bytes_used
        self._total_bytes += bytes_used
        logger.debug(
            "Cached %d messages for %s (%.1f KB, total %.1f MB)",
            len(messages),
            topic,
            bytes_used / 1024,
            self._total_bytes / (1024 * 1024),
        )

    def get(self, topic: str) -> list[Any] | None:
        return self._topics.get(topic)

    def get_range(self, topic: str, start_ns: int | None, end_ns: int | None) -> list[Any] | None:
        msgs = self._topics.get(topic)
        if msgs is None:
            return None
        if start_ns is None and end_ns is None:
            return msgs

        # Binary search using timestamp (stored as seconds in BagMessage)
        start_sec = start_ns / 1e9 if start_ns else None
        end_sec = end_ns / 1e9 if end_ns else None

        lo = 0
        hi = len(msgs)
        if start_sec is not None:
            lo = bisect.bisect_left([m.timestamp for m in msgs], start_sec)
        if end_sec is not None:
            hi = bisect.bisect_right([m.timestamp for m in msgs], end_sec)
        return msgs[lo:hi]

    def clear(self) -> None:
        self._topics.clear()
        self._topic_bytes.clear()
        self._total_bytes = 0

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    def stats(self) -> dict[str, Any]:
        return {
            "cached_topics": list(self._topics.keys()),
            "total_bytes": self._total_bytes,
            "per_topic": {
                t: {"messages": len(m), "bytes": self._topic_bytes.get(t, 0)}
                for t, m in self._topics.items()
            },
        }


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

        self.message_cache = MessageCache()

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

    @contextmanager
    def reader_ctx(self) -> Generator[AnyReader, None, None]:
        """Context manager for safe reader lifecycle.

        Usage::

            with handle.reader_ctx() as reader:
                for conn, ts, raw in reader.messages():
                    ...
        """
        reader = self.open_reader()
        try:
            yield reader
        finally:
            self.close_reader(reader)

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
                    "message_cache": h.message_cache.stats(),
                    "idle_s": round(time.monotonic() - h.last_used, 1),
                }
                for h in self._handles.values()
            ],
        }

    def _close_handle(self, key: BagKey) -> None:
        handle = self._handles.pop(key, None)
        if handle is not None:
            handle.message_cache.clear()
            logger.debug("Closed bag handle: %s", handle.path)

    def _evict_idle(self) -> None:
        now = time.monotonic()
        to_close = [k for k, h in self._handles.items() if (now - h.last_used) >= self.idle_ttl_s]
        for k in to_close:
            logger.debug("Evicting idle bag handle: %s", k.realpath)
            self._close_handle(k)
