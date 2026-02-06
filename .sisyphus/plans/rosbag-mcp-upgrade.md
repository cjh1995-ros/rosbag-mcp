# ROSBag MCP — Major Feature Upgrade & Performance Caching

## TL;DR

> **Quick Summary**: Integrate all features from the reference implementation (binabik-ai/mcp-rosbags) except GPS/NavSatFix, rewrite `bag_reader.py` to use the already-written tiered caching system (`cache.py`), add new sensor tools (PointCloud2, JointState, Diagnostics), enhance image/search/trajectory tools, add YAML config system, Python logging, regression tests, and performance benchmarks.
>
> **Deliverables**:
> - Rewritten `bag_reader.py` with cache integration (tiered SLRU + topic time indexes)
> - Enhanced `get_image_at_time` (CompressedImage, more encodings, smart resize)
> - Enhanced `search_messages` (contains, field_exists, cross-topic correlation)
> - Enhanced `analyze_trajectory` (angle-based waypoints, path efficiency metrics)
> - New `tools/sensors.py` (PointCloud2, JointState, DiagnosticArray analysis)
> - New `config.py` + YAML config/schema system
> - Python logging throughout all modules
> - Full server.py wiring of all new/updated tools
> - Regression tests + cache performance benchmarks
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES — 3 waves
> **Critical Path**: Task 1 → Task 2 → Task 3 (verify) → Tasks 4-8 (parallel) → Task 9 (wiring) → Task 10-12 (tests/lint)

---

## Context

### Original Request
User wants to massively upgrade rosbag-mcp by incorporating all features from the reference implementation at https://github.com/binabik-ai/mcp-rosbags (except GPS/NavSatFix), with a better-than-LRU caching system for performance, plus regression tests and performance benchmarks comparing before/after caching.

### Interview Summary
**Key Discussions**:
- Full feature comparison with reference repo completed — reference uses extractors pattern, simple LRU cache, schema YAML, image compression support
- Oracle consulted on caching architecture → designed BagKey (file identity + auto-invalidation) + SizeAwareSLRU (segmented LRU with byte accounting) + TopicTimeIndex (bisect-based timestamp lookup) + BagHandle (per-bag metadata/index caches) + BagCacheManager (connection pooling with LRU eviction)
- `cache.py` already written with the tiered caching system — currently untracked in git
- `bag_reader.py` rewrite content was prepared in a prior session — integrates cache.py
- User explicitly excluded GPS/NavSatFix support
- Test infrastructure: pytest + pytest-asyncio configured in pyproject.toml but NO test files exist

### Research Findings
- Reference repo (`binabik-ai/mcp-rosbags`) uses simple `functools.lru_cache` — our tiered SLRU is significantly more sophisticated
- PointCloud2 binary parsing requires numpy structured dtypes with field offset mapping
- CompressedImage decoding (JPEG/PNG) works natively with Pillow — no opencv needed
- `rosbags.highlevel.AnyReader` is NOT re-entrant after `.messages()` iteration — must close and reopen
- MCP SDK tool handlers are invoked via `asyncio` — but `rosbags` is synchronous internally

### Metis Review
**Identified Gaps** (addressed in plan):
- `cache.py` is untracked, not committed — must commit first before any dependent work
- `BagKey` broken for directory-based ROS2 bags (`.db3` in directories) — `os.stat()` on directories returns filesystem-dependent sizes and doesn't track content changes → fix during bag_reader integration by statting the `.db3` file inside directories
- Version mismatch: `__init__.py` says `0.1.0`, `pyproject.toml` says `0.1.1` → harmonize in preparatory commit
- `from __future__ import annotations` missing from `tools/__init__.py` and `__init__.py` → fix in preparatory commit
- `filter.py` directly imports `AnyReader` — must NOT be routed through cache (write operations)
- `_msg_to_dict()` must remain unchanged — all 24 tools depend on `BagMessage.data` being a dict
- Thread/task safety: `BagCacheManager` uses `OrderedDict` without locks — acceptable for now since MCP SDK processes tools serially, but noted for future work
- `opencv-python` must NOT be a required dependency — use Pillow for JPEG/PNG, graceful error for unsupported formats

---

## Work Objectives

### Core Objective
Upgrade rosbag-mcp from a basic bag analysis tool to a comprehensive ROS data analysis server with intelligent caching, multi-sensor support, enhanced search capabilities, and configurable behavior — matching or exceeding the reference implementation's feature set.

### Concrete Deliverables
- `src/rosbag_mcp/bag_reader.py` — Rewritten with cache integration
- `src/rosbag_mcp/tools/analysis.py` — Enhanced image + trajectory functions
- `src/rosbag_mcp/tools/messages.py` — Enhanced search with correlation
- `src/rosbag_mcp/tools/sensors.py` — NEW: PointCloud2, JointState, Diagnostics
- `src/rosbag_mcp/config.py` — NEW: ServerConfig + SchemaManager
- `src/rosbag_mcp/default_config.yaml` — NEW: Default server configuration
- `src/rosbag_mcp/message_schemas.yaml` — NEW: ROS message field schemas
- `src/rosbag_mcp/server.py` — Updated with all new tools wired in
- `src/rosbag_mcp/tools/__init__.py` — Updated with new re-exports
- `src/rosbag_mcp/__init__.py` — Version bumped
- `pyproject.toml` — Updated with optional dependencies
- `tests/conftest.py` — Test fixtures with synthetic/mock bags
- `tests/test_cache.py` — Cache unit tests
- `tests/test_bag_reader.py` — Regression tests for bag_reader
- `tests/test_tools.py` — Regression tests for tool functions
- `tests/test_benchmarks.py` — Cache performance benchmarks

### Definition of Done
- [ ] `python -c "import rosbag_mcp.server"` — No import errors
- [ ] `ruff check src/ --select E,F,I,W --target-version py310` — 0 errors
- [ ] `ruff format --check src/` — Already formatted
- [ ] `python -m pytest tests/ -v` — All tests pass, 0 failures
- [ ] All 24 existing tools + 3 new tools (27 total) registered in TOOL_DEFINITIONS, TOOL_HANDLERS, and `tools/__init__.py`
- [ ] Cache benchmark shows measurable speedup on repeated operations

### Must Have
- Tiered caching integrated into bag_reader.py
- All existing 24 tools working unchanged (backward compatible)
- CompressedImage support in get_image_at_time
- PointCloud2, JointState, DiagnosticArray analysis tools
- Enhanced search with contains, field_exists, correlation
- Enhanced trajectory with angle-based waypoints
- YAML config with Python fallback (no required PyYAML)
- Python logging in all modules
- Regression tests proving backward compatibility
- Performance benchmarks proving cache benefit

### Must NOT Have (Guardrails)
- **No GPS/NavSatFix** — Explicitly excluded by user
- **No `plt.show()`** — Server is headless; always save to BytesIO buffer
- **No `opencv-python` as required dependency** — Use Pillow for JPEG/PNG; try/except import for optional cv2
- **No `typing.Optional`** — Use `X | None` syntax (Python 3.10+)
- **No modification of cache.py logic** — Already designed by Oracle and written; only extend for directory bag fix
- **No restructuring of server.py TOOL_DEFINITIONS/TOOL_HANDLERS pattern** — Extend only, don't refactor
- **No splitting of advanced.py** — Only add to it; splitting is separate work
- **No CI/CD, mypy, or meta-tooling** — Not in scope
- **No video extraction or 3D visualization** — Image tools limited to still frames
- **No ML/clustering in PointCloud2** — Summary statistics only
- **No environment variable config overrides** — YAML + dict defaults only
- **No changing existing function signatures** — Only ADD new optional parameters
- **No changing BagMessage.data type** — Must remain `dict[str, Any]`
- **No changing read_messages() generator contract** — Must still yield `BagMessage`
- **No modifying filter.py's direct AnyReader import** — Write operations bypass cache
- **Every new `.py` file must have `from __future__ import annotations`** as first non-docstring import
- **Line length max 100 chars**, ruff rules: E, F, I, W
- **All tool functions must be `async def`** returning `list[TextContent]` or `list[TextContent | ImageContent]`

---

## Verification Strategy

> **UNIVERSAL RULE: ZERO HUMAN INTERVENTION**
>
> ALL tasks in this plan MUST be verifiable WITHOUT any human action.

### Test Decision
- **Infrastructure exists**: PARTIALLY (pytest + pytest-asyncio in dev deps, but 0 test files, no tests/ directory, no conftest.py)
- **Automated tests**: YES (tests-after — write implementation first, then tests)
- **Framework**: pytest + pytest-asyncio (already configured in pyproject.toml)

### Agent-Executed QA Scenarios (MANDATORY — ALL tasks)

Every task includes specific verification commands that the executing agent runs directly.

**Verification Tool by Deliverable Type:**

| Type | Tool | How Agent Verifies |
|------|------|-------------------|
| Python module | Bash | `python -c "from module import X; ..."` |
| Backward compat | Bash | Import all 24 existing tools, verify handler dict |
| Lint | Bash | `ruff check src/ && ruff format --check src/` |
| Tests | Bash | `python -m pytest tests/ -v --tb=short` |
| Benchmarks | Bash | `python -m pytest tests/test_benchmarks.py -v` |

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately):
└── Task 1: Preparatory commit (cache.py, version fix, __future__ imports)

Wave 2 (After Wave 1):
├── Task 2: Rewrite bag_reader.py with cache integration
└── Task 3: Create config.py + YAML schemas (independent of bag_reader rewrite)

