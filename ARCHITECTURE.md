# rmadd - Architecture Guide

## 1. Layout

Everything lives in the `rmadd/` package plus a thin `main.py` entry point.

### Entry point & wiring

| File | Role |
|---|---|
| `main.py` | Builds the three services directly (no DI container), dispatches to tui/cli via `config.ui_mode`. |
| `rmadd/config.py` | JSON config at `~/.config/rmadd/config.json` (`ui.mode`: tui or cli). |
| `rmadd/logging.py` | Logs to `~/.local/share/rmadd/logs/app.log`. |
| `rmadd/state.py` | `PackageStateBus` - app-wide pub/sub bus. |

### Textual TUI layer

| File | Role |
|---|---|
| `rmadd/tui.py` | `RmaddTuiApp` - root App, cyberpunk theme, mounts StoreScreen, owns state bus. |
| `rmadd/screens/store_screen.py` | `StoreScreen` - one TabbedContent screen (Tools/Search/Installed/Local/About). |
| `rmadd/screens/widgets/package_table.py` | `PackageTable` + `apply_pane_floor()` sizing. |
| `rmadd/screens/widgets/tools_table.py` | `ToolsTable` widget. |
| `rmadd/screens/widgets/system_card.py` | `SystemCard` (About tab). |
| `rmadd/screens/install_progress_screen.py` | `InstallProgressScreen` modal (progress, ETA, cancel, emits bus events). |
| `rmadd/screens/package_detail_screen.py` | `PackageDetailScreen` modal. |
| `rmadd/screens/appimage_install_screen.py` | `AppImageInstallScreen` file picker. |
| `style.tcss` | Textual CSS stylesheet (root). |

### Core logic

| File | Role |
|---|---|
| `rmadd/models.py` | `PackageManager` enum (27), tier metadata, `Package`, `PackageCollection`, `SystemInfo`, hardware dataclasses. |
| `rmadd/package_managers/base.py` | `BaseAdapter` (shared runner, privilege handling), `discover_managers()`, `resolve_system_manager()`. |
| `rmadd/package_managers/<mgr>.py` | One module per manager (apt, dnf, flatpak, snap, pip, ...). |
| `rmadd/package_managers/service.py` | `PackageManagerService` - search/install/counts, thread pool, TTL caches. |
| `rmadd/package_managers/local.py` | `LocalBinaryScanner` (opt-in PATH scan). |
| `rmadd/system_info.py` | `SystemDataSource`, `HostnamectlAdapter`, `SystemInfoService`. |
| `rmadd/hardware.py` | `HardwareDataSource`, `ProcFsAdapter` (CPU/mem/disk/GPU/network), `HardwareMonitorService`. |
| `rmadd/cache.py` | `CachingSystemAdapter` / `CachingHardwareAdapter` (TTL decorators). |
| `rmadd/tools.py` | `INSTALLER_TOOLS` + `detect_tools()`. |
| `rmadd/cli.py` | `CliApp` - info / packages / hardware subcommands. |

The old hexagonal `features/` and `shared/` trees (ports, adapters, DI container,
registry) were removed; all that logic now lives in the flat modules above.

## 2. Data Flow

```
main.py
  system_service   = SystemInfoService(CachingSystemAdapter(HostnamectlAdapter()))
  hardware_service = HardwareMonitorService(CachingHardwareAdapter(ProcFsAdapter()))
  package_service  = PackageManagerService(dict(discover_managers()))
  ui_mode == "tui" -> RmaddTuiApp(system, package, hardware).run()
  ui_mode == "cli" -> CliApp(system, package, hardware).run(sys.argv[1:])
```

1. **Read path (off the UI thread):** StoreScreen calls services via
   `asyncio.to_thread`. PackageManagerService fans out to a ThreadPoolExecutor,
   merges results, caches counts and searches.
2. **Write/op path:** key/button action -> InstallProgressScreen ->
   `package_service.install/remove/update` -> adapter `_run_stream()` (cancel
   via threading.Event) -> emits to the bus on completion.
3. **Refresh path:** `state_bus.emit(kind, name, mgr)` -> StoreScreen
   `_on_state_event` -> updates installed set, invalidates counts, re-runs
   search, reloads stats, triggers `_rediscover_managers()`.
4. **Background:** StoreScreen starts a 5s interval for stats; local scan and
   live search are lazy/debounced.

## 3. Gotchas & going forward

- **Reactivity:** the app only renders what the state bus tells it to. Any new
  modal that changes package state must end with
  `app.state_bus.emit("install"|"remove"|"update", name, mgr)`.
- **Adding a manager:** 1) add enum + tier/meta in `rmadd/models.py`;
  2) add `<manager>.py` in `rmadd/package_managers/` exposing an `Adapter`
  subclass of `BaseAdapter`; 3) register the module. Register modules discovered
  automatically via `discover_managers()`.
- **Debugging:** logs at `~/.local/share/rmadd/logs/app.log`; StoreScreen owns
  `_track`/`on_unmount` for background tasks; force refresh via `r`.
- All bindings live in `rmadd/tui.py`.

## 4. Package state bus

`rmadd/state.py` `PackageStateBus` supports subscribe / unsubscribe / emit.
The contract is `emit(kind, name, mgr)`.

| kind             | name | mgr            | Emitter                                            |
|------------------|------|----------------|----------------------------------------------------|
| install          | pkg  | manager        | InstallProgressScreen on success                   |
| remove           | pkg  | manager        | InstallProgressScreen on success                   |
| update           | pkg  | manager        | InstallProgressScreen on success                   |
| install          | pkg  | APPIMAGE       | StoreScreen (AppImage install path)                |
| managers_changed | ""   | None           | StoreScreen `_rediscover_managers()`               |

Subscribers: StoreScreen `_on_state_event` (mounted/unmounted with the screen).

This is the only reactive channel the UI uses: modals must end with
`app.state_bus.emit(action, name, mgr)` or the Installed tab will not reset.
