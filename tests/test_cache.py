"""Tests for cache.py module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from rosbag_mcp.cache import BagKey, MessageCache, TopicTimeIndex


@dataclass
class FakeBagMessage:
    topic: str
    timestamp: float
    data: dict[str, Any]
    msg_type: str


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


def _make_msgs(topic: str, count: int, start_ts: float = 1.0) -> list[FakeBagMessage]:
    return [
        FakeBagMessage(
            topic=topic,
            timestamp=start_ts + i * 0.1,
            data={"value": i},
            msg_type="std_msgs/msg/Float64",
        )
        for i in range(count)
    ]


class TestMessageCache:
    def test_commit_and_get(self):
        cache = MessageCache()
        msgs = _make_msgs("/odom", 10)
        cache.commit("/odom", msgs, 800)
        assert cache.has("/odom")
        assert cache.get("/odom") is msgs
        assert cache.total_bytes == 800

    def test_get_missing_topic(self):
        cache = MessageCache()
        assert not cache.has("/odom")
        assert cache.get("/odom") is None

    def test_get_range_full(self):
        cache = MessageCache()
        msgs = _make_msgs("/odom", 10, start_ts=1.0)
        cache.commit("/odom", msgs, 800)
        result = cache.get_range("/odom", None, None)
        assert result is msgs

    def test_get_range_sliced(self):
        cache = MessageCache()
        msgs = _make_msgs("/odom", 100, start_ts=0.0)
        cache.commit("/odom", msgs, 8000)
        start_ns = int(2.0 * 1e9)
        end_ns = int(5.0 * 1e9)
        result = cache.get_range("/odom", start_ns, end_ns)
        assert result is not None
        assert all(2.0 <= m.timestamp <= 5.0 for m in result)
        assert len(result) > 0
        assert len(result) < 100

    def test_get_range_missing_topic(self):
        cache = MessageCache()
        assert cache.get_range("/odom", None, None) is None

    def test_can_cache_accepts_small(self):
        cache = MessageCache()
        assert cache.can_cache(raw_msg_size=500, msg_count=1000)

    def test_can_cache_rejects_large_message(self):
        cache = MessageCache()
        assert not cache.can_cache(raw_msg_size=200_000, msg_count=100)

    def test_can_cache_rejects_over_per_topic_budget(self):
        cache = MessageCache(max_per_topic=1000)
        assert not cache.can_cache(raw_msg_size=100, msg_count=20)

    def test_can_cache_rejects_over_total_budget(self):
        cache = MessageCache(max_bytes=5000)
        cache.commit("/a", _make_msgs("/a", 5), 4500)
        assert not cache.can_cache(raw_msg_size=100, msg_count=10)

    def test_budget_ok_tracks_total(self):
        cache = MessageCache(max_bytes=2000, max_per_topic=1500)
        cache.commit("/a", _make_msgs("/a", 5), 1000)
        assert cache.budget_ok(500)
        assert not cache.budget_ok(1500)

    def test_budget_ok_per_topic_limit(self):
        cache = MessageCache(max_per_topic=1000)
        assert cache.budget_ok(999)
        assert not cache.budget_ok(1001)

    def test_clear(self):
        cache = MessageCache()
        cache.commit("/odom", _make_msgs("/odom", 10), 800)
        cache.commit("/imu", _make_msgs("/imu", 10), 400)
        assert cache.total_bytes == 1200
        cache.clear()
        assert cache.total_bytes == 0
        assert not cache.has("/odom")
        assert not cache.has("/imu")

    def test_stats(self):
        cache = MessageCache()
        cache.commit("/odom", _make_msgs("/odom", 5), 500)
        s = cache.stats()
        assert "/odom" in s["cached_topics"]
        assert s["total_bytes"] == 500
        assert s["per_topic"]["/odom"]["messages"] == 5

    def test_multiple_topics(self):
        cache = MessageCache()
        cache.commit("/odom", _make_msgs("/odom", 10), 800)
        cache.commit("/imu", _make_msgs("/imu", 20), 400)
        assert cache.has("/odom")
        assert cache.has("/imu")
        assert cache.total_bytes == 1200
        odom = cache.get("/odom")
        imu = cache.get("/imu")
        assert odom is not None and len(odom) == 10
        assert imu is not None and len(imu) == 20
