# rmadd - Architecture Guide

## 1. Layout

Everything lives in the `rmadd/` package plus a thin `main.py` entry point.

### Entry point & wiring

| File | Role |
|---|---|
| `main.py` | Builds the three services directly (no DI container), dispatches to tui/cli via `config.ui_mode`. |
| `rmadd/config.py` | JSON config at `~/.config/rmadd/config.json` (`ui.mode`: tui or cli; `package_managers.op_timeout_seconds`: execution budget; `ui.confirm_removal`: opt-in removal confirmation). |
| `rmadd/logging.py` | Logs to `~/.local/share/rmadd/logs/app.log`. |
| `rmadd/state.py` | `PackageStateBus` - app-wide pub/sub bus. |

### Textual TUI layer

| File | Role |
|---|---|
| `rmadd/tui.py` | `RmaddTuiApp` - root App, cyberpunk theme, mounts StoreScreen, owns state bus. |
| `rmadd/screens/store_screen.py` | `StoreScreen` - composition root: layout (Tools/Search/Installed/Local/About), bindings, event routing; delegates behavior to controllers. |
| `rmadd/screens/widgets/package_table.py` | `PackageTable` + `apply_pane_floor()` sizing. |
| `rmadd/screens/widgets/tools_table.py` | `ToolsTable` widget. |
| `rmadd/screens/widgets/system_card.py` | `SystemCard` (About tab). |
| `rmadd/screens/install_progress_screen.py` | `InstallProgressScreen` modal (progress, ETA, cancel, emits bus events). |
| `rmadd/screens/package_detail_screen.py` | `PackageDetailScreen` modal. |
| `rmadd/screens/appimage_install_screen.py` | `AppImageInstallScreen` file picker. |
| `rmadd/screens/help_overlay.py` | `?` keybinding overlay (`ModalScreen`). |
| `rmadd/screens/confirm_remove.py` | Opt-in removal confirmation modal (y/n). |
| `rmadd/screens/op_feedback.py` | `OpResult` -> toast severity/message + result-pane markup. |
| `style.tcss` | Textual CSS stylesheet (root). |

Package/tools tables embed a `ResponsiveMixin`: trailing-edge debounced
resize with width-tiered column hiding, cursor-locked profile switches and
keyed reconciliation (M3 Step 1/3).

### Controllers (`rmadd/controllers/`)

| File | Role |
|---|---|
| `optimistic_state.py` | Pure optimistic state machine (zero UI imports): installed set/lists, pending ops with pre-op snapshots, removal stash; register/settle/revert return plain deltas. |
| `operations_controller.py` | Owns the state machine; translates bus events into widget updates; start/settle/revert orchestration + manager rediscovery. |
| `search_controller.py` | Debounced live search fan-out, version enrichment, dynamic action bar. |
| `installed_controller.py` | Service hydration, filtering, per-manager tab strip, 15 s stale reload. |
| `local_binaries_controller.py` | Lazy LOCAL scanner adapter, scan/render of the Local tab. |
| `tools_controller.py` | Installer-tool catalog actions + AppImage install flow. |
| `stats_controller.py` | System card + counts rendering; fast in-memory count patching. |
| `base.py` | `Controller` base wiring a controller to its host screen. |

Sibling coordination is late-bound through the screen (`ui.<controller>`); the
screen owns task tracking (`track`), bus subscription and thread marshalling.

### Core logic

| File | Role |
|---|---|
| `rmadd/models.py` | `PackageManager` enum (27), tier metadata, `Package`, `PackageCollection`, `SystemInfo`, hardware dataclasses. |
| `rmadd/package_managers/base.py` | `BaseAdapter` (streaming runner: `OpResult` failure contexts, two-phase auth/execution deadlines, pgid-directed cleanup, pkexec→sudo fallback), `OpReport` batch aggregate, runtime execution-timeout override, discovery registry. |
| `rmadd/package_managers/<mgr>.py` | One module per manager (apt, dnf, flatpak, snap, pip, ...). |
| `rmadd/package_managers/service.py` | `PackageManagerService` - search/install/counts, thread pool, TTL caches, batch runner (`run_batch`/`batch_update_all` → `OpReport`), dual named long-lived pools + `shutdown()`. |
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
2. **Write/op path:** key/button action -> StoreScreen `_do_pkg_action` ->
   `OperationsController.start` (emits `phase="pending"` on the bus) ->
   `InstallProgressScreen` -> `package_service.install/remove/update` ->
   adapter `run_stream()` returning an `OpResult` (cancel via threading.Event;
   auth vs execution deadlines) -> emits `"confirmed"` or `"reverted"` on
   completion.
3. **Refresh path:** `state_bus.emit(kind, name, mgr)` -> screen marshals to
   `OperationsController.on_bus_event` (same-thread inline, worker-thread via
   `call_from_thread`) -> updates installed set, invalidates counts, re-runs
   search, reloads stats, triggers rediscovery.
4. **Background:** StoreScreen starts a 5s interval for stats; local scan and
   live search are lazy/debounced.
