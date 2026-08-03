# 📦 rmadd 0.1.0

An all-in-one, modular **Textual-based TUI application** designed for Linux system monitoring and cross-distribution package management.

> 🚧 **Under Active Development (قيد التطوير النشط)**  
> This project is currently an early-stage Work in Progress (WIP). Features, architecture, and UI layouts are subject to rapid changes.

---

## 🚀 Features

* 📊 **Dynamic System Info:** Displays distribution details, kernel version, and hardware architecture without distribution-specific hardcoding.
* 📦 **Package Manager Detection:** Automatically scans and counts installed packages across multiple package managers (`APT`, `Snap`, `Flatpak`, etc.).
* 🧩 **Modular Architecture:** Built with decoupled UI views and clean core abstractions for seamless scaling.
* 🖥️ **Keyboard-driven UI:** Responsive Terminal User Interface built with Python's [Textual](https://textual.textualize.io/) framework.

---

## 🛠️ Project Structure

```text
rmadd/
├── core/              # Core logic & system utilities (SystemInfo, package queries)
├── widgets/           # Modular Textual UI components (UserCard, ProgramsView, etc.)
├── style.tcss         # Textual CSS stylesheet
└── main.py            # Main application entry point