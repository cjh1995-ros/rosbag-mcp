# Architecture Review: rosbag-mcp v0.2.0

**Reviewed:** 2026-02-07  
**Codebase:** ~4,200 lines across 14 Python files  
**Scope:** Full architecture + readability analysis

---

## Executive Summary

The codebase is well-structured for a solo-developer MCP server. The dependency graph is clean (acyclic), the cache layer is well-isolated, and the tool pattern is consistent. However, there is **one critical runtime bug** in `bag_reader.py`'s reader lifecycle, and several readability improvements would reduce maintenance burden.

### Verdict

| Area | Rating | Notes |
|------|--------|-------|
| Dependency graph | ✅ Good | Acyclic, no circular imports |
| Cache layer | ✅ Excellent | Clean abstractions, well-tested |
| Tool consistency | ✅ Good | All 30 tools follow same async pattern |
| Reader lifecycle | 🔴 Bug | `handle.reader` / `handle.close_reader()` mismatch |
| Dead code | 🟡 Warn | `config.py` (354 lines) never imported |
| Module size | 🟡 Warn | `advanced.py` (1,113 lines) and `server.py` (901 lines) |
| Docstrings | 🟡 Warn | ~60% of public functions missing docstrings |

---

## Critical: Runtime Bug in `bag_reader.py`

### The Problem

`BagHandle.open_reader()` in `cache.py` **returns** an `AnyReader` instance, and `BagHandle.close_reader()` is a **static method** that takes a `reader` argument. But `bag_reader.py` discards the return value and accesses a non-existent `handle.reader` attribute:

```python
# bag_reader.py — CURRENT (BROKEN)
handle.open_reader()          # return value discarded!
try:
    reader = handle.reader    # AttributeError — no such attribute
    ...
finally:
    handle.close_reader()     # TypeError — missing required `reader` arg
```

```python
# cache.py — BagHandle API
def open_reader(self) -> AnyReader:     # returns reader
    reader = AnyReader([Path(self.path)])
    reader.__enter__()
    return reader

@staticmethod
def close_reader(reader: AnyReader) -> None:  # takes reader arg
    reader.__exit__(None, None, None)
```

### Affected Call Sites (6 locations)

| Function | Line | Pattern |
|----------|------|---------|
| `get_bag_info()` | 121-155 | `handle.open_reader()` then `handle.reader` |
| `read_messages()` | 182-225 | Same |
| `get_message_at_time()` fast path | 248-284 | Same |
| `get_message_at_time()` slow path | 288-322 | Same |
| `get_topic_schema()` | 356-414 | Same |
| `get_topic_timestamps()` | 433-455 | Same |

### Why Tests Pass

Tests mock at the `BagCacheManager` boundary and never exercise the real `BagHandle.open_reader()` → `handle.reader` path. The bug is real but unexercised.

### Recommended Fix

Add a context manager to `BagHandle` and use it everywhere:

```python
# cache.py — ADD
from contextlib import contextmanager

class BagHandle:
    @contextmanager
    def reader_ctx(self):
        """Context manager for safe reader lifecycle."""
        reader = self.open_reader()
        try:
            yield reader
        finally:
            self.close_reader(reader)
```

```python
# bag_reader.py — REWRITE call sites to:
with handle.reader_ctx() as reader:
    # use reader
    ...
# no manual close needed
```

---

## Architecture Overview

### Dependency Graph

```
server.py (MCP protocol + tool registry)
    └─> tools/__init__.py (re-exports 30 tools)
            ├─> core.py (3)  messages.py (3)  analysis.py (5)
            ├─> advanced.py (11)  sensors.py (3)  visualization.py (4)
            └─> filter.py (1)
                    │
                    ▼
            bag_reader.py (central I/O hub)
                    │
                    ▼
            cache.py (isolated cache layer)

config.py ──── (orphaned, nothing imports it)
```

**Strengths:**
- Strictly acyclic — no circular dependencies
- Cache layer is self-contained and independently testable
- Tool modules only depend downward (toward `bag_reader`)

**Weaknesses:**
- `bag_reader.py` is a coupling bottleneck — every tool depends on it
- `config.py` is dead code
- `server.py` mixes protocol, schema definitions, and dispatch

### Module Responsibilities

| Module | Lines | Responsibility | Concern |
|--------|-------|---------------|---------|
| `server.py` | 901 | MCP protocol + 30 tool schemas + 30 handlers + startup | Monolithic |
| `bag_reader.py` | 456 | I/O hub + state + cache integration | Coupling hub |
| `cache.py` | 356 | Cache system (SLRU, indexes, handle pooling) | Clean ✅ |
| `config.py` | 354 | Configuration + schema management | Dead code |
| `advanced.py` | 1,113 | 11 analysis tools | God module |
| `analysis.py` | 502 | 5 domain-specific tools | Acceptable |
| `sensors.py` | 334 | 3 sensor tools | Clean ✅ |
| `visualization.py` | 256 | 4 plotting tools | Clean ✅ |
| `messages.py` | 149 | 3 message retrieval tools | Clean ✅ |
| `filter.py` | 75 | 1 bag filter tool | Duplicated logic |
| `core.py` | 43 | 3 basic tools | Clean ✅ |
| `utils.py` | 66 | Pure utility functions | Clean ✅ |

