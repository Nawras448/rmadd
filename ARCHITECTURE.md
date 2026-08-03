# rmadd — Architecture Guide

## 1. Project Directory Mapping

### Active core (keep — this is the app)

**Entry point & wiring**

| File | Role |
|---|---|
| `main.py` | Entry point; builds `DIContainer`, selects UI mode (tui/gui/cli) via config |
| `shared/di_container.py` | Manual DI container: sources -> lazy singleton services |
| `shared/config.py` | JSON config at `~/.config/rmadd/config.json` with defaults |
| `shared/logging.py` | Logs to `~/.local/share/rmadd/logs/app.log` (file handler only) |
| `shared/cache.py` | `CachingSystemAdapter` / `CachingHardwareAdapter` TTL decorators |
| `shared/state.py` | `PackageStateBus` — app-wide pub/sub (the central state bus) |

**Textual TUI layer**

| File | Role |
|---|---|
| `features/ui_switch/presentation/tui/app.py` | `RmaddTuiApp` — root App, cyberpunk theme, mounts `StoreScreen` |
| `features/package_store/presentation/store_screen.py` | `StoreScreen` — the single TabbedContent screen (Tools/Search/Installed/Local/About) with all view logic |
| `features/package_store/presentation/package_table.py` | `PackageTable` widget + `apply_pane_floor()` sizing |
| `features/package_store/presentation/tools_table.py` | `ToolsTable` widget |
| `features/package_store/presentation/install_progress_screen.py` | `InstallProgressScreen` modal (progress bar, ETA, cancel, emits bus events) |
| `features/package_store/presentation/package_detail_screen.py` | `PackageDetailScreen` modal |
| `features/package_store/presentation/appimage_install_screen.py` | `AppImageInstallScreen` file-picker modal |
| `features/system_info/presentation/system_card.py` | `SystemCard` widget (About tab) |
| `style.tcss` | Textual CSS (reached via `CSS_PATH`) |

**Core logic**

| File | Role |
|---|---|
| `features/package_store/domain.py` | `PackageManager` enum (27), `TIER_MAP`, `MANAGER_META`, `Package`, `PackageCollection` |
| `features/package_store/ports.py` | ABCs: `GetPackagesUseCase`, `InstallPackageUseCase`, `BasePackageManager` |
| `features/package_store/registry.py` | `discover_managers()` — os-release parsing + binary probing + tier ordering |
| `features/package_store/adapters.py` | Concrete adapters + `ADAPTER_FACTORIES` map; shared `_run_stream`/privilege handling |
| `features/package_store/service.py` | `PackageManagerService` — use cases, thread pool, search/count caching |
| `features/package_store/installer_tools.py` | `INSTALLER_TOOLS` manifest + `detect_tools()` |
| `features/package_store/binary_scanner.py` | `LocalBinaryAdapter` / `LocalBinaryScanner` opt-in PATH scan |
| `features/system_info/{ports,domain,service}.py` | System-info ports, `SystemInfo`/`Distribution` dataclasses, `GetSystemInfoService` |
| `features/system_info/adapters.py` | `HostnamectlAdapter` (used in `main.py`) |
| `features/system_monitor/{ports,domain,service}.py` | Hardware monitor use cases + dataclasses |
| `features/system_monitor/adapters.py` | `ProcFsAdapter` (CPU/mem/disk/GPU/network readers) — wired but not rendered in the TUI |
| `features/ui_switch/presentation/cli/commands.py` | Minimal CLI (`info`, `packages`, `hardware`) |

### Ghost / dead / temporary files (safe to delete)

| Path | Why |
|---|---|
| `--version.hwm`, `--version.pwd`, `--version.pwi`, `-v.hwm`, `-v.pwd`, `-v.pwi` | Zero-byte probe artifacts (from a `--version` invocation writing to these names). Gitignored. |
| `tmp/0.log` | Empty, gitignored scratch. |
| `screens/` | Empty except a stale `__pycache__/home_screen.pyc`; the old `home_screen.py` was removed in `fab23e2`. |
| `tests/` (`unit/integration/e2e`) | Only `__init__.py` stubs; the `__pycache__` in `tests/unit` references a deleted `test_ai_benchmark.py`. |
| `widgets/` (entire package) + `core/core.py` | Orphaned: nothing reachable from `main.py` imports `widgets.*`. Leftover pre-refactor UI. |
| `default_mono.wav` | Tracked ~300 KB WAV; `RmaddTuiApp.bell()` is overridden so it is never played. |

Also safe to ignore: all `__pycache__/`, `.pytest_cache/` (already gitignored).

### Dormant / stub (not dead)

| File | Status |
|---|---|
| `features/system_monitor/*` | Wired but unrendered: `ProcFsAdapter` is built and cached, `hardware_service` is retrieved — yet no Textual widget displays hardware data. Downgrade candidate, not delete. |
| `features/ui_switch/presentation/gui/app.py` | Intentional stub ("not yet implemented"). |
| `features/system_info/adapters.py::LsbReleaseAdapter` | Unused duplicate of `HostnamectlAdapter`. |

