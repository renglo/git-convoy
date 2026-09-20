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


def test_aux_start_creates_missing_develop(workspace: Path) -> None:
    helper = init_repo(workspace / "ops" / "bom-helper", develop=False)
    (helper / "gitconvoy.toml").write_text('role = "aux"\n')
    git(helper, "add", "gitconvoy.toml")
    git(helper, "commit", "-m", "marker")
    membership.refresh_membership(workspace, discover_repos(workspace))

    assert git(helper, "branch", "--list", "develop").stdout.strip() == ""
    aux_cmd.start(workspace, State(), "tools")
    assert git(helper, "rev-parse", "--abbrev-ref", "develop").stdout.strip() == "develop"


def _diverge_main(repo: Path) -> tuple[str, str]:
    """Local main and origin/main each get a unique commit from the same parent."""
    git(repo, "checkout", "main")
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "LOCAL.md").write_text("laptop\n")
    git(repo, "add", "LOCAL.md")
    git(repo, "commit", "-m", "local main work")
    local = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "reset", "--hard", base)
    (repo / "REMOTE.md").write_text("github\n")
    git(repo, "add", "REMOTE.md")
    git(repo, "commit", "-m", "origin main work")
    remote = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "update-ref", "refs/remotes/origin/main", remote)
    git(repo, "reset", "--hard", local)
    return local, remote


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


def test_aux_prs_compare_targets_main(workspace: Path, monkeypatch) -> None:
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
    data = aux_cmd.prs(workspace, load(workspace), use_gh=False)
    assert data["base"] == "main"
    assert data["repos"][0]["compare"].endswith("compare/main...aux/codeartifact")


def test_aux_prs_absorbs_diverged_local_main(workspace: Path, monkeypatch) -> None:
    launcher, state = _prep_aux_prs(workspace, monkeypatch)
    _diverge_main(launcher)

    data = aux_cmd.prs(workspace, state, use_gh=False)
    synced = {row["id"]: row.get("main") for row in data["ensure_develop"]}
    assert synced["launcher"]["action"] == "absorbed"
    assert any(
        "local main work" in (item.get("subject") or "")
        for item in synced["launcher"]["moved"]
    )
    assert "Moved local-main-only commits" in data["note"]

    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == (
        "aux/codeartifact"
    )
    main_tip = git(launcher, "rev-parse", "main").stdout.strip()
    origin_tip = git(launcher, "rev-parse", "origin/main").stdout.strip()
    assert main_tip == origin_tip
    assert git(launcher, "show", "main:REMOTE.md").stdout == "github\n"
    assert git(launcher, "show", "aux/codeartifact:LOCAL.md").stdout == "laptop\n"
    assert (launcher / "TOOL.md").read_text() == "aux change\n"


def test_aux_prs_absorbs_ahead_only_local_main(workspace: Path, monkeypatch) -> None:
    launcher, state = _prep_aux_prs(workspace, monkeypatch)
    git(launcher, "checkout", "main")
    origin = git(launcher, "rev-parse", "HEAD").stdout.strip()
    git(launcher, "update-ref", "refs/remotes/origin/main", origin)
    (launcher / "LOCAL.md").write_text("laptop\n")
    git(launcher, "add", "LOCAL.md")
    git(launcher, "commit", "-m", "local main work")

    data = aux_cmd.prs(workspace, state, use_gh=False)
    synced = {row["id"]: row.get("main") for row in data["ensure_develop"]}
    assert synced["launcher"]["action"] == "absorbed"
    assert git(launcher, "rev-parse", "main").stdout.strip() == origin
    git(launcher, "checkout", "aux/codeartifact")
    assert (launcher / "LOCAL.md").read_text() == "laptop\n"


def test_aux_prs_absorb_conflict_leaves_main(workspace: Path, monkeypatch) -> None:
    launcher, state = _prep_aux_prs(workspace, monkeypatch)
    git(launcher, "checkout", "aux/codeartifact")
    (launcher / "LOCAL.md").write_text("aux side\n")
    git(launcher, "add", "LOCAL.md")
    git(launcher, "commit", "-m", "aux already has LOCAL.md")
    _diverge_main(launcher)
    local_main = git(launcher, "rev-parse", "main").stdout.strip()

    with pytest.raises(GitConvoyError, match="conflict moving local-main"):
        aux_cmd.prs(workspace, state, use_gh=False)

    assert git(launcher, "rev-parse", "main").stdout.strip() == local_main
    from gitconvoy import gitutil

    assert gitutil.cherry_pick_in_progress(launcher)


def test_aux_close_merges_main_into_develop(workspace: Path) -> None:
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
    # Simulate PR merge into main without going through GitHub.
    git(launcher, "checkout", "main")
    git(launcher, "merge", "--no-edit", "aux/ship")
    git(launcher, "checkout", "aux/ship")
    state = load(workspace)
    data = aux_cmd.close(workspace, state, yes=True, keep_branch=True)
    assert data["closed"] is True
    assert data["repos"][0]["mergeback"]["status"] in {"merged", "already"}
    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "develop"
    # Aux tip is now an ancestor of develop.
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
    git(launcher, "checkout", "main")
    git(launcher, "merge", "--no-edit", "aux/ship")
    git(launcher, "checkout", "aux/ship")
    data = aux_cmd.abandon(workspace, load(workspace), yes=True)
    assert data["abandoned"] is True
    assert git(launcher, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "aux/ship"
    assert "aux/ship" in git(launcher, "branch", "--list", "aux/ship").stdout
    assert git(launcher, "show", "main:TOOL.md").stdout == "ship it\n"
    row = next(item for item in data["repos"] if item["id"] == "launcher")
    assert row["kept_local_branch"] is True
    assert row["dirty"] is False
