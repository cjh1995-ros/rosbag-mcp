# PROJECT KNOWLEDGE BASE

**Generated:** 2026-02-07
**Commit:** d68d4ae
**Branch:** main
**Version:** 0.2.0

## OVERVIEW

MCP (Model Context Protocol) server exposing 30 tools for analyzing ROS 1/2 bag files (.bag, .mcap, .db3) via LLMs. Python 3.10+, built with `mcp` SDK + `rosbags` library. Features tiered caching system for performance, YAML-based configuration, and comprehensive sensor analysis tools. Published on PyPI as `rosbag-mcp`.

## STRUCTURE

```
rosbag-mcp/
├── pyproject.toml           # hatchling build, ruff config, CLI entry point, optional pyyaml dep
├── uv.lock                  # dependency lock (uv package manager)
├── src/rosbag_mcp/
│   ├── __init__.py          # version 0.2.0
│   ├── server.py            # MCP server: 30 tool definitions, handlers, stdio entrypoint
│   ├── cache.py             # Tiered cache: SizeAwareSLRU, TopicTimeIndex, BagCacheManager
│   ├── config.py            # ServerConfig, SchemaManager (YAML-based, graceful degradation)
│   ├── bag_reader.py        # Bag I/O with cache integration: metadata, schemas, time indexes
│   ├── default_config.yaml  # Server settings (cache_max_open, cache_idle_ttl)
│   ├── message_schemas.yaml # ROS message type schemas (Odometry, LaserScan, etc.)
│   └── tools/
│       ├── __init__.py      # Re-exports all 30 tool functions
│       ├── utils.py         # json_serialize, get_nested_field, extract_position/velocity
│       ├── core.py          # set_bag_path, list_bags, bag_info
│       ├── messages.py      # get_message_at_time, get_messages_in_range, search_messages (enhanced)
│       ├── filter.py        # filter_bag (ROS1 Writer / ROS2 Writer)
│       ├── analysis.py      # trajectory (enhanced), lidar, logs, tf_tree, image (enhanced)
│       ├── sensors.py       # PointCloud2, JointState, Diagnostics analysis (NEW)
│       ├── visualization.py # matplotlib plots (timeseries, 2d, lidar polar, comparison)
│       └── advanced.py      # IMU, topic stats, compare, CSV export, events, nav health, costmap, wheel slip, lidar timeseries
├── tests/                   # Regression tests + benchmarks (NEW)
│   ├── conftest.py          # Mock fixtures for ROS messages
│   ├── test_cache.py        # SizeAwareSLRU, TopicTimeIndex, BagKey tests (17 tests)
│   ├── test_bag_reader.py   # Public API, _msg_to_dict tests (8 tests)
│   ├── test_tools.py        # Utils, importability tests (16 tests)
│   └── test_benchmarks.py   # Performance benchmarks (5 benchmarks)
└── images/                  # README screenshots
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new MCP tool | `server.py` (TOOL_DEFINITIONS + TOOL_HANDLERS) + new func in `tools/` | Must add to both dicts AND `tools/__init__.py` |
| Modify bag reading logic | `bag_reader.py` | All I/O goes through `AnyReader` from `rosbags.highlevel` |
| Add analysis tool | `tools/advanced.py` or new file in `tools/` | Follow async pattern, return `list[TextContent]` |
| Add visualization | `tools/visualization.py` | Uses matplotlib Agg backend, returns base64 PNG as `ImageContent` |
| Change field extraction | `tools/utils.py` | `get_nested_field` for dot-path traversal, `extract_position`/`extract_velocity` for ROS msg shapes |
| Debug bag format support | `bag_reader.py` + `rosbags` library | `AnyReader` handles .bag/.mcap/.db3 transparently |
| Run the server | `rosbag-mcp` CLI or `python -m rosbag_mcp.server` | stdio transport, JSON-RPC |

## CODE MAP

### Data Flow

```
MCP Client (Claude) ──stdio/JSON-RPC──> server.py
  └─> TOOL_HANDLERS[name](args)
        └─> tools/*.py async functions
              └─> bag_reader.py (read_messages / get_message_at_time / get_bag_info)
                    └─> cache.py (BagCacheManager)
                          └─> rosbags.highlevel.AnyReader([Path(bag)])
```

### Key Abstractions

| Symbol | File | Role |
|--------|------|------|
| `BagReaderState` | bag_reader.py | Singleton (`_state`) holding current bag/dir path |
| `BagCacheManager` | cache.py | Singleton (`_cache`) managing open bag handles + metadata caches |
| `SizeAwareSLRU` | cache.py | Segmented LRU cache with byte-based eviction and TTL |
| `TopicTimeIndex` | cache.py | Sorted nanosecond timestamps for fast bisect lookups |
| `ServerConfig` | config.py | YAML-based server configuration (cache settings) |
| `SchemaManager` | config.py | YAML-based ROS message schema provider |
| `BagInfo` | bag_reader.py | Dataclass: path, duration, timestamps, topics |
| `BagMessage` | bag_reader.py | Dataclass: topic, timestamp, data dict, msg_type |
| `read_messages()` | bag_reader.py | Generator yielding `BagMessage` with optional topic/time filters |
| `_msg_to_dict()` | bag_reader.py | Recursive converter: ROS dataclass msg -> nested dict |
| `TOOL_DEFINITIONS` | server.py | List of 30 `Tool` objects with JSON Schema inputs |
| `TOOL_HANDLERS` | server.py | Dict mapping tool name -> lambda calling async tool func |

### Tool Pattern (all tools follow this)

```python
async def tool_name(param: type, ..., bag_path: str | None = None) -> list[TextContent]:
    for msg in read_messages(bag_path=bag_path, topics=[topic], ...):
        # process msg.data (dict)
    return [TextContent(type="text", text=json_serialize(result))]
```

Visualization tools return `list[TextContent | ImageContent]` with base64-encoded PNG.

## CONVENTIONS

- **Tool registration is manual**: Every tool needs 3 touch points — `TOOL_DEFINITIONS` list, `TOOL_HANDLERS` dict (both in server.py), and `tools/__init__.py` re-export. Easy to miss one.
- **No type checking configured**: No mypy/pyright in pyproject.toml. Type hints used but not enforced.
- **Timestamps**: ROS native nanoseconds internally, converted to float seconds at API boundary (`/ 1e9`).
- **Bag path resolution**: Every tool accepts optional `bag_path`; falls back to `_state.current_bag_path` via `BagReaderState` singleton.
- **matplotlib backend**: Must use `Agg` (headless). Set at module import in visualization.py.
- **All tool functions are async** but most do synchronous I/O (rosbags is sync). The async is for MCP protocol compliance.
- **ROS message fields accessed by string keys** on dicts (not typed), e.g., `data.get("pose", {}).get("position", {})`.

## ANTI-PATTERNS (THIS PROJECT)

- **Do NOT import rosbags readers directly in tool files** — always go through `bag_reader.py` except `filter.py` which needs Writer classes.
- **Do NOT forget to add tools to all 3 locations** (TOOL_DEFINITIONS, TOOL_HANDLERS, `__init__.py`).
- **Do NOT use `plt.show()`** — server is headless. Always save to BytesIO buffer.
- **filter.py directly imports `Ros1Writer`/`Ros2Writer`** — this is the only file that bypasses bag_reader for write operations.

## COMMANDS

```bash
# Install (dev)
uv pip install -e ".[dev]"

# Run server
rosbag-mcp                    # CLI entry point
python -m rosbag_mcp.server   # Module execution

# Lint
ruff check src/ tests/        # E, F, I, W rules, 100 char line length
ruff format src/ tests/       # Format (ruff default style)

# Test
pytest tests/ -v              # 46 tests (41 regression + 5 benchmarks)
pytest tests/test_benchmarks.py -v -s  # Run benchmarks with output
```

## NOTES

- **Version 0.2.0** — Major upgrade with tiered caching, 3 new sensor tools, enhanced search/image/trajectory
- **Test coverage**: 46 tests (41 regression + 5 benchmarks), all passing
- **Cache performance**: TopicTimeIndex lookups 0.0004ms, BagCacheManager hits 0.0069ms, 21x metadata speedup
- **No CI/CD** — no GitHub Actions, Makefile, or Dockerfile
- **`advanced.py` is the largest file** (~1073 lines) containing 11 tool functions
- **`server.py` is ~801 lines** mostly due to verbose `Tool()` JSON Schema definitions
- **Build excludes**: `test_bag/`, `paper/`, `.claude/` directories excluded from sdist
- **Inspired by**: [ROSBag MCP Paper](https://arxiv.org/pdf/2511.03497) (arxiv 2511.03497)