---

## Readability Issues (Prioritized)

### Priority 1: Reader Lifecycle (Bug)

See critical section above. Must fix.

### Priority 2: Boilerplate Response Pattern

Every single tool ends with the same pattern:

```python
return [TextContent(type="text", text=json_serialize(result))]
```

This appears 30+ times. A one-line helper eliminates it:

```python
# utils.py
def text_result(obj: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json_serialize(obj))]
```

### Priority 3: Missing Docstrings on Tool Functions

~60% of public tool functions have no docstring. The tool descriptions in `server.py` TOOL_DEFINITIONS serve as external docs, but the Python functions themselves are undocumented. At minimum, add one-line docstrings to functions in `advanced.py` that aren't self-evident from the name:

- `detect_events()` — 132 lines, complex logic
- `analyze_path_tracking()` — 153 lines
- `analyze_wheel_slip()` — 155 lines
- `analyze_navigation_health()` — 149 lines

### Priority 4: Magic Numbers

Hardcoded thresholds scattered throughout tool functions. The worst offenders:

| Location | Value | What It Means |
|----------|-------|---------------|
| `advanced.py:412` | `0.01` | Stoppage velocity threshold (m/s) |
| `advanced.py:377` | `2.0` | Anomaly z-score threshold |
| `advanced.py:800` | `253` | Costmap lethal cost threshold |
| `sensors.py:207` | `0.001` | Joint stuck velocity threshold |
| `sensors.py:231` | `100` | High effort threshold |
| `analysis.py:79` | `0.01` | Moving velocity threshold |

**Recommendation:** Define as module-level constants near the tool that uses them. No need for a central `constants.py` — keep them local:

```python
_STOPPAGE_VELOCITY_THRESHOLD = 0.01  # m/s
_ANOMALY_ZSCORE_THRESHOLD = 2.0
```

### Priority 5: Duplicated Writer Logic in `filter.py`

Lines 30-47 (ROS1 writer) and 48-66 (ROS2 writer) are near-identical. Extract a helper:

```python
def _write_filtered(writer, reader, topics, start_time, end_time):
    connections = {}
    for conn in reader.connections:
        if conn.topic in topics:
            connections[conn.topic] = writer.add_connection(conn.topic, conn.msgtype)
    count = 0
    for conn, timestamp, rawdata in reader.messages():
        if conn.topic not in topics:
            continue
        ts_sec = timestamp / 1e9
        if start_time and ts_sec < start_time:
            continue
        if end_time and ts_sec > end_time:
            continue
        writer.write(connections[conn.topic], timestamp, rawdata)
        count += 1
    return count
```

---

## Structural Recommendations

### Should `config.py` Be Deleted or Integrated?

**Recommendation: Delete.** 

Rationale:
- 354 lines of dead code increases maintenance burden
- `ServerConfig` would require un-globalizing the `_cache = BagCacheManager()` singleton (significant churn)
- `SchemaManager` duplicates every schema for ROS1/ROS2 variants
- `quaternion_to_euler()` and `downsample_array()` are utility methods misplaced on `SchemaManager`
- If config is needed later, it can be re-implemented more cleanly

### Should `advanced.py` Be Split?

**Recommendation: Not now.**

At ~4,000 total lines, the project is small enough that file count matters less than navigability. The 11 tools in `advanced.py` share imports and patterns. Splitting would create 5+ small files that each import the same things. Instead:
- Add clear section comments (already has some)
- Add one-line docstrings to each tool function
- Extract any shared helpers within the file

### Should Tool Registration Be Automated?

**Recommendation: Not yet, but document the pattern.**

The 3-point registration (TOOL_DEFINITIONS + TOOL_HANDLERS + `__init__.py`) is a footgun. For now, a comment block at the top of `server.py` documenting the pattern is sufficient. A decorator-based approach would be cleaner but adds complexity:

```python
# Future idea (not recommended now):
@register_tool(name="analyze_imu", schema={...})
async def analyze_imu(...): ...
```

---

## Action Items

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| 🔴 P0 | Fix reader lifecycle bug in `bag_reader.py` | 1h | Prevents runtime crashes |
| 🔴 P0 | Add `reader_ctx()` context manager to `BagHandle` | 30m | Makes bug impossible to reintroduce |
| 🟡 P1 | Add `text_result()` helper to `utils.py` | 15m | Reduces 30+ boilerplate lines |
| 🟡 P1 | Delete `config.py` + YAML files (dead code) | 15m | -354 lines, clearer codebase |
| 🟢 P2 | Deduplicate ROS1/ROS2 writer in `filter.py` | 20m | Cleaner, DRY |
| 🟢 P2 | Add docstrings to top 5 complex tools | 30m | Better maintainability |
| 🟢 P2 | Extract magic numbers as named constants | 30m | Self-documenting code |
| ⚪ P3 | Split `advanced.py` into domain modules | 2h | Optional, marginal benefit |
| ⚪ P3 | Automate tool registration | 4h | Optional, prevents footgun |
