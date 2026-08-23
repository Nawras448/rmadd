<p align="center">
  <img src="docs/assets/logo.png" alt="rmadd Logo" width="180"/>
</p>

# rmadd

An all-in-one, modular Textual-based TUI application for Linux system
monitoring and cross-distribution package management.

Current release: **v0.2.0** (see `CHANGELOG.md`).

---

## Features

* **Instant Optimistic UI** — actions mutate the UI and in-memory state
  immediately (zero-latency row removal), then reconcile with the real
  subprocess result through a confirm/revert lifecycle on the state bus.
* **Direct Action Flow** — no blocking confirmation dialogs: `remove` fires
  immediately; a failed removal silently restores the row and surfaces a
  toast.
* **Dynamic Search Action Bar** — the Search tab is context-aware: installed
  packages show Remove/Update, available ones show Install, with a live
  installed/available status label and installed-version enrichment.
* **Physical Local Binary Management** — the Local Binaries tab resolves
  absolute paths via `$PATH` scanning and `shutil.which()`, unlinks
  user-level binaries directly, and elevates via `pkexec`/`sudo` for system
  paths like `/usr/bin`.
* Dynamic System Info: distribution, kernel, architecture and uptime without
  distro-specific hardcoding.
* Package Manager Detection: probes and counts installed packages across
  many manager families:
  - Native: apt, dpkg, dnf, yum, rpm, zypper, apk, pacman, emerge, xbps,
    nix, eopkg, slackpkg.
  - Universal: flatpak, snap, brew, appimage.
  - Ecosystem: pip, pipx, cargo, npm, pnpm, yarn, bun, go, gem, composer.
* Keyboard-driven TUI built with Textual: tabbed store, live search,
  streaming install/remove/update with progress, cancel + ETA.
* CLI subcommands for scripting: info, packages, hardware.
* Non-blocking I/O: subprocess calls run off the UI thread (thread pool and
  asyncio.to_thread), debounced search, 5s stats refresh, TTL caches.
* Flat package layout: everything lives under one `rmadd/` package - no DI
  container, no hexagonal indirection.
* Rich operation feedback: streamed `OpResult` failure contexts
  (auth-denied / timeout / cancelled / manager-missing) surfaced as typed
  toasts plus a live status chip (`gen:N · k/M managers done · ms`) on the
  search tab.
* Batch operations with per-target isolation (`OpReport`): one failing
  manager never drops the rest of the report; skipped targets are recorded,
  never silently dropped.
* Responsive tables: width-tiered column hiding behind a debounced resize
  handler, with cursor/scroll locked across refreshes and profile switches.
* Focus pipeline: modals capture focus on push and restore it verbatim on
  dismissal; progress panels focus their Cancel button immediately.
* Opt-in removal confirmation (`ui.confirm_removal`) and a single-keystroke
  keybinding overlay (`?`).

## Visual Overview

All screenshots live in `docs/assets/`. Sizes are fixed for a consistent,
scannable layout: the hero shot is 640 px wide, grid shots are 320 px each,
and the logo is 180 px.

<!-- Insert GIF demo here (e.g., docs/assets/optimistic-removal.gif) -->

**Search & Dynamic Action Bar**

<p align="center">
  <img src="docs/assets/search-view.png" alt="Search Programs & Dynamic Action Bar" width="640"/>
</p>

<p align="center">
  <em>Search tab: live results, installed-status labels, and the context-aware
  action bar (Install / Remove / Update).</em>
</p>

<table align="center">
  <tr>
    <td align="center">
      <img src="docs/assets/installed-apps.png" alt="Installed Applications View" width="320"/>
      <br/>
      <em>Installed Applications with per-manager filtering.</em>
    </td>
    <td align="center">
      <img src="docs/assets/local-binaries.png" alt="Local Binaries & Instant Zero-Latency Deletion" width="320"/>
      <br/>
      <em>Local Binaries — rows vanish instantly on removal and reappear on
      failure.</em>
    </td>
  </tr>
