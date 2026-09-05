from __future__ import annotations

from pathlib import Path

from gitconvoy import aux as aux_cmd
from gitconvoy import membership
from gitconvoy.state import State, load, save
from gitconvoy.workspace import discover_repos

from conftest import git, init_repo


def _aux_workspace(workspace: Path) -> Path:
    launcher = init_repo(workspace / "ops" / "launcher")
    helper = init_repo(workspace / "ops" / "bom-helper")
    (launcher / "gitconvoy.toml").write_text('role = "aux"\n')
    (helper / "gitconvoy.toml").write_text('role = "aux"\n')
    git(launcher, "add", "gitconvoy.toml")
    git(launcher, "commit", "-m", "marker")
    git(helper, "add", "gitconvoy.toml")
    git(helper, "commit", "-m", "marker")
    membership.refresh_membership(workspace, discover_repos(workspace))
    return workspace


def test_aux_start_and_adopt_only_touches_aux_repos(workspace: Path) -> None:
    _aux_workspace(workspace)
    # dirty product repo must be ignored
    (workspace / "dev" / "renglo-lib" / "README.md").write_text("product dirty\n")
    launcher = workspace / "ops" / "launcher"
    (launcher / "TOOL.md").write_text("aux change\n")

    state = State()
    data = aux_cmd.start(workspace, state, "codeartifact")
    assert data["aux"] == "codeartifact"
    assert data["branch"] == "aux/codeartifact"
    assert data["repo_count"] == 0

    data = aux_cmd.adopt(workspace, state)
    assert {row["id"] for row in data["adopted"]} == {"launcher"}
    assert "renglo-lib" not in {row["id"] for row in data["adopted"]}
    assert "renglo-lib" not in {row["id"] for row in data["skipped"]}

    state = load(workspace) if (workspace / ".gitconvoy" / "state.json").exists() else state
    # adopt saves state
    state = load(workspace)
    sheet = state.require_aux()
    assert sheet.repo_ids() == ["launcher"]
    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "aux/codeartifact"


def test_aux_parallel_to_feature(workspace: Path) -> None:
    _aux_workspace(workspace)
    state = State(current_feature="demo")
    save(workspace, state)
    state = load(workspace)
    data = aux_cmd.start(workspace, state, "tooling")
    assert data["ok"]
    state = load(workspace)
    assert state.current_feature == "demo"
    assert state.current_aux == "tooling"


def test_aux_adopt_fishes_dirty_work_from_main(workspace: Path) -> None:
    """Aux repos often land work on main even when develop exists."""
    _aux_workspace(workspace)
    svc = init_repo(workspace / "ops" / "extensions-service")
    (svc / "gitconvoy.toml").write_text('role = "aux"\n')
    git(svc, "add", "gitconvoy.toml")
    git(svc, "commit", "-m", "marker")
    membership.refresh_membership(workspace, discover_repos(workspace))

    git(svc, "checkout", "main")
    (svc / "SERVICE.md").write_text("main-side change\n")

    state = State()
    aux_cmd.start(workspace, state, "initial-aux")
    data = aux_cmd.adopt(workspace, state)
    adopted = {row["id"]: row for row in data["adopted"]}
    assert "extensions-service" in adopted
    assert adopted["extensions-service"].get("fish_from") == "main"
    assert git(svc, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "aux/initial-aux"
    assert (svc / "SERVICE.md").read_text() == "main-side change\n"
