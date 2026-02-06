"""Tests for cache.py module."""

from __future__ import annotations

import time

import pytest

from rosbag_mcp.cache import BagKey, SizeAwareSLRU, TopicTimeIndex


class TestSizeAwareSLRU:
    """Test SizeAwareSLRU cache implementation."""

    def test_put_and_get(self):
        """Test basic put and get operations."""
        cache = SizeAwareSLRU[str, str](max_bytes=1000)
        cache.put("key1", "value1", size_bytes=100)
        assert cache.get("key1") == "value1"
        assert cache.hits == 1
        assert cache.misses == 0

    def test_miss(self):
        """Test cache miss."""
        cache = SizeAwareSLRU[str, str](max_bytes=1000)
        assert cache.get("nonexistent") is None
        assert cache.misses == 1
        assert cache.hits == 0

    def test_promotion_to_protected(self):
        """Test promotion from probation to protected on second access."""
        cache = SizeAwareSLRU[str, str](max_bytes=1000)
        cache.put("key1", "value1", size_bytes=100)
        # First get: still in probation
        assert cache.get("key1") == "value1"
        # Second get: promoted to protected
        assert cache.get("key1") == "value1"
        assert cache.hits == 2

    def test_eviction_when_over_budget(self):
        """Test eviction when cache exceeds max_bytes."""
        cache = SizeAwareSLRU[str, str](max_bytes=250)
        cache.put("key1", "value1", size_bytes=100)
        cache.put("key2", "value2", size_bytes=100)
        cache.put("key3", "value3", size_bytes=100)  # Should evict key1
        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_ttl_expiration(self):
        """Test TTL-based expiration."""
        cache = SizeAwareSLRU[str, str](max_bytes=1000)
        cache.put("key1", "value1", size_bytes=100, ttl_s=0.1)
        assert cache.get("key1") == "value1"
        time.sleep(0.15)
        assert cache.get("key1") is None  # Expired

    def test_byte_accounting(self):
        """Test byte accounting is accurate."""
        cache = SizeAwareSLRU[str, str](max_bytes=1000)
        cache.put("key1", "value1", size_bytes=100)
        cache.put("key2", "value2", size_bytes=200)
        assert cache.total_bytes == 300

    def test_delete(self):
        """Test delete operation."""
        cache = SizeAwareSLRU[str, str](max_bytes=1000)
        cache.put("key1", "value1", size_bytes=100)
        cache.delete("key1")
        assert cache.get("key1") is None
        assert cache.total_bytes == 0

    def test_clear(self):
        """Test clear operation."""
        cache = SizeAwareSLRU[str, str](max_bytes=1000)
        cache.put("key1", "value1", size_bytes=100)
        cache.put("key2", "value2", size_bytes=100)
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert cache.total_bytes == 0


class TestTopicTimeIndex:
    """Test TopicTimeIndex implementation."""

    def test_find_nearest_exact_match(self):
        """Test find_nearest with exact timestamp match."""
        index = TopicTimeIndex(
            timestamps_ns=[
                1_000_000_000,
                2_000_000_000,
                3_000_000_000,
                4_000_000_000,
                5_000_000_000,
            ]
        )
        result = index.find_nearest(3_000_000_000, tolerance_ns=100_000_000)
        assert result == 2  # Index 2

    def test_find_nearest_within_tolerance(self):
        """Test find_nearest within tolerance."""
        index = TopicTimeIndex(
            timestamps_ns=[
                1_000_000_000,
                2_000_000_000,
                3_000_000_000,
                4_000_000_000,
                5_000_000_000,
            ]
        )
        result = index.find_nearest(3_050_000_000, tolerance_ns=100_000_000)
        assert result == 2

    def test_find_nearest_out_of_tolerance(self):
        """Test find_nearest outside tolerance."""
        index = TopicTimeIndex(
            timestamps_ns=[
                1_000_000_000,
                2_000_000_000,
                3_000_000_000,
                4_000_000_000,
                5_000_000_000,
            ]
        )
        result = index.find_nearest(3_500_000_000, tolerance_ns=100_000_000)
        assert result is None

    def test_find_range_normal(self):
        """Test find_range with normal range."""
        index = TopicTimeIndex(
            timestamps_ns=[
                1_000_000_000,
                2_000_000_000,
                3_000_000_000,
                4_000_000_000,
                5_000_000_000,
            ]
        )
        result = index.find_range(2_000_000_000, 4_000_000_000)
        assert result == (1, 4)  # Indices 1-3 (inclusive)

    def test_find_range_empty(self):
        """Test find_range with no matches."""
        index = TopicTimeIndex(timestamps_ns=[1_000_000_000, 2_000_000_000, 3_000_000_000])
        result = index.find_range(10_000_000_000, 20_000_000_000)
        assert result == (3, 3)  # Empty range

    def test_find_range_edge_cases(self):
        """Test find_range edge cases."""
        index = TopicTimeIndex(
            timestamps_ns=[
                1_000_000_000,
                2_000_000_000,
                3_000_000_000,
                4_000_000_000,
                5_000_000_000,
            ]
        )
        # Before all timestamps
        result = index.find_range(0, 500_000_000)
        assert result == (0, 0)
        # After all timestamps
        result = index.find_range(10_000_000_000, 20_000_000_000)
        assert result == (5, 5)


class TestBagKey:
    """Test BagKey dataclass."""

    def test_equality(self):
        """Test BagKey equality."""
        key1 = BagKey(realpath="/path/to/bag.bag", size=1000, mtime_ns=123456789)
        key2 = BagKey(realpath="/path/to/bag.bag", size=1000, mtime_ns=123456789)
        assert key1 == key2

    def test_different_files(self):
        """Test BagKey inequality for different files."""
        key1 = BagKey(realpath="/path/to/bag1.bag", size=1000, mtime_ns=123456789)
        key2 = BagKey(realpath="/path/to/bag2.bag", size=2000, mtime_ns=987654321)
        assert key1 != key2

    def test_frozen(self):
        """Test BagKey is frozen (immutable)."""
        key = BagKey(realpath="/path/to/bag.bag", size=1000, mtime_ns=123456789)
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            key.realpath = "/new/path.bag"  # type: ignore