</table>

<!-- Insert GIF demo here (e.g., docs/assets/demo.gif) -->


## Requirements

* Python 3.10+
* textual (see requirements.txt)

## Project Structure

```text
main.py
  Backward-compatible entry point delegating to `rmadd.main`.
rmadd/
  models.py                  PackageManager enum (27), tier metadata, Package,
                             PackageCollection, SystemInfo and hardware dataclasses.
  state.py                   PackageStateBus - app-wide pub/sub bus with
                             pending/confirmed/reverted lifecycle phases.
  ui_keys.py                 Row-key codec shared by tables and screens.
  controllers/
    optimistic_state.py      Pure optimistic state machine (no UI imports):
                             pending -> confirmed/reverted with verbatim
                             restore of removed rows at their original index.
    operations_controller.py Bus intake -> state deltas -> widget updates;
                             owns start/settle/revert orchestration and
                             manager rediscovery.
    search_controller.py     Live multi-manager search, version enrichment,
                             dynamic action bar.
    installed_controller.py  Load/hydrate/filter, per-manager tab strip,
                             15 s stale-reload policy.
    local_binaries_controller.py  Opt-in PATH scan + deletion view.
    tools_controller.py      Installer-tool catalog + AppImage installs.
    stats_controller.py      System card + per-manager counts (5 s tick).
  package_managers/
    base.py                  BaseAdapter - streaming runner with two-phase
                             deadlines (auth vs execution budget), pgid-directed
                             process-group cleanup and OpResult failure contexts;
                             discovery registry.
    service.py               PackageManagerService: search/install/counts,
                             batch runner (OpReport), thread pools, TTL caches.
    <manager>.py             one adapter per manager (apt, dnf, flatpak, ...)
    local.py                 opt-in PATH binary scanner + physical removal.
  screens/
    store_screen.py          StoreScreen: composition root wiring controllers
                             to the widget tree (layout, bindings, events).
    widgets/                 PackageTable, ToolsTable, SystemCard.
    install_progress_screen.py, package_detail_screen.py,
    appimage_install_screen.py
  system_info.py             SystemInfoService + HostnamectlAdapter
  hardware.py                ProcFsAdapter + HardwareMonitorService.
  cache.py                   TTL caching for system and hardware providers.
  tools.py                   InstallerTool detection for the Tools tab.
  tui.py                     RmaddTuiApp (cyberpunk theme).
  cli.py                     info / packages / hardware subcommands.
  config.py                  JSON config (confirm_removal, op_timeout_seconds).
  logging.py                 file logging setup.
style.tcss                   Textual CSS stylesheet.
docs/
  LOCAL_BINARIES.md          Local binaries guide (discovery & deletion).
  assets/                    Logos, screenshots and demo GIFs.
```

## Download

```bash
curl -L https://github.com/Nawras448/rmadd/archive/refs/heads/main.tar.gz | tar -xz

```

## Usage

```bash
pip install -r requirements.txt
python3 main.py                 # bare invocation opens the TUI
rmadd                           # same, via the installed launcher

Any arguments route to the CLI subcommands -- no config switch required:

```bash
rmadd info                      # system info
rmadd packages                  # per-manager package counts
rmadd hardware                  # CPU / memory summary
rmadd --help                    # usage
python3 -m rmadd packages       # module form works too
```

* Config file: `~/.config/rmadd/config.json`
* Logs: `~/.local/share/rmadd/logs/app.log`

## Key Bindings

| Key      | Action                                |
|----------|---------------------------------------|
| F1 - F5  | Switch tab (Tools/Search/Installed/Local/About) |
| i / r / u | Install / remove / update selected package |
| Enter    | Open package detail                   |
| R (app)  | Force refresh all stats               |
| q        | Quit                                  |

## Documentation

* `ARCHITECTURE.md` — module map, data flow, `PackageStateBus` lifecycle.
* `docs/LOCAL_BINARIES.md` — local binary discovery, path resolution and
  deletion permissions.