5. **Focus pipeline:** every modal is pushed through `StoreScreen.push_modal`,
   which snapshots the focused widget and restores it on dismissal (falling
   back to the active section's primary widget); progress panels grab their
   Cancel button immediately.
6. **Removal safety valve:** when `ui.confirm_removal` is enabled,
   `_do_pkg_action` routes removals through `ConfirmRemoveScreen`; declines
   are surfaced as a cancelled label and never touch state.

## 3. Gotchas & going forward

- **Reactivity:** the app only renders what the state bus tells it to. Any op
  path must end with
  `app.state_bus.emit("install"|"remove"|"update", name, mgr, phase)`
  (default `"confirmed"`), or the Installed tab will not reset.
- **Adding a manager:** 1) add enum + tier/meta in `rmadd/models.py`;
  2) add `<manager>.py` in `rmadd/package_managers/` exposing an `Adapter`
  subclass of `BaseAdapter`; 3) register the module. Register modules discovered
  automatically via `discover_managers()`.
- **Debugging:** logs at `~/.local/share/rmadd/logs/app.log`; StoreScreen owns
   `_track`/`on_unmount` for background tasks; force refresh via `R`.
- All bindings live in `rmadd/tui.py`.

## 4. Package state bus

`rmadd/state.py` `PackageStateBus` supports subscribe / unsubscribe / emit.
The contract is `emit(kind, name, mgr, phase)` where `phase` is one of
`"pending"` (optimistic write, emitted by the screen that starts the op),
`"confirmed"` (succeeded) or `"reverted"` (failed/cancelled). The 3-arg form
defaults to `"confirmed"` for backward compatibility.

| kind             | name | mgr            | phase           | Emitter                                            |
|------------------|------|----------------|-----------------|----------------------------------------------------|
| install          | pkg  | manager        | pending         | OperationsController.start / PackageDetailScreen |
| install/remove/update | pkg | manager    | confirmed       | InstallProgressScreen on success                   |
| install/remove/update | pkg | manager    | reverted        | InstallProgressScreen on failure/cancel            |
| install          | pkg  | APPIMAGE       | confirmed       | StoreScreen (AppImage install path)                |
| managers_changed | ""   | None           | (n/a)           | OperationsController.rediscover_managers()         |

OperationsController owns the optimistic lifecycle, backed by the pure
`OptimisticPackageState`: `pending` writes straight into the in-memory
installed set (`register_pending`, keeping a pre-op snapshot), `confirmed`
settles it (`settle_confirmed`) and `reverted` undoes exactly what the op
changed (`revert_pending` restores removed rows verbatim at their original
index; installs of pre-existing packages survive) — all without a rescan.

### Optimistic lifecycle: Action Trigger -> Memory Mutation -> Subprocess Exec
-> Confirm/Revert

1. **Trigger / memory mutation** — for `remove`, StoreScreen first calls
   `_remove_instantly()`: the row is dropped from `PackageTable` (and the
   local/search tables), the key is discarded from `_installed_set`,
   `_installed_pkgs`/`_local_pkgs` are filtered, counts are patched from
   memory (`_fast_counts`), and the search action bar re-evaluates — all
   before any subprocess work. The original `Package` object plus its list
   index are stashed in `_removal_stash` so a failure can restore it
   verbatim (version, status, path for LOCAL).
2. **Pending** — `_start_operation` emits `phase="pending"`;
   `_register_pending` records the op in `_pending_ops` (this drives the
   context-aware guards and search action bar) and pushes
   `InstallProgressScreen`.
3. **Subprocess exec** — the adapter runs off the UI thread
   (`asyncio.to_thread` + `_run_stream`), streaming output and honouring
   cancel.
4. **Confirm** — success emits `"confirmed"`; `_settle_confirmed` settles
   (pops the stash, keeps the optimistic removal) and refreshes tabs,
   counts and search.
5. **Revert** — failure or cancel emits `"reverted"`; `_revert_pending`
   re-inserts the stashed `Package` at its original index, restores
   `_installed_set`, re-renders the view, and the caller surfaces a toast
   (`error` on failure, `warning` on cancel).

### Direct action flow (no confirmation dialogs)

Removal is deliberately un-gated: `_do_pkg_action("remove", ...)` runs the
instant mutation and starts the operation immediately from every context
(Installed, Search, Local) and from `PackageDetailScreen`. Safety is
provided reactively — a failed removal restores the row and notifies the
user — rather than by a blocking modal.

### Context-aware action rendering

* **Search tab** — `_update_search_actions()` shows Remove/Update for
  installed items and Install for available ones (`#search-status` renders
  "Already Installed"/"Available"); `_is_installed()` consults
  `_pending_ops` first so the bar updates mid-operation. Search results are
  enriched with the installed version when the adapter output lacks one.
* **PackageDetailScreen** — receives `is_installed` from the caller (no
  subprocess status probe), and `_rebuild_actions()` shows only the buttons
  the package state and the manager's `supports()` allow; `_run_action`
  re-guards install/remove/update and refreshes state after each op.

Subscribers: StoreScreen `_on_state_event_safe` marshals every event onto the
app loop (inline when already on it, `call_from_thread` from worker threads)
into `OperationsController.on_bus_event`; subscribed/unsubscribed with the
screen's mount cycle.

This is the only reactive channel the UI uses: op paths must end with
`app.state_bus.emit(action, name, mgr, phase)` or the Installed tab will not
reset.

See `docs/LOCAL_BINARIES.md` for the local binary discovery, path-resolution
and elevated-deletion mechanics.