Wave 3 (After Task 2 verified):
├── Task 4: Enhance get_image_at_time (CompressedImage, encodings, resize)
├── Task 5: Enhance search_messages (contains, field_exists, correlation)
├── Task 6: Enhance analyze_trajectory (angle waypoints, path efficiency)
├── Task 7: Create tools/sensors.py (PointCloud2, JointState, Diagnostics)
└── Task 8: Add logging to all modules

Wave 4 (After Waves 3):
└── Task 9: Wire all new/updated tools in server.py + tools/__init__.py + pyproject.toml

Wave 5 (After Wave 4):
├── Task 10: Create test infrastructure + regression tests
├── Task 11: Cache performance benchmarks
└── Task 12: Final ruff lint/format + AGENTS.md update

Critical Path: Task 1 → Task 2 → Task 9 → Task 10
Parallel Speedup: ~45% faster than sequential
```

### Dependency Matrix

| Task | Depends On | Blocks | Can Parallelize With |
|------|------------|--------|---------------------|
| 1 | None | 2, 3 | None (must go first) |
| 2 | 1 | 4, 5, 6, 7, 9 | 3 |
| 3 | 1 | 9 | 2 |
| 4 | 2 | 9 | 5, 6, 7, 8 |
| 5 | 2 | 9 | 4, 6, 7, 8 |
| 6 | 2 | 9 | 4, 5, 7, 8 |
| 7 | 2 | 9 | 4, 5, 6, 8 |
| 8 | 2 | 9 | 4, 5, 6, 7 |
| 9 | 2, 3, 4, 5, 6, 7, 8 | 10, 11 | None (integration) |
| 10 | 9 | 12 | 11 |
| 11 | 9 | 12 | 10 |
| 12 | 10, 11 | None | None (final) |

### Agent Dispatch Summary

| Wave | Tasks | Recommended Agents |
|------|-------|-------------------|
| 1 | 1 | `delegate_task(category="quick", load_skills=["git-master"])` |
| 2 | 2, 3 | `delegate_task(category="deep", ...)` in parallel |
| 3 | 4-8 | `delegate_task(category="unspecified-high", ...)` parallel |
| 4 | 9 | `delegate_task(category="unspecified-high", ...)` |
| 5 | 10, 11, 12 | `delegate_task(category="deep", ...)` parallel |

---

## TODOs

---

- [x] 1. Preparatory Commit — Stage cache.py, fix version mismatch, add missing `__future__` imports

  **What to do**:
  - `git add src/rosbag_mcp/cache.py` — stage the already-written cache module
  - Fix `src/rosbag_mcp/__init__.py`: change `__version__ = "0.1.0"` → `__version__ = "0.2.0"` (this is a major feature release)
  - Fix `pyproject.toml`: change `version = "0.1.1"` → `version = "0.2.0"`
  - Add `from __future__ import annotations` as first line in `src/rosbag_mcp/tools/__init__.py`
  - Add `from __future__ import annotations` as first non-docstring line in `src/rosbag_mcp/__init__.py`
  - Run `ruff check src/ && ruff format src/`
  - Commit all changes

  **Must NOT do**:
  - Do NOT modify cache.py logic
  - Do NOT change any existing tool function signatures
  - Do NOT modify any tool behavior

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: [`git-master`]
    - `git-master`: Atomic commit with proper message formatting

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (solo)
  - **Blocks**: Tasks 2, 3
  - **Blocked By**: None

  **References**:
  - `src/rosbag_mcp/__init__.py:3` — Current version `"0.1.0"` — change to `"0.2.0"`
  - `pyproject.toml:7` — Current version `"0.1.1"` — change to `"0.2.0"`
  - `src/rosbag_mcp/tools/__init__.py:1` — Missing `from __future__ import annotations`, currently starts with `from rosbag_mcp.tools.core import ...`
  - `src/rosbag_mcp/__init__.py:1` — Missing `from __future__ import annotations`, currently starts with docstring
  - `src/rosbag_mcp/cache.py` — Exists but untracked in git, needs staging

  **Acceptance Criteria**:
  - [ ] `git diff --cached --name-only` shows cache.py, __init__.py, pyproject.toml, tools/__init__.py
  - [ ] `python -c "from rosbag_mcp import __version__; assert __version__ == '0.2.0'"` → passes
  - [ ] `ruff check src/ --select E,F,I,W --target-version py310` → 0 errors
  - [ ] `git log -1 --oneline` shows new commit

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: All files staged and committed correctly
    Tool: Bash
    Steps:
      1. git status → working tree clean
      2. python -c "from rosbag_mcp import __version__; print(__version__); assert __version__ == '0.2.0'"
      3. python -c "import ast; t = ast.parse(open('src/rosbag_mcp/tools/__init__.py').read()); assert isinstance(t.body[0], ast.ImportFrom) and t.body[0].module == '__future__'"
      4. ruff check src/ --select E,F,I,W --target-version py310
    Expected Result: All assertions pass, 0 ruff errors
    Evidence: Command outputs captured
  ```

  **Commit**: YES
  - Message: `feat: add tiered cache module, bump version to 0.2.0`
  - Files: `src/rosbag_mcp/cache.py`, `src/rosbag_mcp/__init__.py`, `pyproject.toml`, `src/rosbag_mcp/tools/__init__.py`
  - Pre-commit: `ruff check src/ && ruff format --check src/`

---

