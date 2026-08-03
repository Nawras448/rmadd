# rmadd 0.1.0

An all-in-one, modular Textual-based TUI application for Linux system
monitoring and cross-distribution package management.

> UNDER ACTIVE DEVELOPMENT (WIP). Structure and features change quickly.

---

## Features

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

## Requirements

* Python 3.10+
* textual (see requirements.txt)

## Project Structure

```text
main.py
  Entry point; builds services, selects UI mode (tui or cli).
rmadd/
  models.py                  PackageManager, Package, PackageCollection,
                             SystemInfo and hardware dataclasses.
  package_managers/          BaseAdapter + discovery registry, plus one
    base.py                  module per package manager and the service.
    service.py               PackageManagerService: search/install/counts.
    <manager>.py             one adapter per manager (apt, dnf, flatpak, ...)
    local.py                 opt-in PATH binary scanner.
  screens/
    store_screen.py          StoreScreen: the tabbed store screen.
    widgets/                 PackageTable, ToolsTable, SystemCard.
    install_progress_screen.py, package_detail_screen.py,
    appimage_install_screen.py
  system_info.py             SystemInfoService + HostnamectlAdapter
  hardware.py                ProcFsAdapter + HardwareMonitorService.
  cache.py                   TTL caching for system and hardware providers.
  tools.py                   InstallerTool detection for the Tools tab.
  tui.py                     RmaddTuiApp (cyberpunk theme).
  cli.py                     info / packages / hardware subcommands.
  config.py                  JSON config (ui.mode).
  logging.py                 file logging setup.
style.tcss                   Textual CSS stylesheet.
```

## Usage

```bash
pip install -r requirements.txt
python main.py                  # TUI (default)

# CLI mode
echo '{"ui":{"mode":"cli"}}' > ~/.config/rmadd/config.json
python main.py info
python main.py packages
python main.py hardware
```

Reset to TUI mode:

```bash
echo '{"ui":{"mode":"tui"}}' > ~/.config/rmadd/config.json
```

* Config file: `~/.config/rmadd/config.json`
* Logs: `~/.local/share/rmadd/logs/app.log`

## Key Bindings

| Key      | Action                                |
|----------|---------------------------------------|
| F1 - F5  | Switch tab (Tools/Search/Installed/Local/About) |
| i / r / u | Install / remove / update selected package |
| Enter    | Open package detail                   |
| r (app)  | Force refresh all stats               |
| q        | Quit                                  |

## Documentation

See `ARCHITECTURE.md` for the module map and data flow.
