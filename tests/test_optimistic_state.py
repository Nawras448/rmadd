"""Characterization tests for OptimisticPackageState (Milestone 1, Step 1).

Each test transcribes a transition documented in ARCHITECTURE.md §4
(pending -> confirmed / reverted) from the exact StoreScreen logic that was
extracted verbatim. Quirks present in the source are pinned deliberately and
marked, so M2 can revisit them as conscious decisions rather than accidents.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from rmadd.controllers.optimistic_state import OptimisticPackageState, RestoreDirective
from rmadd.models import Package, PackageManager, PackageStatus

APT = PackageManager.APT
FLATPAK = PackageManager.FLATPAK
LOCAL = PackageManager.LOCAL
NPM = PackageManager.NPM


# --------------------------------------------------------------- fixtures --

def _pkg(name, mgr, version="", status=PackageStatus.INSTALLED):
    return Package(name=name, manager=mgr, version=version, status=status)


@pytest.fixture()
def state():
    """Hydrated mirror of a typical screen snapshot:
    installed=[htop@2.0(APT), spotify(FLATPAK), git(APT)], local=[moviebox]."""
    s = OptimisticPackageState()
    s.hydrate_installed([
        _pkg("htop", APT, "2.0"),
        _pkg("spotify", FLATPAK),
        _pkg("git", APT, "2.43"),
    ])
    s.hydrate_local([_pkg("moviebox", LOCAL, "Standalone Binary")])
    return s


# ------------------------------------------------------- PENDING phase -----

def test_pending_install_marks_installed_and_appends_placeholder(state):
    override = state.register_pending("install", "jq", APT)
    assert override == PackageStatus.PENDING
    assert state.is_installed("jq", APT) is True            # pending != "remove"
    assert state.pending_action("jq", APT) == "install"
    placeholders = [p for p in state.installed_packages() if p.name == "jq"]
    assert len(placeholders) == 1
    assert placeholders[0].status == PackageStatus.PENDING


def test_pending_install_existing_package_no_duplicate_row(state):
    override = state.register_pending("install", "htop", APT)
    assert override == PackageStatus.PENDING                # glyph still painted
    entries = [p for p in state.installed_packages() if p.name == "htop"]
    assert len(entries) == 1                                # no placeholder appended


def test_pending_remove_marks_not_installed_without_mutating_lists(state):
    before = state.installed_packages()
    override = state.register_pending("remove", "htop", APT)
    assert override is None
    assert state.is_installed("htop", APT) is False
    assert state.pending_action("htop", APT) == "remove"
    assert state.installed_packages() == before             # remove branch: pass


def test_pending_update_keeps_installed_flag(state):
    override = state.register_pending("update", "git", APT)
    assert override == PackageStatus.UPDATING
    assert state.is_installed("git", APT) is True
    assert len([p for p in state.installed_packages() if p.name == "git"]) == 1


def test_is_installed_prefers_pending_over_set(state):
    # Not hydrated, but a pending install flips the answer.
    state.register_pending("install", "cargo-binstall", NPM)
    assert state.is_installed("cargo-binstall", NPM) is True


# ----------------------------------------------------- CONFIRMED phase -----

def test_confirm_install_promotes_placeholder(state):
    state.register_pending("install", "jq", APT)
    state.settle_confirmed("install", "jq", APT)
    assert state.pending_action("jq", APT) is None
    rows = [p for p in state.installed_packages() if p.name == "jq"]
    assert len(rows) == 1 and rows[0].status == PackageStatus.INSTALLED
    assert state.is_installed("jq", APT) is True
    assert state.counts_by_manager()["apt"] == 3


def test_confirm_install_dedups_when_already_present(state):
    state.settle_confirmed("install", "htop", APT)          # no prior pending
    rows = [p for p in state.installed_packages() if p.name == "htop"]
    assert len(rows) == 1 and rows[0].status == PackageStatus.INSTALLED


def test_confirm_remove_prunes_everywhere_and_pops_stash(state):
    stashed = state.remove_instantly("htop", APT)
    state.settle_confirmed("remove", "htop", APT)
    names = {(p.name, p.manager) for p in state.installed_packages()}
    assert ("htop", APT) not in names
    assert state.counts_by_manager().get("apt") == 1        # git only
    assert state.stash_entry("htop", APT) is None
    assert stashed[0].name == "htop"


def test_confirm_remove_for_local_prunes_local_list(state):
    state.remove_instantly("moviebox", LOCAL)
    state.settle_confirmed("remove", "moviebox", LOCAL)
    assert all(p.name != "moviebox" for p in state.local_packages())


def test_confirm_update_clears_pending_and_restores_status(state):
    state.register_pending("update", "git", APT)
    state.settle_confirmed("update", "git", APT)
    assert state.pending_action("git", APT) is None
    git = next(p for p in state.installed_packages() if p.name == "git")
    assert git.status == PackageStatus.INSTALLED
    assert state.is_installed("git", APT) is True


# -------------------------------------------------------- REVERTED phase ----

def test_revert_install_removes_placeholder_only(state):
    state.register_pending("install", "jq", APT)
    directive = state.revert_pending("install", "jq", APT)
    assert directive is None
    assert all(p.name != "jq" for p in state.installed_packages())
    assert state.is_installed("jq", APT) is False
    assert state.counts_by_manager() == {"apt": 2, "flatpak": 1}


def test_revert_install_preserves_preexisting_entry(state):
    # Quirk-1 FIX: reverting an install of an already-installed package must
    # restore the previous state, never delete the real entry.
    state.register_pending("install", "htop", APT)
    state.revert_pending("install", "htop", APT)
    htop = [p for p in state.installed_packages() if p.name == "htop"]
    assert len(htop) == 1 and htop[0].version == "2.0"
    assert state.is_installed("htop", APT) is True
    assert ("htop", APT) in state.version_map()
    assert state.counts_by_manager() == {"apt": 2, "flatpak": 1}


def test_reregister_preserves_first_preexisting_flag(state):
    # Double registration must not mistake op #1's placeholder for a
    # pre-existing install when computing op #2's snapshot.
    state.register_pending("install", "jq", APT)
    state.register_pending("install", "jq", APT)
    state.revert_pending("install", "jq", APT)
    assert all(p.name != "jq" for p in state.installed_packages())
    assert state.is_installed("jq", APT) is False


def test_revert_remove_restores_verbatim_at_original_index(state):
    original = next(p for p in state.installed_packages() if p.name == "spotify")
    _, index = state.remove_instantly("spotify", FLATPAK)
    assert index == 1
    directive = state.revert_pending("remove", "spotify", FLATPAK)
    assert isinstance(directive, RestoreDirective)
    assert directive.index == 1 and directive.is_local is False
    assert directive.pkg is original                        # same object restored
    pkgs = state.installed_packages()
    assert [p.name for p in pkgs] == ["htop", "spotify", "git"]
    assert pkgs[1].version == ""                            # attributes untouched
    assert state.stash_entry("spotify", FLATPAK) is None
    assert state.is_installed("spotify", FLATPAK) is True


def test_revert_remove_clamps_stale_index_to_append(state):
    # Natural stale-index scenario: b stashed at idx 1 of [a,b,c]; confirming
    # another removal shrinks the list to [c]; reverting b must append.
    s = OptimisticPackageState()
    s.hydrate_installed([_pkg("a", APT), _pkg("b", APT), _pkg("c", APT)])
    s.remove_instantly("b", APT)
    s.settle_confirmed("remove", "a", APT)                  # [c]
    directive = s.revert_pending("remove", "b", APT)
    assert directive.index == 1                             # clamped to len
    assert [p.name for p in s.installed_packages()] == ["c", "b"]


def test_revert_remove_local_restores_without_polluting_installed_set(state):
    # Quirk-2 FIX: LOCAL binaries restored after a failed removal stay in the
    # local list and must NOT re-enter the managed-installed set/counts.
    state.remove_instantly("moviebox", LOCAL)
    directive = state.revert_pending("remove", "moviebox", LOCAL)
    assert directive.is_local is True
    assert [p.name for p in state.local_packages()] == ["moviebox"]
    assert all(p.name != "moviebox" for p in state.installed_packages())
    assert state.is_installed("moviebox", LOCAL) is False
    assert "local" not in state.counts_by_manager()


def test_revert_remove_managed_restores_installed_set_membership(state):
    # Managed packages removed optimistically were genuinely installed, so a
    # revert re-adds them to the set (and counts).
    state.remove_instantly("spotify", FLATPAK)
    assert state.counts_by_manager().get("flatpak") is None
    state.revert_pending("remove", "spotify", FLATPAK)
    assert state.counts_by_manager()["flatpak"] == 1
    assert state.is_installed("spotify", FLATPAK) is True


def test_revert_remove_missing_stash_is_noop(state):
    # No remove_instantly happened (e.g. PackageDetailScreen flow): no prior
    # memory mutation exists, so revert only clears the pending marker.
    before_pkgs = state.installed_packages()
    before_local = state.local_packages()
    directive = state.revert_pending("remove", "ghost", APT)
    assert directive is None
    assert state.installed_packages() == before_pkgs
    assert state.local_packages() == before_local
    assert state.stash_entry("ghost", APT) is None
    assert state.pending_action("ghost", APT) is None
    assert ("ghost", APT) not in state.version_map()


def test_revert_update_clears_pending_and_restores_status(state):
    state.register_pending("update", "htop", APT)
    state.revert_pending("update", "htop", APT)
    assert state.pending_action("htop", APT) is None
    htop = next(p for p in state.installed_packages() if p.name == "htop")
    assert htop.status == PackageStatus.INSTALLED


# ------------------------------------------------------------ mutations ----

def test_remove_instantly_stashes_identity_and_index_then_hides(state):
    spotify = next(p for p in state.installed_packages() if p.name == "spotify")
    pkg, index = state.remove_instantly("spotify", FLATPAK)
    assert pkg is spotify and index == 1
    stashed = state.stash_entry("spotify", FLATPAK)
    assert stashed.pkg is spotify and stashed.index == 1
    assert stashed.was_managed_installed is True            # genuinely installed
    assert all(p.name != "spotify" for p in state.installed_packages())
    assert state.is_installed("spotify", FLATPAK) is False  # pre-pending window


def test_remove_instantly_unknown_package_placeholders(state):
    pkg, index = state.remove_instantly("never-existed", NPM)
    assert isinstance(pkg, Package)
    assert pkg.name == "never-existed" and index == -1      # not found in either list
    stashed = state.stash_entry("never-existed", NPM)
    assert stashed.was_managed_installed is False           # must not re-enter set on revert


def test_remove_instantly_local_resolves_via_local_list(state):
    moviebox = next(p for p in state.local_packages())
    pkg, index = state.remove_instantly("moviebox", LOCAL)
    assert pkg is moviebox and index == 0                   # source = local list
    assert all(p.name != "moviebox" for p in state.local_packages())


# ---------------------------------------------------------------- queries --

def test_version_map_excludes_versionless_and_local(state):
    vmap = state.version_map()
    assert vmap == {("htop", APT): "2.0", ("git", APT): "2.43"}
    # LOCAL versions exist but must never contribute (matches source).
    assert ("moviebox", LOCAL) not in vmap


def test_counts_track_optimistic_set_only(state):
    assert state.counts_by_manager() == {"apt": 2, "flatpak": 1}
    state.register_pending("install", "lodash", NPM)
    assert state.counts_by_manager()["npm"] == 1            # optimistic bump
    state.revert_pending("install", "lodash", NPM)
    assert "npm" not in state.counts_by_manager()


# ---------------------------------------------------------------- purity ---

def test_module_imports_zero_textual():
    repo_root = str(Path(__file__).resolve().parent.parent)
    probe = (
        "import sys; import rmadd.controllers.optimistic_state;"
        "leaked = [k for k in sys.modules if k.split('.')[0] in ('textual', 'rich')];"
        "assert not leaked, f'UI deps leaked: {leaked}'; print('pure')"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=repo_root
    )
    assert result.returncode == 0, result.stderr
    assert "pure" in result.stdout