- [ ] 2. Rewrite bag_reader.py — Integrate tiered cache system

  **What to do**:
  - Rewrite `src/rosbag_mcp/bag_reader.py` to integrate with `cache.py`
  - Add imports: `from rosbag_mcp.cache import BagCacheManager, TopicTimeIndex, bag_key_for`
  - Add module-level singleton: `_cache = BagCacheManager()` and `logger = logging.getLogger(__name__)`
  - Create helper `_resolve_path(bag_path: str | None) -> str` that replaces duplicated path resolution logic in every function
  - **Rewrite `get_bag_info()`**: Use `handle = _cache.get_handle(path)`, cache result in `handle.meta["bag_info"]`, return from cache on repeat calls. Still use `handle.open_reader()` / `handle.close_reader()` to get connections data, but cache the `BagInfo` object.
  - **Rewrite `get_topic_schema()`**: Use cached handle, cache result in `handle.meta[f"schema:{topic}"]`
  - **Rewrite `read_messages()`**: Use `handle.open_reader()` for iteration, `handle.close_reader()` after. When iterating a single topic without time filters (full scan), opportunistically build `TopicTimeIndex` by collecting timestamps during iteration and calling `handle.store_index(topic, index)` after complete iteration.
  - **Rewrite `get_message_at_time()`**: Check if `handle.get_or_build_index(topic)` exists — if so, use `index.find_nearest(target_ns, tolerance_ns)` to locate the approximate position, then do a targeted scan near that timestamp instead of scanning from the beginning. Fall back to full scan if no index.
  - **Rewrite `get_topic_timestamps()`**: If `handle.get_or_build_index(topic)` exists, return `[t / 1e9 for t in index.timestamps_ns]` immediately. Otherwise build index during full scan, cache it, return timestamps.
  - **Fix BagKey for directory-based ROS2 bags**: In `_resolve_path()` or a new helper, when the path is a directory containing `.db3` files, stat the `.db3` file(s) inside rather than the directory itself. This fixes cache invalidation for ROS2 directory bags.
  - **PRESERVE ALL public API**: Same function signatures, same return types (`BagInfo`, `BagMessage`, `Iterator[BagMessage]`, etc.), same exports (`BagInfo`, `BagMessage`, `BagReaderState`, `set_bag_path`, `get_current_bag_path`, `get_current_bags_dir`, `list_bags`, `get_bag_info`, `_msg_to_dict`, `read_messages`, `get_message_at_time`, `get_messages_in_range`, `get_topic_schema`, `get_topic_timestamps`)
  - **`_msg_to_dict()` MUST remain unchanged** — all 24 tools depend on it
  - `BagMessage.data` MUST remain `dict[str, Any]`
  - Run `ruff check src/rosbag_mcp/bag_reader.py && ruff format src/rosbag_mcp/bag_reader.py`

  **Must NOT do**:
  - Do NOT change any existing function signatures (only internal implementation)
  - Do NOT change return types
  - Do NOT modify `filter.py` or any other tool file
  - Do NOT change `_msg_to_dict()` logic at all
  - Do NOT modify cache.py (except potentially extending `bag_key_for` for directory bags)
  - Do NOT remove `BagReaderState` or `_state` singleton (still used for current path tracking)
  - Do NOT add required dependencies

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
    - No special skills needed — pure Python refactoring with careful API preservation

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 3)
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 4, 5, 6, 7, 8, 9
  - **Blocked By**: Task 1

  **References**:

  **Pattern References**:
  - `src/rosbag_mcp/bag_reader.py` (entire file, 308 lines) — Current implementation to rewrite. PRESERVE all public function signatures exactly.
  - `src/rosbag_mcp/cache.py` (entire file, 356 lines) — Cache system to integrate. Key classes: `BagCacheManager.get_handle()` → `BagHandle`, `BagHandle.open_reader()` / `close_reader()`, `BagHandle.meta` dict, `BagHandle.topic_indexes` dict, `BagHandle.store_index()`, `TopicTimeIndex.find_nearest()` / `find_range()`

  **API References**:
  - `src/rosbag_mcp/bag_reader.py:11-26` — `BagInfo` and `BagMessage` dataclass definitions — MUST NOT CHANGE
  - `src/rosbag_mcp/bag_reader.py:29-34` — `BagReaderState` and `_state` singleton — MUST KEEP
  - `src/rosbag_mcp/bag_reader.py:37-48` — `set_bag_path()` — signature unchanged
  - `src/rosbag_mcp/bag_reader.py:128-140` — `_msg_to_dict()` — MUST NOT CHANGE at all
  - `src/rosbag_mcp/bag_reader.py:143-174` — `read_messages()` — signature unchanged, still yields `BagMessage`
  - `src/rosbag_mcp/bag_reader.py:177-212` — `get_message_at_time()` — signature unchanged
  - `src/rosbag_mcp/bag_reader.py:290-307` — `get_topic_timestamps()` — signature unchanged

  **Integration References**:
  - `src/rosbag_mcp/cache.py:280-312` — `BagCacheManager.get_handle()` — returns `BagHandle`, evicts idle/LRU handles
  - `src/rosbag_mcp/cache.py:223-230` — `BagHandle.open_reader()` — creates AnyReader, calls `__enter__()`, caches connections
  - `src/rosbag_mcp/cache.py:232-238` — `BagHandle.close_reader()` — calls `__exit__()` with error suppression
  - `src/rosbag_mcp/cache.py:174-188` — `TopicTimeIndex.find_nearest()` — bisect-based nearest timestamp lookup
  - `src/rosbag_mcp/cache.py:38-42` — `bag_key_for()` — builds BagKey from path; needs directory fix

  **Downstream Dependency References** (what breaks if API changes):
  - `src/rosbag_mcp/tools/analysis.py:11-14` — imports `get_message_at_time`, `read_messages` from bag_reader
  - `src/rosbag_mcp/tools/messages.py:9-13` — imports `get_message_at_time`, `get_messages_in_range`, `read_messages` from bag_reader
  - `src/rosbag_mcp/tools/core.py` — imports `set_bag_path`, `list_bags`, `bag_info` (wraps `get_bag_info`)
  - `src/rosbag_mcp/tools/advanced.py` — imports `read_messages`, `get_bag_info`, `get_topic_timestamps`, `get_topic_schema` from bag_reader
  - `src/rosbag_mcp/tools/filter.py:6` — imports `AnyReader` directly (NOT from bag_reader) — LEAVE ALONE
  - `src/rosbag_mcp/tools/visualization.py` — imports `read_messages`, `get_message_at_time` from bag_reader

  **Acceptance Criteria**:
  - [ ] `python -c "from rosbag_mcp.bag_reader import BagInfo, BagMessage, BagReaderState, set_bag_path, get_current_bag_path, get_current_bags_dir, list_bags, get_bag_info, read_messages, get_message_at_time, get_messages_in_range, get_topic_schema, get_topic_timestamps; print('All imports OK')"` → passes
  - [ ] `python -c "from rosbag_mcp.cache import BagCacheManager; m = BagCacheManager(); print('Cache OK:', m.stats())"` → passes
  - [ ] `python -c "from rosbag_mcp.bag_reader import _msg_to_dict; print(_msg_to_dict.__code__.co_code[:20])"` → function exists and is callable
  - [ ] `python -c "import rosbag_mcp.server"` → No import errors (proves no import cycles, all 24 tools still load)
  - [ ] `python -c "from rosbag_mcp.server import TOOL_HANDLERS; assert len(TOOL_HANDLERS) == 24; print('All 24 tools OK')"` → passes (unchanged count)
  - [ ] `ruff check src/rosbag_mcp/bag_reader.py --select E,F,I,W --target-version py310` → 0 errors

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: All existing public API preserved
    Tool: Bash
    Steps:
      1. python -c "from rosbag_mcp.bag_reader import BagInfo, BagMessage, BagReaderState, set_bag_path, get_current_bag_path, get_current_bags_dir, list_bags, get_bag_info, read_messages, get_message_at_time, get_messages_in_range, get_topic_schema, get_topic_timestamps, _msg_to_dict; print('All 13 symbols OK')"
      2. python -c "import inspect; from rosbag_mcp.bag_reader import read_messages; sig = inspect.signature(read_messages); params = list(sig.parameters.keys()); assert params == ['bag_path', 'topics', 'start_time', 'end_time'], f'Signature changed: {params}'"
      3. python -c "import inspect; from rosbag_mcp.bag_reader import get_message_at_time; sig = inspect.signature(get_message_at_time); params = list(sig.parameters.keys()); assert params == ['topic', 'target_time', 'bag_path', 'tolerance'], f'Signature changed: {params}'"
    Expected Result: All assertions pass
    Evidence: Command output captured

  Scenario: Cache singleton is active in bag_reader
    Tool: Bash
    Steps:
      1. python -c "from rosbag_mcp.bag_reader import _cache; print(type(_cache).__name__); assert type(_cache).__name__ == 'BagCacheManager'"
    Expected Result: BagCacheManager instance exists
    Evidence: Command output captured

  Scenario: No import cycles with full server load
    Tool: Bash
    Steps:
      1. python -c "import rosbag_mcp.server; print('Server loaded OK')"
      2. python -c "from rosbag_mcp.server import TOOL_DEFINITIONS, TOOL_HANDLERS; assert len(TOOL_DEFINITIONS) == len(TOOL_HANDLERS) == 24; print(f'{len(TOOL_DEFINITIONS)} tools OK')"
    Expected Result: Server loads cleanly, 24 tools registered
    Evidence: Command output captured
  ```

  **Commit**: YES
  - Message: `feat(bag_reader): integrate tiered cache for connection pooling and metadata caching`
  - Files: `src/rosbag_mcp/bag_reader.py`, possibly `src/rosbag_mcp/cache.py` (if BagKey directory fix needed)
  - Pre-commit: `ruff check src/ && ruff format --check src/`

---

- [x] 3. Create config.py + YAML schema system

  **What to do**:
  - Create `src/rosbag_mcp/config.py` with:
    - `from __future__ import annotations` as first import
    - `ServerConfig` class: loads from YAML (optional PyYAML) with dict fallback defaults
    - Default config values: `time_tolerance: 0.1`, `cache_max_open: 3`, `cache_idle_ttl: 300`, `image_max_size: 1024`, `image_quality: 85`, `log_level: "INFO"`
    - `SchemaManager` class: loads message field schemas from YAML, provides `get_position_fields(msg_type)`, `get_velocity_fields(msg_type)`, `get_timestamp_field(msg_type)`, `quaternion_to_euler(quat_dict)`, `downsample_array(arr, max_len)`
    - YAML import with try/except: `try: import yaml except ImportError: yaml = None`
    - If yaml is None, fall back to hardcoded Python dict defaults
  - Create `src/rosbag_mcp/default_config.yaml`:
    - Server settings (time_tolerance, cache, image, logging)
  - Create `src/rosbag_mcp/message_schemas.yaml`:
    - Field path schemas for common ROS message types: `nav_msgs/Odometry`, `geometry_msgs/PoseStamped`, `sensor_msgs/LaserScan`, `sensor_msgs/Imu`, `sensor_msgs/JointState`, `sensor_msgs/PointCloud2`, `diagnostic_msgs/DiagnosticArray`, `rosgraph_msgs/Log`
    - For each: position fields, velocity fields, orientation fields, key data fields
  - Run ruff check/format

  **Must NOT do**:
  - Do NOT make PyYAML a required dependency — must work without it
  - Do NOT add environment variable overrides
  - Do NOT create a config CLI
  - Do NOT import config.py from existing modules yet (wired in Task 9)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
  - **Skills**: []
    - Straightforward module creation following Python patterns

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 2)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9
  - **Blocked By**: Task 1

  **References**:

  **Pattern References**:
  - Reference repo `core/schema_manager.py` — Loads `message_schemas.yaml`, provides field extraction by msg type. Our version should follow similar structure but use `try/except` for YAML import.
  - Reference repo `config/message_schemas.yaml` — Example YAML schema structure for ROS message types

  **API References**:
  - `src/rosbag_mcp/tools/utils.py` — `extract_position()` and `extract_velocity()` currently hardcode field paths. SchemaManager should eventually allow configurable field paths (but existing utils.py is NOT modified in this task).
  - `src/rosbag_mcp/cache.py:271-275` — `BagCacheManager.__init__(max_open=3, idle_ttl_s=300.0)` — Config values should match these defaults

  **Acceptance Criteria**:
  - [ ] `python -c "from rosbag_mcp.config import ServerConfig, SchemaManager; c = ServerConfig(); print(c.time_tolerance, c.cache_max_open); s = SchemaManager(); print(s.get_position_fields('nav_msgs/Odometry'))"` → prints defaults and field paths
  - [ ] `python -c "import sys; sys.modules['yaml'] = None; from rosbag_mcp.config import ServerConfig; c = ServerConfig(); assert c.time_tolerance == 0.1; print('YAML-free OK')"` → passes (graceful degradation)
  - [ ] `ruff check src/rosbag_mcp/config.py --select E,F,I,W --target-version py310` → 0 errors
  - [ ] Files exist: `src/rosbag_mcp/default_config.yaml`, `src/rosbag_mcp/message_schemas.yaml`

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: Config loads with defaults (no YAML)
    Tool: Bash
    Steps:
      1. python -c "import sys; sys.modules['yaml'] = None; from rosbag_mcp.config import ServerConfig; c = ServerConfig(); assert c.time_tolerance == 0.1; assert c.cache_max_open == 3; assert c.image_max_size == 1024; print('All defaults correct')"
    Expected Result: All default values accessible
    Evidence: Command output

  Scenario: SchemaManager returns field paths for known types
    Tool: Bash
    Steps:
      1. python -c "from rosbag_mcp.config import SchemaManager; s = SchemaManager(); pos = s.get_position_fields('nav_msgs/Odometry'); assert 'pose.pose.position' in str(pos) or len(pos) > 0; print('Schema OK:', pos)"
    Expected Result: Returns position field paths for Odometry
    Evidence: Command output

  Scenario: No import cycle with server
    Tool: Bash
    Steps:
      1. python -c "import rosbag_mcp.config; import rosbag_mcp.server; print('No cycles')"
    Expected Result: Both modules load without error
    Evidence: Command output
  ```

  **Commit**: YES
  - Message: `feat(config): add ServerConfig and SchemaManager with YAML schema system`
  - Files: `src/rosbag_mcp/config.py`, `src/rosbag_mcp/default_config.yaml`, `src/rosbag_mcp/message_schemas.yaml`
  - Pre-commit: `ruff check src/ && ruff format --check src/`

