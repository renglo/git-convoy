from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gitconvoy import ops as ops_cmd
from gitconvoy import membership
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, load, save
from gitconvoy.workspace import discover_repos

from conftest import git, init_repo


def _ops_workspace(workspace: Path) -> Path:
    launcher = init_repo(workspace / "ops" / "launcher")
    helper = init_repo(workspace / "ops" / "bom-helper")
    (launcher / "gitconvoy.toml").write_text('role = "ops"\n')
    (helper / "gitconvoy.toml").write_text('role = "ops"\n')
    git(launcher, "add", "gitconvoy.toml")
    git(launcher, "commit", "-m", "marker")
    git(helper, "add", "gitconvoy.toml")
    git(helper, "commit", "-m", "marker")
    membership.refresh_membership(workspace, discover_repos(workspace))
    return workspace


def test_ops_start_and_adopt_only_touches_ops_repos(workspace: Path) -> None:
    _ops_workspace(workspace)
    # dirty product repo must be ignored
    (workspace / "dev" / "renglo-lib" / "README.md").write_text("product dirty\n")
    launcher = workspace / "ops" / "launcher"
    (launcher / "TOOL.md").write_text("ops change\n")

    state = State()
    data = ops_cmd.start(workspace, state, "codeartifact")
    assert data["ops"] == "codeartifact"
    assert data["branch"] == "ops/codeartifact"
    assert data["repo_count"] == 0

    data = ops_cmd.adopt(workspace, state)
    assert {row["id"] for row in data["adopted"]} == {"launcher"}
    assert "renglo-lib" not in {row["id"] for row in data["adopted"]}
    assert "renglo-lib" not in {row["id"] for row in data["skipped"]}

    state = load(workspace)
    sheet = state.require_ops()
    assert sheet.repo_ids() == ["launcher"]
    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "ops/codeartifact"


def test_ops_parallel_to_feature(workspace: Path) -> None:
    _ops_workspace(workspace)
    state = State(current_feature="demo")
    save(workspace, state)
    state = load(workspace)
    data = ops_cmd.start(workspace, state, "tooling")
    assert data["ok"]
    state = load(workspace)
    assert state.current_feature == "demo"
    assert state.current_ops == "tooling"


