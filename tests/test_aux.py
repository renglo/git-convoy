from __future__ import annotations

from pathlib import Path

import pytest

from gitconvoy import aux as aux_cmd
from gitconvoy import membership
from gitconvoy.errors import GitConvoyError
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


def test_aux_adopt_repos_includes_clean_aux(workspace: Path) -> None:
    _aux_workspace(workspace)
    state = State()
    aux_cmd.start(workspace, state, "npm-always-auth")
    helper = workspace / "ops" / "bom-helper"
    launcher = workspace / "ops" / "launcher"

    data = aux_cmd.adopt(workspace, state, repo_ids=["bom-helper"])
    assert {row["id"] for row in data["adopted"]} == {"bom-helper"}
    assert "launcher" not in {row["id"] for row in data["adopted"]}
    state = load(workspace)
    assert state.require_aux().repo_ids() == ["bom-helper"]
    assert git(helper, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == (
        "aux/npm-always-auth"
    )
    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != (
        "aux/npm-always-auth"
    )


def test_aux_adopt_repos_rejects_product(workspace: Path) -> None:
    _aux_workspace(workspace)
    state = State()
    aux_cmd.start(workspace, state, "tools")
    with pytest.raises(GitConvoyError, match="product repo"):
        aux_cmd.adopt(workspace, state, repo_ids=["renglo-lib"])


def test_aux_adopt_fishes_dirty_work_from_develop(workspace: Path) -> None:
    _aux_workspace(workspace)
    svc = init_repo(workspace / "ops" / "publisher")
    (svc / "gitconvoy.toml").write_text('role = "aux"\n')
    git(svc, "add", "gitconvoy.toml")
    git(svc, "commit", "-m", "marker")
    membership.refresh_membership(workspace, discover_repos(workspace))

    git(svc, "checkout", "develop")
    (svc / "SERVICE.md").write_text("develop-side change\n")

    state = State()
    aux_cmd.start(workspace, state, "initial-aux")
    data = aux_cmd.adopt(workspace, state)
    adopted = {row["id"]: row for row in data["adopted"]}
    assert "publisher" in adopted
    assert adopted["publisher"].get("fish_from") == "develop"
    assert git(svc, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "aux/initial-aux"
    assert (svc / "SERVICE.md").read_text() == "develop-side change\n"


def test_aux_start_creates_missing_develop(workspace: Path) -> None:
    helper = init_repo(workspace / "ops" / "bom-helper", develop=False)
    (helper / "gitconvoy.toml").write_text('role = "aux"\n')
    git(helper, "add", "gitconvoy.toml")
    git(helper, "commit", "-m", "marker")
    membership.refresh_membership(workspace, discover_repos(workspace))

    assert git(helper, "branch", "--list", "develop").stdout.strip() == ""
    aux_cmd.start(workspace, State(), "tools")
    assert git(helper, "rev-parse", "--abbrev-ref", "develop").stdout.strip() == "develop"


def _prep_aux_prs(workspace: Path, monkeypatch) -> tuple[Path, object]:
    _aux_workspace(workspace)
    launcher = workspace / "ops" / "launcher"
    (launcher / "TOOL.md").write_text("aux change\n")
    state = State()
    aux_cmd.start(workspace, state, "codeartifact")
    aux_cmd.adopt(workspace, state)
    state = load(workspace)
    from gitconvoy import commit as commit_cmd

    commit_cmd.commit(
        workspace,
        state,
        header="fix: aux",
        header_only=True,
        kind="aux",
    )
    monkeypatch.setattr(
        "gitconvoy.aux.gitutil.github_slug", lambda _repo: "renglo/launcher"
    )
    monkeypatch.setattr("gitconvoy.aux.gitutil.push", lambda *args, **kwargs: None)
    monkeypatch.setattr("gitconvoy.gitutil.fetch", lambda _repo: None)
    return launcher, load(workspace)


def test_aux_prs_compare_targets_develop(workspace: Path, monkeypatch) -> None:
    launcher, state = _prep_aux_prs(workspace, monkeypatch)
    # fetch is mocked; seed origin/develop so merge step can succeed
    tip = git(launcher, "rev-parse", "develop").stdout.strip()
    git(launcher, "update-ref", "refs/remotes/origin/develop", tip)
    data = aux_cmd.prs(workspace, state, use_gh=False)
    assert data["base"] == "develop"
    assert data["repos"][0]["compare"].endswith("compare/develop...aux/codeartifact")


def test_aux_prs_merges_origin_develop(workspace: Path, monkeypatch) -> None:
    launcher, state = _prep_aux_prs(workspace, monkeypatch)
    git(launcher, "checkout", "develop")
    (launcher / "REMOTE.md").write_text("from origin\n")
    git(launcher, "add", "REMOTE.md")
    git(launcher, "commit", "-m", "on origin develop")
    remote_tip = git(launcher, "rev-parse", "HEAD").stdout.strip()
    git(launcher, "update-ref", "refs/remotes/origin/develop", remote_tip)
    git(launcher, "checkout", "aux/codeartifact")
    git(launcher, "reset", "--hard", "HEAD~0")  # stay on aux with only aux commit

    data = aux_cmd.prs(workspace, state, use_gh=False)
    assert data["base"] == "develop"
    assert (launcher / "REMOTE.md").read_text() == "from origin\n"


def test_aux_close_checks_out_develop(workspace: Path) -> None:
    _aux_workspace(workspace)
    launcher = workspace / "ops" / "launcher"
    (launcher / "TOOL.md").write_text("ship it\n")
    state = State()
    aux_cmd.start(workspace, state, "ship")
    aux_cmd.adopt(workspace, state)
    state = load(workspace)
    from gitconvoy import commit as commit_cmd

    commit_cmd.commit(
        workspace,
        state,
        header="fix: ship",
        header_only=True,
        kind="aux",
    )
    # Simulate PR merge into develop without going through GitHub.
    git(launcher, "checkout", "develop")
    git(launcher, "merge", "--no-edit", "aux/ship")
    git(launcher, "checkout", "aux/ship")
    state = load(workspace)
    data = aux_cmd.close(workspace, state, yes=True, keep_branch=True)
    assert data["closed"] is True
    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "develop"
    tip = git(launcher, "rev-parse", "aux/ship").stdout.strip()
    merge_base = git(launcher, "merge-base", tip, "develop").stdout.strip()
    assert tip == merge_base


def test_aux_abandon_keeps_uncommitted_files(workspace: Path) -> None:
    _aux_workspace(workspace)
    launcher = workspace / "ops" / "launcher"
    (launcher / "TOOL.md").write_text("do not delete me\n")
    state = State()
    aux_cmd.start(workspace, state, "peer-release")
    aux_cmd.adopt(workspace, state)
    data = aux_cmd.abandon(workspace, load(workspace), yes=True)
    assert data["abandoned"] is True
    assert (launcher / "TOOL.md").read_text() == "do not delete me\n"
    from gitconvoy import gitutil

    assert gitutil.is_dirty(launcher)
    assert gitutil.current_branch(launcher) == "aux/peer-release"
    assert gitutil.has_local_branch(launcher, "aux/peer-release")
    row = next(item for item in data["repos"] if item["id"] == "launcher")
    assert row["dirty"] is True
    assert row["kept_local_branch"] is True
    state = load(workspace)
    assert state.current_aux is None
    assert "peer-release" not in state.auxes


def test_aux_abandon_keeps_merged_local_branch(workspace: Path) -> None:
    _aux_workspace(workspace)
    launcher = workspace / "ops" / "launcher"
    (launcher / "TOOL.md").write_text("ship it\n")
    state = State()
    aux_cmd.start(workspace, state, "ship")
    aux_cmd.adopt(workspace, state)
    from gitconvoy import commit as commit_cmd

    commit_cmd.commit(
        workspace,
        load(workspace),
        header="fix: ship",
        header_only=True,
        kind="aux",
    )
    git(launcher, "checkout", "develop")
    git(launcher, "merge", "--no-edit", "aux/ship")
    git(launcher, "checkout", "aux/ship")
    data = aux_cmd.abandon(workspace, load(workspace), yes=True)
    assert data["abandoned"] is True
    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "aux/ship"
    assert "aux/ship" in git(launcher, "branch", "--list", "aux/ship").stdout
    assert git(launcher, "show", "develop:TOOL.md").stdout == "ship it\n"
    row = next(item for item in data["repos"] if item["id"] == "launcher")
    assert row["kept_local_branch"] is True
    assert row["dirty"] is False