---

- [ ] 4. Enhance get_image_at_time — CompressedImage, more encodings, smart resize

  **What to do**:
  - Modify `src/rosbag_mcp/tools/analysis.py` function `get_image_at_time()`:
    - Add new optional parameters: `max_size: int = 1024`, `quality: int = 85`
    - Add **CompressedImage support**: Detect by checking for `format` field in msg data (CompressedImage has `format` + `data`, raw Image has `encoding` + `width` + `height` + `data`). If `format` field exists and `width` field is missing, treat as CompressedImage:
      - Extract `data.get("data", [])` as bytes
      - Use `PIL.Image.open(io.BytesIO(compressed_bytes))` to decode JPEG/PNG
      - Handle error gracefully: if Pillow can't decode, return TextContent error
    - Add new encodings for raw Image:
      - `mono16` / `16UC1`: `np.uint16`, reshape `(H, W)`, scale to 8-bit `(arr >> 8).astype(np.uint8)`
      - `32FC1`: `np.float32`, reshape `(H, W)`, normalize to 0-255 uint8
      - `rgba8`: `np.uint8`, reshape `(H, W, 4)`, convert to RGB via `img_arr[:, :, :3]`
      - `bgra8`: `np.uint8`, reshape `(H, W, 4)`, swap channels + drop alpha
    - Add **smart resize**: After creating PIL Image, if `max(width, height) > max_size`, resize with `Image.LANCZOS` resampling maintaining aspect ratio
    - Use `quality` parameter in `img.save(buffer, format="JPEG", quality=quality)`
    - Return enhanced metadata: include `original_size`, `resized` boolean, `format` for compressed

  **Must NOT do**:
  - Do NOT add `opencv-python` as required import — Pillow only
  - Do NOT add video extraction
  - Do NOT change the function signature for existing parameters (topic, timestamp, bag_path)
  - Do NOT break existing rgb8/bgr8/mono8 behavior

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
    - Image processing with Pillow, numpy array manipulation

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 5, 6, 7, 8)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 9
  - **Blocked By**: Task 2

  **References**:

  **Pattern References**:
  - `src/rosbag_mcp/tools/analysis.py:276-323` — Current `get_image_at_time()` implementation. Handles rgb8, bgr8, mono8. Returns `list[TextContent | ImageContent]`.
  - Reference repo `extractors/image.py` — CompressedImage handling, image resize logic, multiple encoding support

  **API References**:
  - `src/rosbag_mcp/bag_reader.py:177-212` — `get_message_at_time()` (aliased as `_get_message_at_time` in analysis.py) — returns `BagMessage | None` with `.data` dict
  - Pillow `Image.open(BytesIO(data))` — For CompressedImage decode
  - Pillow `Image.thumbnail((max_size, max_size), Image.LANCZOS)` — For resize

  **ROS Message Shape References**:
  - `sensor_msgs/Image`: `{width, height, encoding, step, data}` — raw pixel data
  - `sensor_msgs/CompressedImage`: `{header, format, data}` — JPEG/PNG compressed bytes, NO width/height fields

  **Acceptance Criteria**:
  - [ ] `python -c "import inspect; from rosbag_mcp.tools.analysis import get_image_at_time; sig = inspect.signature(get_image_at_time); assert 'max_size' in sig.parameters; assert 'quality' in sig.parameters; print('New params OK')"` → passes
  - [ ] `python -c "from rosbag_mcp.tools.analysis import get_image_at_time; print('Import OK')"` → no import errors
  - [ ] `ruff check src/rosbag_mcp/tools/analysis.py --select E,F,I,W --target-version py310` → 0 errors
  - [ ] Verify the function source handles CompressedImage: `python -c "import inspect; from rosbag_mcp.tools.analysis import get_image_at_time; src = inspect.getsource(get_image_at_time); assert 'CompressedImage' in src or 'format' in src; assert 'mono16' in src or '16UC1' in src; assert 'LANCZOS' in src or 'thumbnail' in src; print('All code paths present')"` → passes

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: CompressedImage detection logic exists in code
    Tool: Bash
    Steps:
      1. python -c "import inspect; from rosbag_mcp.tools.analysis import get_image_at_time; src = inspect.getsource(get_image_at_time); checks = ['format' in src, 'mono16' in src or '16UC1' in src, 'rgba8' in src, 'LANCZOS' in src or 'thumbnail' in src, 'max_size' in src]; print('Checks:', checks); assert all(checks), f'Missing code paths: {checks}'"
    Expected Result: All encoding and resize code paths present
    Evidence: Command output

  Scenario: Backward compatible — existing parameters unchanged
    Tool: Bash
    Steps:
      1. python -c "import inspect; from rosbag_mcp.tools.analysis import get_image_at_time; sig = inspect.signature(get_image_at_time); p = sig.parameters; assert list(p.keys())[:3] == ['image_topic', 'timestamp', 'bag_path']; assert p['max_size'].default == 1024; assert p['quality'].default == 85; print('Signature OK')"
    Expected Result: First 3 params unchanged, new params have defaults
    Evidence: Command output
  ```

  **Commit**: YES (groups with Tasks 5, 6)
  - Message: `feat(image): add CompressedImage support, more encodings, smart resize`
  - Files: `src/rosbag_mcp/tools/analysis.py`
  - Pre-commit: `ruff check src/rosbag_mcp/tools/analysis.py`

---

- [ ] 5. Enhance search_messages — contains, field_exists, cross-topic correlation

  **What to do**:
  - Modify `src/rosbag_mcp/tools/messages.py` function `search_messages()`:
    - Add new `condition_type` values:
      - `"contains"`: Check if `str(field_value)` contains the value substring (case-insensitive)
      - `"field_exists"`: Check if the field path exists and is not None in the message data (value parameter is ignored but still required by schema)
    - Add new optional parameters:
      - `correlate_topic: str | None = None` — If provided, for each match found on the primary topic, find the nearest message on `correlate_topic` within `correlation_tolerance` seconds and include it in the result
      - `correlation_tolerance: float = 0.1` — Time window for correlation matching
    - Correlation implementation: For each primary match, call `from rosbag_mcp.bag_reader import get_message_at_time as _get_message_at_time` and use `_get_message_at_time(correlate_topic, match_timestamp, bag_path, tolerance=correlation_tolerance)` to find the correlated message. Add `"correlated"` key to result dict with the correlated message data (or `null` if no match).
    - Keep all existing condition_type behavior (regex, equals, greater_than, less_than, near_position) unchanged

  **Must NOT do**:
  - Do NOT change existing condition_type behavior
  - Do NOT remove any existing parameters
  - Do NOT change return format for non-correlated results
  - Do NOT add full-text search or fuzzy matching
  - Do NOT add multi-topic join queries

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
    - Python async function modification with careful API extension

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 4, 6, 7, 8)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 9
  - **Blocked By**: Task 2

  **References**:

  **Pattern References**:
  - `src/rosbag_mcp/tools/messages.py:51-107` — Current `search_messages()` implementation. Has condition_types: regex, equals, greater_than, less_than, near_position. Returns `list[TextContent]` with JSON-serialized results.
  - `src/rosbag_mcp/tools/utils.py` — `get_nested_field()` for dot-path field traversal, already used by search_messages

  **API References**:
  - `src/rosbag_mcp/bag_reader.py:177-212` — `get_message_at_time()` for correlation lookups
  - `src/rosbag_mcp/tools/messages.py:9-10` — Already imports `get_message_at_time as _get_message_at_time`

  **Acceptance Criteria**:
  - [ ] `python -c "import inspect; from rosbag_mcp.tools.messages import search_messages; sig = inspect.signature(search_messages); assert 'correlate_topic' in sig.parameters; assert 'correlation_tolerance' in sig.parameters; print('New params OK')"` → passes
  - [ ] `python -c "import inspect; from rosbag_mcp.tools.messages import search_messages; src = inspect.getsource(search_messages); assert 'contains' in src; assert 'field_exists' in src; print('New conditions OK')"` → passes
  - [ ] `ruff check src/rosbag_mcp/tools/messages.py` → 0 errors

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: New condition types and correlation params exist in code
    Tool: Bash
    Steps:
      1. python -c "import inspect; from rosbag_mcp.tools.messages import search_messages; src = inspect.getsource(search_messages); sig = inspect.signature(search_messages); checks = ['contains' in src, 'field_exists' in src, 'correlate_topic' in sig.parameters, 'correlation_tolerance' in sig.parameters, sig.parameters['correlation_tolerance'].default == 0.1]; print('Checks:', checks); assert all(checks)"
    Expected Result: All new features present in code
    Evidence: Command output

  Scenario: Existing parameters preserved
    Tool: Bash
    Steps:
      1. python -c "import inspect; from rosbag_mcp.tools.messages import search_messages; sig = inspect.signature(search_messages); required = ['topic', 'condition_type', 'value']; assert all(p in sig.parameters for p in required); print('Backward compat OK')"
    Expected Result: Original parameters unchanged
    Evidence: Command output
  ```

  **Commit**: YES (groups with Tasks 4, 6)
  - Message: `feat(search): add contains, field_exists conditions and cross-topic correlation`
  - Files: `src/rosbag_mcp/tools/messages.py`
  - Pre-commit: `ruff check src/rosbag_mcp/tools/messages.py`

