# Changelog

All notable changes to rmadd are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **Dispatch is now argument-driven:** bare `rmadd` / `python -m rmadd`
  always launches the interactive TUI; any arguments (`info`, `packages`,
  `hardware`, `--help`, unknown commands) route to the CLI parser with
  standard exit codes. The legacy `ui.mode` config key is no longer
  consulted for dispatch (it previously forced bare invocations into the
  argparse help view).
- `main()` accepts an optional `argv` list for hermetic dispatch testing.
- Root `python main.py` is now a thin delegator to `rmadd.main`; the
  bootstrap lives inside the package so `python -m rmadd` works.

### Added
- `[project.scripts]` entry point (`rmadd`) in `pyproject.toml`.
- Hardened `install.sh`: prerequisite checks for `python3`,
  `python3-venv` (probe plus runtime venv-creation guard) and `git` with
  actionable apt guidance; launcher wrapper executes the package via
  `python -m rmadd "$@"` from the isolated venv.

## [0.2.0] - 2026-08-23

First hardened release: correctness fixes, controller decomposition,
service/escalation hardening and a polished, responsive TUI.

### Milestone 0 — Correctness & Safety Nets
- Fixed update operations crashing (`TypeError`) in `InstallProgressScreen`
  by switching service dispatch to keyword arguments.
- `Config` now deep-copies defaults; user config no longer contaminates
  `DEFAULT_CONFIG` across instances.
- `detect_tools()` is pure (returns `dataclasses.replace` copies) instead of
  mutating the shared installer catalog.
- Row-key codec (`rmadd/ui_keys.py`): keys decode on the last separator, so
  package names containing `|` (LOCAL binaries) no longer corrupt routing.
- Force-refresh rebound to `R`; lowercase `r` stays quick-remove.

### Milestone 1 — Structural Refactor
- Extracted the optimistic lifecycle into a pure state machine
  (`rmadd/controllers/optimistic_state.py`, zero UI imports).
- Quirk fixes: reverting an install of a pre-existing package keeps it;
  reverted LOCAL removals never pollute the managed-installed set; removal
  reverts without a prior instant-removal are strict no-ops.
- `StoreScreen` halved into a composition root over six controllers
  (search / installed / local / tools / stats / operations).
- **Critical fix:** bus events emitted from the UI thread were silently
  dropped (`call_from_thread` raises on same-thread); events now dispatch
  inline. Pending/confirmed/reverted reconciliation actually runs.

### Milestone 2 — Service & Escalation Hardening
- `OpResult` + `FailureReason` replace binary failure tuples; two-phase
  deadlines separate an auth budget (silent polkit/sudo prompts) from the
  execution budget (`ui.package_managers.op_timeout_seconds`).
- Escalation candidates resolve to absolute paths (no PATH re-resolution),
  pkexec denials fall back to sudo, and termination targets the captured
  process group with a SIGTERM→SIGKILL ladder.
- Failure reasons surface as differentiated toasts/result lines
  (`rmadd/screens/op_feedback.py`); sudo password prompts are detected and
  announced in the progress console.
- Batch runner (`run_batch` / `batch_update_all`) aggregates per-target
  results into `OpReport` with failure isolation and skip accounting.
- Executor hygiene: dual named long-lived pools (`rmadd-query`,
  `rmadd-fetch`) plus scanner probe pool; explicit `shutdown()`.
- Batched ops honour cancellation between targets without dropping the
  report.

### Milestone 3 — TUI & UX Polish
- Key-aware row reconciliation replaces full table rebuilds; cursor and
  scroll stay locked across background refreshes (key match, nearest-index
  fallback).
- Optimistic pending rows render glyph overrides plus Rich dimming across
  Installed/Search/Local tables; action buttons disable while an op is in
  flight and a screen-level guard blocks double-fires.
- Search status chip (`gen:N · k/M managers done · ms`), Esc cancels live
  search and clears input.
- Focus capture/restoration around every modal; progress panels focus their
  Cancel button.
- `?` opens a keybinding help overlay.
- Responsive columns: width-tiered hiding behind a debounced resize handler
  for package and tools tables.
- Opt-in removal confirmation modal (`ui.confirm_removal`, default off).

### Milestone 4 — Hygiene, Docs & Release
- Purged unused imports across 35 modules, duplicate imports and dead API
  surface (`progress_callback` parameters, subscription hooks,
  `PackageCollection.count_by_manager`, legacy tuple shim).
- `ruff` and `mypy` configurations added (`pyproject.toml`); both pass clean
  over the codebase (mypy: 64 files, 0 issues; gradual-typing profile for
  the dynamic UI layer).
- GitHub Actions CI (`.github/workflows/ci.yml`): pytest on Python
  3.10–3.12 plus ruff lint and mypy report.
- Architecture and README documentation finalized for the end-state design.

## [0.1.0]
Initial development releases (pre-changelog): Textual store UI, discovery
registry across native/universal/ecosystem managers, optimistic lifecycle,
installed-cache SWR with disk persistence, system/hardware monitoring.
