# 📦 rmadd 0.1.0

An all-in-one, modular **Textual-based TUI application** designed for Linux system monitoring and cross-distribution package management.

> 🚧 **Under Active Development (قيد التطوير النشط)**  
> Early-stage WIP. Features, architecture, and UI layouts are subject to rapid changes.

---

## 🚀 Features

* 📊 **Dynamic System Info:** Distribution details, kernel version, and hardware architecture without distro-specific hardcoding.
* 📦 **Package Manager Detection:** Automatically probes and counts installed packages across `Native` (apt, dnf, pacman, ...), `Universal` (flatpak, snap, AppImage, brew), and `Ecosystem` (pip, npm, cargo, ...) managers.
* 🧩 **Modular Architecture:** Hexagonal design — ports & adapters per feature, a manual DI container, and a central pub/sub state bus.
* 🖥️ **Keyboard-driven TUI:** Built with Python's [Textual](https://textual.textualize.io/) framework (tabbed store, live search, streaming install progress with cancel/ETA).
* 🧵 **Non-blocking I/O:** All subprocess calls run off the UI thread via a thread pool and `asyncio.to_thread`, with debounced search and a 5s stats refresh.

## 🛠️ Project Structure

```text
rmadd/
├── main.py                 # Entry point; builds the DI container, selects UI mode
├── shared/                 # Cross-cutting: DI container, config, logging, cache, state bus
├── features/
│   ├── package_store/      # Ports, domain, registry, 27 adapters, service, presentation
│   │   └── presentation/   # StoreScreen + table/progress/detail/AppImage widgets
│   ├── system_info/        # System info service + HostnamectlAdapter + SystemCard
│   ├── system_monitor/     # Hardware monitoring adapters (wired, UI pending)
│   └── ui_switch/          # UI-mode dispatch: TUI (active), CLI (minimal), GUI (stub)
├── style.tcss              # Textual CSS stylesheet
└── ARCHITECTURE.md         # Detailed architecture & navigation guide
```

## 🚀 Usage

```bash
pip install -r requirements.txt   # currently: textual>=8.2.8,<9
python main.py                    # TUI mode (default)
```

Config lives at `~/.config/rmadd/config.json`; logs at `~/.local/share/rmadd/logs/app.log`.

## ⌨️ Key Bindings

| Key | Action |
|---|---|
| `F1`–`F5` | Switch tab (Tools / Search / Installed / Local / About) |
| `i` / `r` / `u` | Quick install / remove / update selected package |
| `Enter` | Package details |
| `r` (app) | Force refresh all stats |
| `q` | Quit |