---

- [ ] 6. Enhance analyze_trajectory — angle-based waypoints, path efficiency metrics

  **What to do**:
  - Modify `src/rosbag_mcp/tools/analysis.py` function `analyze_trajectory()`:
    - Add new optional parameter: `waypoint_angle_threshold: float = 15.0` (degrees)
    - **Angle-based waypoint detection**: When `include_waypoints=True`, instead of just evenly-spaced sampling, detect waypoints where heading change exceeds `waypoint_angle_threshold` degrees. Calculate heading from consecutive position pairs using `math.atan2(dy, dx)`. Mark positions where `abs(heading_change)` exceeds threshold as waypoints. Also detect stop points (speed drops below threshold for sustained period).
    - **New metrics**: Add to result dict:
      - `displacement`: Straight-line distance from first to last position
      - `path_efficiency`: `displacement / total_distance` ratio (1.0 = perfectly straight)
      - `moving_time_s`: Time where linear speed > 0.01 m/s
      - `stationary_time_s`: `duration_s - moving_time_s`
    - Keep all existing behavior for non-waypoint mode unchanged

  **Must NOT do**:
  - Do NOT add trajectory planning or path optimization
  - Do NOT add A* search or any pathfinding
  - Do NOT change the function's existing parameter defaults
  - Do NOT break non-waypoint mode output format

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
    - Geometric computation (heading angles, displacement)

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 4, 5, 7, 8)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 9
  - **Blocked By**: Task 2

  **References**:

  **Pattern References**:
  - `src/rosbag_mcp/tools/analysis.py:18-90` — Current `analyze_trajectory()` implementation. Existing waypoint logic (line 78-88) does evenly-spaced sampling — enhance to angle-based.
  - `src/rosbag_mcp/tools/utils.py` — `extract_position()` and `extract_velocity()` used by trajectory

  **API References**:
  - `math.atan2(dy, dx)` — For heading angle computation
  - `math.degrees()` — Convert radians to degrees for threshold comparison

  **Acceptance Criteria**:
  - [ ] `python -c "import inspect; from rosbag_mcp.tools.analysis import analyze_trajectory; sig = inspect.signature(analyze_trajectory); assert 'waypoint_angle_threshold' in sig.parameters; assert sig.parameters['waypoint_angle_threshold'].default == 15.0; print('Param OK')"` → passes
  - [ ] `python -c "import inspect; from rosbag_mcp.tools.analysis import analyze_trajectory; src = inspect.getsource(analyze_trajectory); assert 'displacement' in src; assert 'path_efficiency' in src; assert 'moving_time_s' in src; assert 'atan2' in src; print('Metrics OK')"` → passes
  - [ ] `ruff check src/rosbag_mcp/tools/analysis.py` → 0 errors

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: New metrics and waypoint logic present
    Tool: Bash
    Steps:
      1. python -c "import inspect; from rosbag_mcp.tools.analysis import analyze_trajectory; src = inspect.getsource(analyze_trajectory); checks = ['displacement' in src, 'path_efficiency' in src, 'moving_time' in src, 'stationary_time' in src, 'atan2' in src, 'waypoint_angle_threshold' in src]; print('Checks:', checks); assert all(checks)"
    Expected Result: All new features present
    Evidence: Command output
  ```

  **Commit**: YES (groups with Tasks 4, 5)
  - Message: `feat(trajectory): add angle-based waypoints, displacement, path efficiency metrics`
  - Files: `src/rosbag_mcp/tools/analysis.py`
  - Pre-commit: `ruff check src/rosbag_mcp/tools/analysis.py`

---

- [ ] 7. Create tools/sensors.py — PointCloud2, JointState, DiagnosticArray analysis

  **What to do**:
  - Create `src/rosbag_mcp/tools/sensors.py` with `from __future__ import annotations` as first import
  - Import: `logging`, `numpy`, `from mcp.types import TextContent`, `from rosbag_mcp.bag_reader import read_messages`, `from rosbag_mcp.tools.utils import json_serialize`
  - Add `logger = logging.getLogger(__name__)`

  - **`async def analyze_pointcloud2()`**:
    - Parameters: `topic: str = "/points"`, `timestamp: float | None = None`, `max_points: int = 10000`, `bag_path: str | None = None`
    - Returns: `list[TextContent]`
    - Implementation:
      - Get one PointCloud2 message (at timestamp if provided, else first)
      - Parse binary data from `msg.data["data"]` using numpy structured dtype built from `msg.data["fields"]` (each field has name, offset, datatype, count)
      - PointCloud2 datatype mapping: `{1: ('int8', 1), 2: ('uint8', 1), 3: ('int16', 2), 4: ('uint16', 2), 5: ('int32', 4), 6: ('uint32', 4), 7: ('float32', 4), 8: ('float64', 8)}`
      - Extract x, y, z fields if present
      - Compute: point_count, bounds (min/max x/y/z), centroid, if intensity field exists compute intensity stats
      - If more than max_points, downsample for stats
      - Return JSON with: point_count, bounds, centroid, intensity_stats (if available), dimensions (width/height from msg), is_dense

  - **`async def analyze_joint_states()`**:
    - Parameters: `topic: str = "/joint_states"`, `start_time: float | None = None`, `end_time: float | None = None`, `bag_path: str | None = None`
    - Returns: `list[TextContent]`
    - Implementation:
      - Iterate messages on topic, collect per-joint-name stats
      - For each joint in `msg.data["name"]` list, collect corresponding `position`, `velocity`, `effort` values from the parallel arrays
      - Compute per-joint: position range (min/max), mean velocity, max effort, variance
      - Detect potential issues: joints near limits (if range is very small), zero-velocity joints, high-effort joints
      - Return JSON with: joint_count, duration, per_joint stats dict, alerts list

  - **`async def analyze_diagnostics()`**:
    - Parameters: `topic: str = "/diagnostics"`, `start_time: float | None = None`, `end_time: float | None = None`, `bag_path: str | None = None`
    - Returns: `list[TextContent]`
    - Implementation:
      - Iterate DiagnosticArray messages
      - Each message has `status` list, each status has `name`, `level` (0=OK, 1=WARN, 2=ERROR, 3=STALE), `message`, `values` (key-value pairs)
      - Aggregate by hardware `name`: count per level, first/last occurrence, messages
      - Build timeline of errors/warnings
      - Return JSON with: total_messages, unique_hardware, per_hardware breakdown, error_timeline, summary (ok_count, warn_count, error_count, stale_count)

  **Must NOT do**:
  - Do NOT add 3D visualization or rendering
  - Do NOT add ML/clustering for PointCloud2
  - Do NOT add object detection or ground plane estimation
  - Do NOT make numpy a new dependency (already in dependencies)
  - Do NOT import from tools/advanced.py or tools/analysis.py

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
    - Numpy binary data parsing, ROS message structure knowledge

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 4, 5, 6, 8)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 9
  - **Blocked By**: Task 2

  **References**:

  **Pattern References**:
  - `src/rosbag_mcp/tools/analysis.py:93-148` — `analyze_lidar_scan()` — Similar sensor analysis pattern: get message, parse data, compute stats, return JSON TextContent
  - `src/rosbag_mcp/tools/advanced.py` — `analyze_imu()` — Per-axis statistics pattern (mean, std, min, max) similar to JointState analysis
  - Reference repo `extractors/lidar.py` — PointCloud2 parsing approach

  **API References**:
  - `src/rosbag_mcp/bag_reader.py:143-174` — `read_messages()` — iterate messages by topic
  - `src/rosbag_mcp/bag_reader.py:177-212` — `get_message_at_time()` — single message at timestamp
  - `src/rosbag_mcp/tools/utils.py:1-40` — `json_serialize()` — JSON encoder for numpy types

  **ROS Message Shape References**:
  - `sensor_msgs/PointCloud2`: `{header, height, width, fields: [{name, offset, datatype, count}], is_bigendian, point_step, row_step, data: bytes, is_dense}`
  - `sensor_msgs/JointState`: `{header, name: [str], position: [float], velocity: [float], effort: [float]}`
  - `diagnostic_msgs/DiagnosticArray`: `{header, status: [{level: int, name: str, message: str, hardware_id: str, values: [{key, value}]}]}`

  **Acceptance Criteria**:
  - [ ] `python -c "from rosbag_mcp.tools.sensors import analyze_pointcloud2, analyze_joint_states, analyze_diagnostics; print('All 3 sensor tools OK')"` → passes
  - [ ] `python -c "import inspect; from rosbag_mcp.tools.sensors import analyze_pointcloud2; assert inspect.iscoroutinefunction(analyze_pointcloud2); print('Async OK')"` → passes
  - [ ] `ruff check src/rosbag_mcp/tools/sensors.py` → 0 errors

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: All 3 sensor tool functions importable and async
    Tool: Bash
    Steps:
      1. python -c "import inspect; from rosbag_mcp.tools.sensors import analyze_pointcloud2, analyze_joint_states, analyze_diagnostics; assert all(inspect.iscoroutinefunction(f) for f in [analyze_pointcloud2, analyze_joint_states, analyze_diagnostics]); print('All async OK')"
      2. python -c "import inspect; from rosbag_mcp.tools.sensors import analyze_pointcloud2; sig = inspect.signature(analyze_pointcloud2); assert 'topic' in sig.parameters; assert 'bag_path' in sig.parameters; print('Signature OK')"
    Expected Result: All functions are async with expected parameters
    Evidence: Command output

  Scenario: PointCloud2 dtype mapping exists
    Tool: Bash
    Steps:
      1. python -c "import inspect; from rosbag_mcp.tools.sensors import analyze_pointcloud2; src = inspect.getsource(analyze_pointcloud2); assert 'float32' in src; assert 'structured' in src.lower() or 'dtype' in src; print('Binary parsing OK')"
    Expected Result: PointCloud2 binary parsing logic present
    Evidence: Command output
  ```

  **Commit**: YES
  - Message: `feat(sensors): add PointCloud2, JointState, DiagnosticArray analysis tools`
  - Files: `src/rosbag_mcp/tools/sensors.py`
  - Pre-commit: `ruff check src/rosbag_mcp/tools/sensors.py`