## 3. Architecture & Data Flow

**Pattern:** hexagonal / ports & adapters + a shared pub/sub state bus, driven by an event-based Textual app.

```
 main.py
   │  build_container()
   ▼
 DIContainer (shared/di_container.py)
   ├── system_source  = CachingSystemAdapter(HostnamectlAdapter)
   ├── hardware_source = CachingHardwareAdapter(ProcFsAdapter)        # dormant
   └── package_sources = discover_managers() -> {PackageManager: adapter}
        # registry.py reads /etc/os-release, probes binaries, sorts by tier
        # ADAPTER_FACTORIES maps each PackageManager to a BaseAdapter subclass
   ▼
 RmaddTuiApp (features/ui_switch/presentation/tui/app.py)
   │  creates PackageStateBus (shared/state.py)
   ▼
 StoreScreen (features/package_store/presentation/store_screen.py)
```

**Data flows around the loop:**

1. **Read path (sync, off the UI thread):** `StoreScreen` calls services via `asyncio.to_thread(...)`.
   - `package_service.list_installed() / search() / get_all_counts()` — `PackageManagerService` fans work out to a `ThreadPoolExecutor` (max 8), runs each adapter, merges results, caches counts (`COUNTS_TTL=60`) and searches (`SEARCH_TTL=60`).
   - Adapters (`BaseAdapter`) shell out to real CLIs, with privilege escalation via `pkexec -> sudo`.
2. **Write/op path:** Button/key action -> push `InstallProgressScreen` -> `package_service.install/remove/update` -> adapter `_run_stream()` (streams output, cancel via `threading.Event`) -> on success emits to the bus:
   ```
   InstallProgressScreen._finish() -> app.state_bus.emit("install"|"remove"|"update", name, mgr)
   ```
3. **Refresh path:** `StoreScreen._on_state_event(kind, name, mgr)` -> `_apply_installed/_apply_removed` -> updates `_installed_set`, invalidates counts, re-runs search, reloads stats, re-triggers `_rediscover_managers()` (which emits `"managers_changed"` -> rebuild tabs).
4. **Background refresh:** `StoreScreen.on_mount()` starts `set_interval(5.0, _on_stats_tick)`; `_load_local()` scans the PATH lazily; live search is debounced (`0.25s`) and the installed filter (`0.15s`).

**Primary classes/modules by responsibility:**

- **Discovery & adapter lifecycle:** `registry.discover_managers()` / `discover_local_scanner()` / `resolve_system_manager()`; `domain.py` metadata (`MANAGER_META`, `TIER_MAP`, `capabilities`); adapter factories in `adapters.py`; runtime re-discovery via `PackageManagerService.add_source()` + `_rediscover_managers()`.
- **Tabbed content & reactive state:** `StoreScreen` (owns all `TabbedContent` panes, per-section action bars, tables, `_active_section`, lazy per-tab loading); widgets `PackageTable`, `ToolsTable`, `SystemCard`; state held in screen instance attrs (`_installed_set`, `_search_gen`, ...) with `PackageCollection` as the transform pipeline.
- **Event dispatch & async:** `PackageStateBus` (subscribe/unsubscribe/emit) in `shared/state.py`; `StoreScreen.on_*` Textual handlers -> `_track()` tasks; install modals run ops on a worker thread + `queue.Queue` drained by a 0.05s `set_interval` timer; task cancellation in `_track`/`on_unmount`.

---

## 4. Navigation Quick Reference

| Goal | Where? |
|---|---|
| Tweak UI layout / CSS | `style.tcss` for all styling; `StoreScreen.compose()` (lines ~67-146) owns the tab structure, IDs, action bars, scroll containers. |
| Add / restyle a widget | Model on `PackageTable` / `ToolsTable` (DataTable subclass pattern + `apply_pane_floor`); hook events in `StoreScreen.on_button_pressed` and the section-specific `_update_*_actions`. |
| Add a new package manager | 1) add enum + tier + `ManagerMeta` in `domain.py`; 2) add an adapter subclass following `AptAdapter` in `adapters.py`; 3) register it in `ADAPTER_FACTORIES`; 4) it appears automatically via discovery. |
| Debug background tasks / refresh / state sync | StoreScreen running methods (`_load_stats`, `_do_load_installed`, `_do_search`, `_apply_installed`, `_rediscover_managers`) and the thread pool in `PackageManagerService`; see `install_progress_screen.py` `_run` / `_drain_queue` for the worker-thread UI pump; logs: `~/.local/share/rmadd/logs/app.log`. |
| Modify the bus contract | `shared/state.py` (`emit(kind, name, mgr)`); subscribers: `StoreScreen._on_state_event`; emitters: `InstallProgressScreen._finish`, `StoreScreen` (AppImage + rediscover). |
| CLI/GUI modes | `features/ui_switch/presentation/cli/commands.py` and `gui/app.py`. |