def test_ops_adopt_repos_includes_clean_aux(workspace: Path) -> None:
    _ops_workspace(workspace)
    state = State()
    ops_cmd.start(workspace, state, "npm-always-auth")
    helper = workspace / "ops" / "bom-helper"
    launcher = workspace / "ops" / "launcher"

    data = ops_cmd.adopt(workspace, state, repo_ids=["bom-helper"])
    assert {row["id"] for row in data["adopted"]} == {"bom-helper"}
    assert "launcher" not in {row["id"] for row in data["adopted"]}
    state = load(workspace)
    assert state.require_ops().repo_ids() == ["bom-helper"]
    assert git(helper, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == (
        "ops/npm-always-auth"
    )
    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != (
        "ops/npm-always-auth"
    )


def test_ops_adopt_repos_rejects_product(workspace: Path) -> None:
    _ops_workspace(workspace)
    state = State()
    ops_cmd.start(workspace, state, "tools")
    with pytest.raises(GitConvoyError, match="product repo"):
        ops_cmd.adopt(workspace, state, repo_ids=["renglo-lib"])


def test_ops_adopt_fishes_dirty_work_from_develop(workspace: Path) -> None:
    _ops_workspace(workspace)
    svc = init_repo(workspace / "ops" / "publisher")
    (svc / "gitconvoy.toml").write_text('role = "ops"\n')
    git(svc, "add", "gitconvoy.toml")
    git(svc, "commit", "-m", "marker")
    membership.refresh_membership(workspace, discover_repos(workspace))

    git(svc, "checkout", "develop")
    (svc / "SERVICE.md").write_text("develop-side change\n")

    state = State()
    ops_cmd.start(workspace, state, "initial-ops")
    data = ops_cmd.adopt(workspace, state)
    adopted = {row["id"]: row for row in data["adopted"]}
    assert "publisher" in adopted
    assert adopted["publisher"].get("fish_from") == "develop"
    assert git(svc, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "ops/initial-ops"
    assert (svc / "SERVICE.md").read_text() == "develop-side change\n"


def test_ops_start_creates_missing_develop(workspace: Path) -> None:
    helper = init_repo(workspace / "ops" / "bom-helper", develop=False)
    (helper / "gitconvoy.toml").write_text('role = "ops"\n')
    git(helper, "add", "gitconvoy.toml")
    git(helper, "commit", "-m", "marker")
    membership.refresh_membership(workspace, discover_repos(workspace))

    assert git(helper, "branch", "--list", "develop").stdout.strip() == ""
    ops_cmd.start(workspace, State(), "tools")
    assert git(helper, "rev-parse", "--abbrev-ref", "develop").stdout.strip() == "develop"


def _prep_ops_prs(workspace: Path, monkeypatch) -> tuple[Path, object]:
    _ops_workspace(workspace)
    launcher = workspace / "ops" / "launcher"
    (launcher / "TOOL.md").write_text("ops change\n")
    state = State()
    ops_cmd.start(workspace, state, "codeartifact")
    ops_cmd.adopt(workspace, state)
    state = load(workspace)
    from gitconvoy import commit as commit_cmd

    commit_cmd.commit(
        workspace,
        state,
        header="fix: ops",
        header_only=True,
        kind="ops",
    )
    monkeypatch.setattr(
        "gitconvoy.ops.gitutil.github_slug", lambda _repo: "renglo/launcher"
    )
    monkeypatch.setattr("gitconvoy.ops.gitutil.push", lambda *args, **kwargs: None)
    monkeypatch.setattr("gitconvoy.gitutil.fetch", lambda _repo: None)
    return launcher, load(workspace)


def test_ops_prs_compare_targets_develop(workspace: Path, monkeypatch) -> None:
    launcher, state = _prep_ops_prs(workspace, monkeypatch)
    # fetch is mocked; seed origin/develop so merge step can succeed
    tip = git(launcher, "rev-parse", "develop").stdout.strip()
    git(launcher, "update-ref", "refs/remotes/origin/develop", tip)
    data = ops_cmd.prs(workspace, state, use_gh=False)
    assert data["base"] == "develop"
    assert data["repos"][0]["compare"].endswith("compare/develop...ops/codeartifact")


def test_ops_prs_merges_origin_develop(workspace: Path, monkeypatch) -> None:
    launcher, state = _prep_ops_prs(workspace, monkeypatch)
    git(launcher, "checkout", "develop")
    (launcher / "REMOTE.md").write_text("from origin\n")
    git(launcher, "add", "REMOTE.md")
    git(launcher, "commit", "-m", "on origin develop")
    remote_tip = git(launcher, "rev-parse", "HEAD").stdout.strip()
    git(launcher, "update-ref", "refs/remotes/origin/develop", remote_tip)
    git(launcher, "checkout", "ops/codeartifact")
    git(launcher, "reset", "--hard", "HEAD~0")  # stay on ops with only ops commit

    data = ops_cmd.prs(workspace, state, use_gh=False)
    assert data["base"] == "develop"
    assert (launcher / "REMOTE.md").read_text() == "from origin\n"


def test_ops_close_checks_out_develop(workspace: Path) -> None:
    _ops_workspace(workspace)
    launcher = workspace / "ops" / "launcher"
    (launcher / "TOOL.md").write_text("ship it\n")
    state = State()
    ops_cmd.start(workspace, state, "ship")
    ops_cmd.adopt(workspace, state)
    state = load(workspace)
    from gitconvoy import commit as commit_cmd

    commit_cmd.commit(
        workspace,
        state,
        header="fix: ship",
        header_only=True,
        kind="ops",
    )
    # Simulate PR merge into develop without going through GitHub.
    git(launcher, "checkout", "develop")
    git(launcher, "merge", "--no-edit", "ops/ship")
    git(launcher, "checkout", "ops/ship")
    state = load(workspace)
    data = ops_cmd.close(workspace, state, yes=True, keep_branch=True)
    assert data["closed"] is True
    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "develop"
    tip = git(launcher, "rev-parse", "ops/ship").stdout.strip()
    merge_base = git(launcher, "merge-base", tip, "develop").stdout.strip()
    assert tip == merge_base


def test_ops_close_ff_develop_from_origin(workspace: Path) -> None:
    _ops_workspace(workspace)
    launcher = workspace / "ops" / "launcher"
    bare = workspace / "launcher.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    git(launcher, "remote", "add", "origin", str(bare))
    git(launcher, "push", "-u", "origin", "develop")
    git(launcher, "push", "-u", "origin", "main")

    (launcher / "TOOL.md").write_text("ship it\n")
    state = State()
    ops_cmd.start(workspace, state, "ship")
    ops_cmd.adopt(workspace, state)
    state = load(workspace)
    from gitconvoy import commit as commit_cmd

    commit_cmd.commit(
        workspace,
        state,
        header="fix: ship",
        header_only=True,
        kind="ops",
    )
    git(launcher, "checkout", "develop")
    git(launcher, "merge", "--no-edit", "ops/ship")
    merged_tip = git(launcher, "rev-parse", "HEAD").stdout.strip()
    git(launcher, "push", "origin", "develop")
    stale_tip = git(launcher, "rev-parse", "develop~1").stdout.strip()
    git(launcher, "checkout", "ops/ship")
    git(launcher, "branch", "-f", "develop", stale_tip)

    state = load(workspace)
    data = ops_cmd.close(workspace, state, yes=True)
    assert data["closed"] is True
    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "develop"
    assert git(launcher, "rev-parse", "develop").stdout.strip() == merged_tip
    assert git(launcher, "rev-parse", "origin/develop").stdout.strip() == merged_tip


def test_ops_abandon_keeps_uncommitted_files(workspace: Path) -> None:
    _ops_workspace(workspace)
    launcher = workspace / "ops" / "launcher"
    (launcher / "TOOL.md").write_text("do not delete me\n")
    state = State()
    ops_cmd.start(workspace, state, "peer-release")
    ops_cmd.adopt(workspace, state)
    data = ops_cmd.abandon(workspace, load(workspace), yes=True)
    assert data["abandoned"] is True
    assert (launcher / "TOOL.md").read_text() == "do not delete me\n"
    from gitconvoy import gitutil

    assert gitutil.is_dirty(launcher)
    assert gitutil.current_branch(launcher) == "ops/peer-release"
    assert gitutil.has_local_branch(launcher, "ops/peer-release")
    row = next(item for item in data["repos"] if item["id"] == "launcher")
    assert row["dirty"] is True
    assert row["kept_local_branch"] is True
    state = load(workspace)
    assert state.current_ops is None
    assert "peer-release" not in state.ops_sheets


def test_ops_abandon_keeps_merged_local_branch(workspace: Path) -> None:
    _ops_workspace(workspace)
    launcher = workspace / "ops" / "launcher"
    (launcher / "TOOL.md").write_text("ship it\n")
    state = State()
    ops_cmd.start(workspace, state, "ship")
    ops_cmd.adopt(workspace, state)
    from gitconvoy import commit as commit_cmd

    commit_cmd.commit(
        workspace,
        load(workspace),
        header="fix: ship",
        header_only=True,
        kind="ops",
    )
    git(launcher, "checkout", "develop")
    git(launcher, "merge", "--no-edit", "ops/ship")
    git(launcher, "checkout", "ops/ship")
    data = ops_cmd.abandon(workspace, load(workspace), yes=True)
    assert data["abandoned"] is True
    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "ops/ship"
    assert "ops/ship" in git(launcher, "branch", "--list", "ops/ship").stdout
    assert git(launcher, "show", "develop:TOOL.md").stdout == "ship it\n"
    row = next(item for item in data["repos"] if item["id"] == "launcher")
    assert row["kept_local_branch"] is True
    assert row["dirty"] is False