---

- [ ] 8. Add Python logging to all modules

  **What to do**:
  - Add `import logging` and `logger = logging.getLogger(__name__)` to ALL source files that don't already have it:
    - `src/rosbag_mcp/server.py` — Add logger, log tool calls (`logger.info("Calling tool: %s", name)`), log errors (`logger.error(...)`)
    - `src/rosbag_mcp/tools/core.py` — Log set_bag_path, list_bags, bag_info calls
    - `src/rosbag_mcp/tools/messages.py` — Log search operations
    - `src/rosbag_mcp/tools/filter.py` — Log filter operations
    - `src/rosbag_mcp/tools/analysis.py` — Log analysis operations
    - `src/rosbag_mcp/tools/visualization.py` — Log plot generation
    - `src/rosbag_mcp/tools/advanced.py` — Log advanced analysis operations
    - `src/rosbag_mcp/tools/utils.py` — Log serialization errors (if any)
  - Note: `cache.py` and `bag_reader.py` (after Task 2) already have logging
  - Note: `sensors.py` (Task 7) and `config.py` (Task 3) should include logging when created
  - Add basic logging configuration in `server.py`'s `main()` or `run_server()`:
    ```python
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    )
    ```
  - Log at appropriate levels: INFO for tool calls and key operations, DEBUG for detailed data, WARNING for unexpected but non-fatal issues, ERROR for caught exceptions

  **Must NOT do**:
  - Do NOT add structured JSON logging
  - Do NOT add log rotation or remote shipping
  - Do NOT add excessive logging that would slow down message iteration
  - Do NOT log message content/data (could be very large)
  - Do NOT change any function signatures or behavior

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
    - Simple additions of logger + log statements across files

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 4, 5, 6, 7)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 9
  - **Blocked By**: Task 2

  **References**:

  **Pattern References**:
  - `src/rosbag_mcp/cache.py:10,20` — Already has `import logging` and `logger = logging.getLogger(__name__)` — follow this exact pattern
  - `src/rosbag_mcp/cache.py:255-260` — Example of `logger.debug(...)` usage with format strings

  **Files to Modify**:
  - `src/rosbag_mcp/server.py` — Add logging import, logger, basicConfig in main(), log tool calls in handle_call_tool
  - `src/rosbag_mcp/tools/core.py` — Add logging
  - `src/rosbag_mcp/tools/messages.py` — Add logging
  - `src/rosbag_mcp/tools/filter.py` — Add logging
  - `src/rosbag_mcp/tools/analysis.py` — Add logging
  - `src/rosbag_mcp/tools/visualization.py` — Add logging
  - `src/rosbag_mcp/tools/advanced.py` — Add logging
  - `src/rosbag_mcp/tools/utils.py` — Add logging

  **Acceptance Criteria**:
  - [ ] `python -c "import logging; logging.basicConfig(level=logging.DEBUG); import rosbag_mcp.server"` → Shows log output during import (no crashes)
  - [ ] `ruff check src/ --select E,F,I,W --target-version py310` → 0 errors
  - [ ] Every .py file in `src/rosbag_mcp/` and `src/rosbag_mcp/tools/` has `logger = logging.getLogger(__name__)`: verify with grep

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: All modules have logger
    Tool: Bash
    Steps:
      1. python -c "
      import importlib, pkgutil
      import rosbag_mcp
      modules = ['rosbag_mcp.server', 'rosbag_mcp.bag_reader', 'rosbag_mcp.cache', 'rosbag_mcp.tools.core', 'rosbag_mcp.tools.messages', 'rosbag_mcp.tools.filter', 'rosbag_mcp.tools.analysis', 'rosbag_mcp.tools.visualization', 'rosbag_mcp.tools.advanced', 'rosbag_mcp.tools.utils']
      for mod_name in modules:
          mod = importlib.import_module(mod_name)
          assert hasattr(mod, 'logger'), f'{mod_name} missing logger'
          print(f'{mod_name}: logger OK')
      print('All modules have logger')
      "
    Expected Result: All modules have logger attribute
    Evidence: Command output
  ```

  **Commit**: YES
  - Message: `feat(logging): add Python logging throughout all modules`
  - Files: All .py files in src/rosbag_mcp/ and src/rosbag_mcp/tools/
  - Pre-commit: `ruff check src/`

---

- [ ] 9. Wire all new/updated tools in server.py + tools/__init__.py + pyproject.toml

  **What to do**:
  - **`src/rosbag_mcp/tools/__init__.py`**: Add imports and re-exports for:
    - `from rosbag_mcp.tools.sensors import analyze_pointcloud2, analyze_joint_states, analyze_diagnostics`
    - Add all 3 to `__all__` list
  - **`src/rosbag_mcp/server.py`**: Add imports at top:
    - Add `analyze_pointcloud2, analyze_joint_states, analyze_diagnostics` to the import from `rosbag_mcp.tools`
  - **`src/rosbag_mcp/server.py` TOOL_DEFINITIONS**: Add 3 new Tool() entries:
    - `analyze_pointcloud2`: params topic (str, default "/points"), timestamp (number, optional), max_points (integer, default 10000), bag_path (str, optional). Required: [] (all have defaults).
    - `analyze_joint_states`: params topic (str, default "/joint_states"), start_time (number, optional), end_time (number, optional), bag_path (str, optional). Required: [].
    - `analyze_diagnostics`: params topic (str, default "/diagnostics"), start_time (number, optional), end_time (number, optional), bag_path (str, optional). Required: [].
  - **`src/rosbag_mcp/server.py` TOOL_DEFINITIONS**: Update existing Tool() entries:
    - `get_image_at_time`: Add `max_size` (integer, default 1024) and `quality` (integer, default 85) to properties
    - `search_messages`: Add `correlate_topic` (string, optional) and `correlation_tolerance` (number, default 0.1) to properties. Add `"contains"` and `"field_exists"` to condition_type description.
    - `analyze_trajectory`: Add `waypoint_angle_threshold` (number, default 15.0) to properties
  - **`src/rosbag_mcp/server.py` TOOL_HANDLERS**: Add 3 new handlers:
    - `"analyze_pointcloud2": lambda args: analyze_pointcloud2(topic=args.get("topic", "/points"), timestamp=args.get("timestamp"), max_points=args.get("max_points", 10000), bag_path=args.get("bag_path"))`
    - `"analyze_joint_states": lambda args: analyze_joint_states(topic=args.get("topic", "/joint_states"), start_time=args.get("start_time"), end_time=args.get("end_time"), bag_path=args.get("bag_path"))`
    - `"analyze_diagnostics": lambda args: analyze_diagnostics(topic=args.get("topic", "/diagnostics"), start_time=args.get("start_time"), end_time=args.get("end_time"), bag_path=args.get("bag_path"))`
  - **`src/rosbag_mcp/server.py` TOOL_HANDLERS**: Update existing handlers:
    - `get_image_at_time`: Add `max_size=args.get("max_size", 1024)`, `quality=args.get("quality", 85)`
    - `search_messages`: Add `correlate_topic=args.get("correlate_topic")`, `correlation_tolerance=args.get("correlation_tolerance", 0.1)`
    - `analyze_trajectory`: Add `waypoint_angle_threshold=args.get("waypoint_angle_threshold", 15.0)`
  - **`pyproject.toml`**: Add optional dependency group:
    ```toml
    [project.optional-dependencies]
    yaml = ["pyyaml>=6.0"]
    dev = [
        "pytest>=7.0.0",
        "pytest-asyncio>=0.21.0",
        "ruff>=0.1.0",
        "pyyaml>=6.0",
    ]
    ```
  - Run ruff check/format on all modified files

  **Must NOT do**:
  - Do NOT restructure the TOOL_DEFINITIONS/TOOL_HANDLERS pattern
  - Do NOT change existing handler behavior for non-new parameters
  - Do NOT remove any existing tool definitions
  - Do NOT change the import pattern (keep direct imports from rosbag_mcp.tools)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
    - Careful multi-file integration, JSON schema writing

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (solo)
  - **Blocks**: Tasks 10, 11
  - **Blocked By**: Tasks 2, 3, 4, 5, 6, 7, 8

  **References**:

  **Pattern References**:
  - `src/rosbag_mcp/server.py:42-55` — Example `Tool()` definition with JSON Schema (follow this exact pattern)
  - `src/rosbag_mcp/server.py:583-748` — `TOOL_HANDLERS` dict — lambda pattern for all handlers
  - `src/rosbag_mcp/server.py:636-640` — Existing `get_image_at_time` handler — add new params here
  - `src/rosbag_mcp/server.py:600-607` — Existing `search_messages` handler — add new params here
  - `src/rosbag_mcp/server.py:615-621` — Existing `analyze_trajectory` handler — add new param here
  - `src/rosbag_mcp/tools/__init__.py` — Current imports and `__all__` list (add 3 new entries)
  - `src/rosbag_mcp/server.py:9-37` — Current import block from rosbag_mcp.tools

  **Acceptance Criteria**:
  - [ ] `python -c "from rosbag_mcp.server import TOOL_DEFINITIONS, TOOL_HANDLERS; assert len(TOOL_DEFINITIONS) == 27; assert len(TOOL_HANDLERS) == 27; print('27 tools registered')"` → passes (24 existing + 3 new)
  - [ ] `python -c "from rosbag_mcp.server import TOOL_HANDLERS; new_tools = ['analyze_pointcloud2', 'analyze_joint_states', 'analyze_diagnostics']; assert all(t in TOOL_HANDLERS for t in new_tools); print('New tools in handlers')"` → passes
  - [ ] `python -c "from rosbag_mcp.server import TOOL_DEFINITIONS; names = {t.name for t in TOOL_DEFINITIONS}; handlers = set(__import__('rosbag_mcp.server', fromlist=['TOOL_HANDLERS']).TOOL_HANDLERS.keys()); assert names == handlers, f'Mismatch: {names ^ handlers}'; print('Definitions match handlers')"` → passes
  - [ ] `python -c "import rosbag_mcp.server"` → no import errors
  - [ ] `ruff check src/ --select E,F,I,W --target-version py310` → 0 errors

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: 27 tools registered consistently
    Tool: Bash
    Steps:
      1. python -c "
      from rosbag_mcp.server import TOOL_DEFINITIONS, TOOL_HANDLERS
      def_names = {t.name for t in TOOL_DEFINITIONS}
      hdl_names = set(TOOL_HANDLERS.keys())
      assert def_names == hdl_names, f'Mismatch: defs_only={def_names - hdl_names}, hdls_only={hdl_names - def_names}'
      assert len(def_names) == 27, f'Expected 27, got {len(def_names)}'
      print(f'All {len(def_names)} tools consistent')
      "
    Expected Result: 27 tools, definitions match handlers
    Evidence: Command output

  Scenario: Updated handlers pass new params
    Tool: Bash
    Steps:
      1. python -c "
      import inspect
      from rosbag_mcp.server import TOOL_HANDLERS
      # Check get_image_at_time handler source includes max_size
      src = inspect.getsource(TOOL_HANDLERS['get_image_at_time'])
      assert 'max_size' in src, 'Missing max_size in image handler'
      assert 'quality' in src, 'Missing quality in image handler'
      # Check search_messages handler source includes correlate_topic
      src = inspect.getsource(TOOL_HANDLERS['search_messages'])
      assert 'correlate_topic' in src, 'Missing correlate_topic in search handler'
      # Check analyze_trajectory handler source includes waypoint_angle_threshold
      src = inspect.getsource(TOOL_HANDLERS['analyze_trajectory'])
      assert 'waypoint_angle_threshold' in src, 'Missing waypoint_angle_threshold in trajectory handler'
      print('All updated handlers have new params')
      "
    Expected Result: All updated handlers include new params
    Evidence: Command output

  Scenario: pyproject.toml has yaml optional dep
    Tool: Bash
    Steps:
      1. python -c "
      import tomllib
      with open('pyproject.toml', 'rb') as f:
          data = tomllib.load(f)
      opt = data.get('project', {}).get('optional-dependencies', {})
      assert 'yaml' in opt or any('pyyaml' in str(v).lower() for v in opt.get('dev', [])), 'Missing pyyaml'
      print('pyproject.toml OK')
      "
    Expected Result: PyYAML in optional deps
    Evidence: Command output
  ```

  **Commit**: YES
  - Message: `feat(server): wire 3 new sensor tools, update schemas for enhanced tools`
  - Files: `src/rosbag_mcp/server.py`, `src/rosbag_mcp/tools/__init__.py`, `pyproject.toml`
  - Pre-commit: `ruff check src/ && ruff format --check src/`

