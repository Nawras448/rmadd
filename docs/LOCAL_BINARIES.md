# Local Binaries — Discovery, Path Resolution & Deletion

The `PackageManager.LOCAL` source ("Local Binaries" tab) manages standalone
executables that are not tracked by any registered package manager (for
example manually downloaded CLI tools in `~/.local/bin`). It is implemented
in `rmadd/package_managers/local.py` by two classes:

| Class | Role |
|---|---|
| `LocalBinaryScanner` | Discovers and describes standalone executables; owns the version-probe cache. |
| `Adapter` | Exposes the scanner as a package source and performs physical deletion. |

## 1. Discovery locations

* Scanned by default (in order, first occurrence per name wins):
  `~/.local/bin`, `~/bin`, `/usr/local/bin`.
* The full system `$PATH` is scanned only when `scan_path=True` — this is
  opt-in because probing arbitrary executables with `--version`/`-v` can have
  side effects.
* Candidates must be files or symlinks (broken symlinks included) and
  executable (`X_OK`).
* Version probing is bounded (4 workers, configurable limit) and cached by
  file mtime; unprobed binaries are labelled `Standalone Binary`.

## 2. Absolute path resolution

When removal is requested for a name, the adapter resolves the absolute path
in two steps:

1. `LocalBinaryScanner.find_path(name)` — fast directory scan; covers the
   default dirs above and symlinks.
2. `shutil.which(name)` — full `$PATH` fallback; covers system locations such
   as `/usr/bin` that the default scan does not include.

If neither resolves, removal fails immediately with `binary not found`.

## 3. Deletion permissions

| Location | Mechanism |
|---|---|
| User-writable dirs (`~/.local/bin`, `~/bin`) | Direct `os.unlink(path)` |
| System dirs (`/usr/bin`, `/usr/local/bin`) | `PermissionError` triggers elevated removal: `pkexec rm -f -- <path>`, falling back to `sudo rm -f -- <path>` (120s timeout, output streamed to the progress console) |

After a successful delete the scanner's mtime-version cache is invalidated
for that path, so a re-scan reflects the removal immediately.

## 4. Failure semantics

`Adapter.remove()` returns `False` when: the binary is not found, unlinking
fails (e.g. `OSError`), or both elevation tools fail. In the TUI this maps
to `phase="reverted"` on the state bus: the optimistically removed row is
restored from `StoreScreen._removal_stash` and an error toast is shown.

`install()`, `update()` and `update_all()` are not supported for LOCAL
(standalone binaries have no package-manager upgrade path); they return
`False`.

## 5. Removal flow summary

```
Trigger (Local tab / detail screen)
  -> _remove_instantly(): row dropped, caches patched, package stashed
  -> adapter.remove(name): find_path -> which -> unlink | pkexec/sudo rm
  -> ok?  emit "confirmed"  (removal kept)
  -> fail? emit "reverted"  (row restored + error toast)
```
