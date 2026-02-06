"""Performance benchmarks for cache system."""

from __future__ import annotations

import random
import time
from statistics import mean, stdev

import pytest

from rosbag_mcp.cache import BagCacheManager, SizeAwareSLRU, TopicTimeIndex


def benchmark(func, iterations=3, warmup=1):
    """Run benchmark with warmup and multiple iterations."""
    # Warmup
    for _ in range(warmup):
        func()

    # Measure
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    return mean(times), stdev(times) if len(times) > 1 else 0.0


class TestCacheBenchmarks:
    """Performance benchmarks for cache components."""

    def test_benchmark_slru_vs_dict(self):
        """Benchmark SizeAwareSLRU vs plain dict."""
        n_ops = 1000

        # Benchmark SLRU
        def slru_ops():
            cache = SizeAwareSLRU[str, str](max_bytes=1_000_000)
            for i in range(n_ops):
                cache.put(f"key{i}", f"value{i}", size_bytes=100)
            for i in range(n_ops):
                cache.get(f"key{i}")

        # Benchmark dict
        def dict_ops():
            d: dict[str, str] = {}
            for i in range(n_ops):
                d[f"key{i}"] = f"value{i}"
            for i in range(n_ops):
                _ = d.get(f"key{i}")

        slru_time, slru_std = benchmark(slru_ops)
        dict_time, dict_std = benchmark(dict_ops)

        overhead = slru_time / dict_time

        print(f"\n{'=' * 60}")
        print(f"Benchmark 1: SizeAwareSLRU vs dict ({n_ops} ops)")
        print(f"{'=' * 60}")
        print(f"SLRU:     {slru_time * 1000:.2f} ± {slru_std * 1000:.2f} ms")
        print(f"dict:     {dict_time * 1000:.2f} ± {dict_std * 1000:.2f} ms")
        print(f"Overhead: {overhead:.1f}x")
        print(f"{'=' * 60}\n")

        # Assert reasonable overhead (SLRU should be within 10x of dict)
        assert overhead < 10.0, f"SLRU overhead too high: {overhead:.1f}x"

    def test_benchmark_topic_time_index_find_nearest(self):
        """Benchmark TopicTimeIndex.find_nearest with 100K timestamps."""
        # Create index with 100,000 timestamps (100 seconds at 1ms intervals)
        timestamps_ns = list(range(0, 100_000_000_000, 1_000_000))
        index = TopicTimeIndex(timestamps_ns=timestamps_ns)

        # Generate 1000 random targets
        targets = [random.randint(0, 100_000_000_000) for _ in range(1000)]
        tolerance_ns = 500_000  # 0.5ms tolerance

        def find_ops():
            for target in targets:
                index.find_nearest(target, tolerance_ns)

        avg_time, std_time = benchmark(find_ops)
        per_call_ms = (avg_time / 1000) * 1000

        print(f"\n{'=' * 60}")
        print("Benchmark 2: TopicTimeIndex.find_nearest")
        print(f"{'=' * 60}")
        print(f"Index size:   {len(timestamps_ns):,} timestamps")
        print("Lookups:      1,000")
        print(f"Total time:   {avg_time * 1000:.2f} ± {std_time * 1000:.2f} ms")
        print(f"Per lookup:   {per_call_ms:.4f} ms")
        print(f"{'=' * 60}\n")

        # Assert < 1ms per lookup
        assert per_call_ms < 1.0, f"find_nearest too slow: {per_call_ms:.4f}ms per call"

    def test_benchmark_topic_time_index_find_range(self):
        """Benchmark TopicTimeIndex.find_range with 100K timestamps."""
        timestamps_ns = list(range(0, 100_000_000_000, 1_000_000))
        index = TopicTimeIndex(timestamps_ns=timestamps_ns)

        # Generate 1000 random ranges
        ranges = []
        for _ in range(1000):
            start = random.randint(0, 90_000_000_000)
            end = start + random.randint(1_000_000, 10_000_000_000)
            ranges.append((start, end))

        def range_ops():
            for start, end in ranges:
                index.find_range(start, end)

        avg_time, std_time = benchmark(range_ops)
        per_call_ms = (avg_time / 1000) * 1000

        print(f"\n{'=' * 60}")
        print("Benchmark 3: TopicTimeIndex.find_range")
        print(f"{'=' * 60}")
        print(f"Index size:   {len(timestamps_ns):,} timestamps")
        print("Ranges:       1,000")
        print(f"Total time:   {avg_time * 1000:.2f} ± {std_time * 1000:.2f} ms")
        print(f"Per range:    {per_call_ms:.4f} ms")
        print(f"{'=' * 60}\n")

        # Assert < 1ms per range lookup
        assert per_call_ms < 1.0, f"find_range too slow: {per_call_ms:.4f}ms per call"

    def test_benchmark_bag_cache_manager_handle_reuse(self):
        """Benchmark BagCacheManager handle reuse (cache hits)."""
        from unittest.mock import patch

        manager = BagCacheManager()
        test_path = "/mock/test.bag"

        # Mock os.stat and os.path.realpath to avoid file system access
        mock_stat = type("stat_result", (), {"st_size": 1000, "st_mtime_ns": 123456789})()

        with (
            patch("os.stat", return_value=mock_stat),
            patch("os.path.realpath", return_value=test_path),
        ):
            # First call creates handle
            manager.get_handle(test_path)

            # Benchmark repeated get_handle calls (should return cached)
            def get_handle_ops():
                for _ in range(1000):
                    manager.get_handle(test_path)

            avg_time, std_time = benchmark(get_handle_ops)
            per_call_ms = (avg_time / 1000) * 1000

        print(f"\n{'=' * 60}")
        print("Benchmark 4: BagCacheManager.get_handle (cache hits)")
        print(f"{'=' * 60}")
        print("Calls:        1,000")
        print(f"Total time:   {avg_time * 1000:.2f} ± {std_time * 1000:.2f} ms")
        print(f"Per call:     {per_call_ms:.4f} ms")
        print(f"{'=' * 60}\n")

        # Assert < 0.1ms per call (dict lookup only)
        assert per_call_ms < 0.1, f"get_handle cache hit too slow: {per_call_ms:.4f}ms per call"

    def test_benchmark_metadata_cache_speedup(self):
        """Benchmark metadata cache hit vs miss simulation."""
        from rosbag_mcp.bag_reader import BagInfo

        # Simulate cache miss: create new BagInfo
        def cache_miss():
            for _ in range(1000):
                BagInfo(
                    path="/test.bag",
                    duration=100.0,
                    start_time=1000.0,
                    end_time=1100.0,
                    message_count=5000,
                    topics=[
                        {"name": "/odom", "type": "nav_msgs/msg/Odometry", "count": 2500},
                        {"name": "/scan", "type": "sensor_msgs/msg/LaserScan", "count": 2500},
                    ],
                )

        # Simulate cache hit: return existing BagInfo
        cached_info = BagInfo(
            path="/test.bag",
            duration=100.0,
            start_time=1000.0,
            end_time=1100.0,
            message_count=5000,
            topics=[
                {"name": "/odom", "type": "nav_msgs/msg/Odometry", "count": 2500},
                {"name": "/scan", "type": "sensor_msgs/msg/LaserScan", "count": 2500},
            ],
        )

        def cache_hit():
            for _ in range(1000):
                _ = cached_info

        miss_time, miss_std = benchmark(cache_miss)
        hit_time, hit_std = benchmark(cache_hit)

        speedup = miss_time / hit_time

        print(f"\n{'=' * 60}")
        print("Benchmark 5: Metadata cache hit vs miss")
        print(f"{'=' * 60}")
        print(
            f"Cache miss:   {miss_time * 1000:.2f} ± {miss_std * 1000:.2f} ms (1000 BagInfo creations)"
        )
        print(
            f"Cache hit:    {hit_time * 1000:.2f} ± {hit_std * 1000:.2f} ms (1000 cached returns)"
        )
        print(f"Speedup:      {speedup:.1f}x")
        print(f"{'=' * 60}\n")

        # Cache hit should be significantly faster
        assert speedup > 2.0, f"Cache speedup too low: {speedup:.1f}x"


if __name__ == "__main__":
    # Run benchmarks directly
    pytest.main([__file__, "-v", "-s"])