---

- [ ] 10. Create test infrastructure + regression tests

  **What to do**:
  - Create `tests/` directory
  - Create `tests/__init__.py` (empty)
  - Create `tests/conftest.py` with:
    - Mock/synthetic bag fixtures using `unittest.mock` to mock `rosbags.highlevel.AnyReader`
    - Fixtures that create mock `BagMessage` objects with realistic data structures for: Odometry, LaserScan, Image, CompressedImage, JointState, PointCloud2, DiagnosticArray, Log
    - Fixture to create a mock `BagInfo` object
    - Fixture to patch `BagCacheManager` for isolated testing
  - Create `tests/test_cache.py`:
    - Test `SizeAwareSLRU`: put/get, promotion from probation to protected, eviction when over budget, TTL expiration, byte accounting
    - Test `TopicTimeIndex`: find_nearest (exact match, within tolerance, out of tolerance), find_range (normal, empty, edge cases)
    - Test `BagKey`: equality, different files, frozen dataclass
    - Test `BagCacheManager`: get_handle creates handle, repeated get_handle returns same handle, LRU eviction at max_open, idle eviction, invalidate
  - Create `tests/test_bag_reader.py`:
    - Test that all public functions exist and are callable
    - Test `set_bag_path` with mock filesystem
    - Test `_msg_to_dict` with nested dataclass-like objects
    - Test `read_messages` uses cache (mock BagCacheManager)
    - Test backward compatibility: function signatures match expected parameters
  - Create `tests/test_tools.py`:
    - Test `json_serialize` with numpy arrays, floats, nested dicts
    - Test `get_nested_field` with valid paths, invalid paths, None handling
    - Test `extract_position` with Odometry-style data, PoseStamped-style data
    - Test new search conditions (contains, field_exists) with mock messages
    - Test that all 27 tool functions are importable from `rosbag_mcp.tools`
  - Run `python -m pytest tests/ -v`

  **Must NOT do**:
  - Do NOT require real bag files for tests
  - Do NOT add coverage reports or mutation testing
  - Do NOT add CI/CD pipeline
  - Do NOT test against live MCP server (unit tests only)
  - Do NOT mock at too low a level — mock at AnyReader boundary

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
    - Test architecture, mocking patterns, pytest fixtures

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 11)
  - **Parallel Group**: Wave 5
  - **Blocks**: Task 12
  - **Blocked By**: Task 9

  **References**:

  **Pattern References**:
  - `pyproject.toml:35-39` — Dev dependencies include pytest + pytest-asyncio (already configured)
  - `src/rosbag_mcp/cache.py:58-157` — `SizeAwareSLRU` class — key target for unit testing
  - `src/rosbag_mcp/cache.py:166-195` — `TopicTimeIndex` class — bisect-based, important to test edge cases
  - `src/rosbag_mcp/bag_reader.py:128-140` — `_msg_to_dict()` — recursive converter, test with nested structures

  **API References**:
  - `src/rosbag_mcp/bag_reader.py:11-26` — `BagInfo` and `BagMessage` dataclass fields for fixture creation
  - All tool function signatures in `src/rosbag_mcp/tools/__init__.py` — for importability testing

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/ -v --tb=short` → All tests pass, 0 failures, 0 errors
  - [ ] `python -m pytest tests/ -v --tb=short 2>&1 | tail -5` → Shows "X passed" with X >= 20
  - [ ] Files exist: `tests/__init__.py`, `tests/conftest.py`, `tests/test_cache.py`, `tests/test_bag_reader.py`, `tests/test_tools.py`

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: Test suite passes
    Tool: Bash
    Steps:
      1. python -m pytest tests/ -v --tb=short
    Expected Result: All tests pass, 0 failures
    Evidence: Full pytest output captured

  Scenario: Minimum test count met
    Tool: Bash
    Steps:
      1. python -m pytest tests/ --co -q 2>&1 | tail -1
    Expected Result: Shows "X tests collected" with X >= 20
    Evidence: Test count output
  ```

  **Commit**: YES
  - Message: `test: add regression tests for cache, bag_reader, and tool functions`
  - Files: `tests/__init__.py`, `tests/conftest.py`, `tests/test_cache.py`, `tests/test_bag_reader.py`, `tests/test_tools.py`
  - Pre-commit: `python -m pytest tests/ -v`

---

- [ ] 11. Cache performance benchmarks

  **What to do**:
  - Create `tests/test_benchmarks.py`:
    - Use `time.perf_counter` for measurements (not `pytest-benchmark` — keep it simple)
    - **Benchmark 1: SizeAwareSLRU vs dict**:
      - Create SLRU with 1MB budget, put/get 1000 items, measure time per operation
      - Compare with plain dict put/get for baseline
      - Assert SLRU operations are within 10x of dict (reasonable overhead)
    - **Benchmark 2: TopicTimeIndex.find_nearest**:
      - Create index with 100,000 timestamps
      - Measure 1000 find_nearest calls (random targets within range)
      - Assert < 1ms per lookup (bisect should be O(log n))
    - **Benchmark 3: TopicTimeIndex.find_range**:
      - Same index, measure 1000 find_range calls
      - Assert < 1ms per range lookup
    - **Benchmark 4: BagCacheManager handle reuse**:
      - Mock a BagHandle with pre-populated meta cache
      - Measure time to call `get_handle` 1000 times for same path (should return cached)
      - Assert < 0.1ms per call (dict lookup only)
    - **Benchmark 5: Metadata cache hit vs miss simulation**:
      - Simulate get_bag_info: first call populates handle.meta["bag_info"], second call returns cached
      - Measure time for cache hit vs creating new BagInfo
      - Show speedup factor
    - Print results as formatted table
    - Each benchmark runs 3 iterations, reports mean and std
  - Run `python -m pytest tests/test_benchmarks.py -v -s` (with -s for print output)

  **Must NOT do**:
  - Do NOT add flamegraph profiling
  - Do NOT add memory leak detection
  - Do NOT add stress testing
  - Do NOT require real bag files
  - Do NOT install pytest-benchmark (use time.perf_counter)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
    - Performance measurement, statistical analysis

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 10)
  - **Parallel Group**: Wave 5
  - **Blocks**: Task 12
  - **Blocked By**: Task 9

  **References**:

  **Pattern References**:
  - `src/rosbag_mcp/cache.py:58-157` — `SizeAwareSLRU` class — benchmark target
  - `src/rosbag_mcp/cache.py:166-195` — `TopicTimeIndex` class — benchmark target (find_nearest, find_range)
  - `src/rosbag_mcp/cache.py:268-355` — `BagCacheManager` class — benchmark handle reuse

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/test_benchmarks.py -v -s` → All benchmarks pass
  - [ ] Output shows formatted benchmark table with timing data
  - [ ] TopicTimeIndex.find_nearest average < 1ms (for 100K timestamps)
  - [ ] BagCacheManager.get_handle cache hit < 0.1ms average

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: Benchmarks run and pass
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_benchmarks.py -v -s --tb=short
    Expected Result: All benchmark tests pass, timing output visible
    Evidence: Full pytest output with timings

  Scenario: Performance assertions hold
    Tool: Bash
    Steps:
      1. python -c "
      from rosbag_mcp.cache import TopicTimeIndex
      import time, random
      idx = TopicTimeIndex(timestamps_ns=list(range(0, 100_000_000_000, 1_000_000)))
      targets = [random.randint(0, 100_000_000_000) for _ in range(1000)]
      start = time.perf_counter()
      for t in targets:
          idx.find_nearest(t, 500_000)
      elapsed = time.perf_counter() - start
      per_call_ms = (elapsed / 1000) * 1000
      print(f'TopicTimeIndex.find_nearest: {per_call_ms:.4f} ms/call')
      assert per_call_ms < 1.0, f'Too slow: {per_call_ms}ms'
      "
    Expected Result: < 1ms per find_nearest call
    Evidence: Timing output
  ```

  **Commit**: YES (groups with Task 10)
  - Message: `test: add cache performance benchmarks`
  - Files: `tests/test_benchmarks.py`
  - Pre-commit: `python -m pytest tests/test_benchmarks.py -v`

---

- [ ] 12. Final lint/format + AGENTS.md update

  **What to do**:
  - Run `ruff check src/ --select E,F,I,W --target-version py310 --fix` to auto-fix any issues
  - Run `ruff format src/` to format all source files
  - Run `ruff check tests/ --select E,F,I,W --target-version py310 --fix` and `ruff format tests/`
  - Run full test suite: `python -m pytest tests/ -v --tb=short`
  - Update `AGENTS.md` with new architecture:
    - Add cache module to STRUCTURE section
    - Add config.py, sensors.py to STRUCTURE
    - Update CODE MAP with cache data flow
    - Add new Key Abstractions: BagCacheManager, ServerConfig, SchemaManager
    - Update COMMANDS section with test commands
    - Add new tool pattern for sensor tools
    - Update NOTES section
  - Final smoke test: `python -c "import rosbag_mcp.server; from rosbag_mcp.server import TOOL_DEFINITIONS; print(f'{len(TOOL_DEFINITIONS)} tools ready')"` → should print "27 tools ready"

  **Must NOT do**:
  - Do NOT change any functional code — lint/format only
  - Do NOT add new features
  - Do NOT modify test assertions

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: [`git-master`]
    - Lint/format run + AGENTS.md update + final commit

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 5 (final, after 10 & 11)
  - **Blocks**: None (final task)
  - **Blocked By**: Tasks 10, 11

  **References**:
  - `AGENTS.md` — Current version to update
  - `pyproject.toml:55-58` — ruff config (target-version, line-length, select rules)

  **Acceptance Criteria**:
  - [ ] `ruff check src/ tests/ --select E,F,I,W --target-version py310` → 0 errors
  - [ ] `ruff format --check src/ tests/` → Already formatted
  - [ ] `python -m pytest tests/ -v --tb=short` → All pass
  - [ ] `python -c "from rosbag_mcp.server import TOOL_DEFINITIONS; assert len(TOOL_DEFINITIONS) == 27"` → passes
  - [ ] AGENTS.md reflects new architecture (cache, config, sensors modules)

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: Everything clean and passing
    Tool: Bash
    Steps:
      1. ruff check src/ tests/ --select E,F,I,W --target-version py310
      2. ruff format --check src/ tests/
      3. python -m pytest tests/ -v --tb=short
      4. python -c "from rosbag_mcp.server import TOOL_DEFINITIONS; print(f'{len(TOOL_DEFINITIONS)} tools'); assert len(TOOL_DEFINITIONS) == 27"
    Expected Result: 0 lint errors, format clean, all tests pass, 27 tools
    Evidence: All command outputs
  ```

  **Commit**: YES
  - Message: `chore: lint, format, update AGENTS.md for v0.2.0`
  - Files: All modified files + AGENTS.md
  - Pre-commit: `ruff check src/ tests/ && python -m pytest tests/ -v`

---

## Commit Strategy

| After Task | Message | Key Files | Verification |
|------------|---------|-----------|--------------|
| 1 | `feat: add tiered cache module, bump version to 0.2.0` | cache.py, __init__.py, pyproject.toml | ruff check |
| 2 | `feat(bag_reader): integrate tiered cache for connection pooling and metadata caching` | bag_reader.py | import test, 24 tools load |
| 3 | `feat(config): add ServerConfig and SchemaManager with YAML schema system` | config.py, *.yaml | import test |
| 4+5+6 | `feat: enhance image, search, trajectory tools` | analysis.py, messages.py | ruff check |
| 7 | `feat(sensors): add PointCloud2, JointState, DiagnosticArray analysis tools` | sensors.py | import test |
| 8 | `feat(logging): add Python logging throughout all modules` | all tools/*.py, server.py | import test |
| 9 | `feat(server): wire 3 new sensor tools, update schemas for enhanced tools` | server.py, tools/__init__.py, pyproject.toml | 27 tools check |
| 10+11 | `test: add regression tests and cache performance benchmarks` | tests/*.py | pytest pass |
| 12 | `chore: lint, format, update AGENTS.md for v0.2.0` | all + AGENTS.md | full suite |

---

## Success Criteria

### Verification Commands
```bash
# Import test — no cycles, all modules load
python -c "import rosbag_mcp.server; print('OK')"

# Tool count — 27 tools registered
python -c "from rosbag_mcp.server import TOOL_DEFINITIONS, TOOL_HANDLERS; assert len(TOOL_DEFINITIONS) == len(TOOL_HANDLERS) == 27; print('27 tools OK')"

# Version check
python -c "from rosbag_mcp import __version__; assert __version__ == '0.2.0'; print('v0.2.0 OK')"

# Lint
ruff check src/ tests/ --select E,F,I,W --target-version py310

# Format
ruff format --check src/ tests/

# Tests
python -m pytest tests/ -v --tb=short

# Benchmarks
python -m pytest tests/test_benchmarks.py -v -s

# Cache module
python -c "from rosbag_mcp.cache import BagCacheManager; m = BagCacheManager(); print(m.stats())"

# Config without YAML
python -c "import sys; sys.modules['yaml'] = None; from rosbag_mcp.config import ServerConfig; c = ServerConfig(); print(c.time_tolerance)"

# All sensors importable
python -c "from rosbag_mcp.tools.sensors import analyze_pointcloud2, analyze_joint_states, analyze_diagnostics; print('Sensors OK')"
```

### Final Checklist
- [ ] All 24 existing tools working (backward compatible)
- [ ] 3 new sensor tools registered and importable
- [ ] Cache system integrated into bag_reader
- [ ] CompressedImage + new encodings + smart resize in get_image_at_time
- [ ] contains + field_exists + correlation in search_messages
- [ ] Angle-based waypoints + efficiency metrics in analyze_trajectory
- [ ] Config system works without PyYAML
- [ ] Logging in all modules
- [ ] All tests pass (≥20 tests)
- [ ] Benchmarks pass and show measurable speedup
- [ ] ruff clean
- [ ] Version 0.2.0 everywhere
- [ ] AGENTS.md updated
