from __future__ import annotations

import subprocess
from pathlib import Path

from gitconvoy import gitutil
from gitconvoy import ops as ops_cmd
from gitconvoy.state import State
from conftest import git


def _bare_remote(path: Path) -> Path:
    bare = path.parent / f"{path.name}.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    git(path, "remote", "add", "origin", str(bare))
    return bare


def test_ensure_develop_pushes_main_then_creates_develop(tmp_path: Path) -> None:
    repo = tmp_path / "renglo-ops"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "Initial commit")
    _bare_remote(repo)

    ensured = gitutil.ensure_develop(repo, push=True)
    assert ensured["status"] == "created"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "develop"
    assert git(repo, "ls-remote", "--heads", "origin", "main").stdout.strip()
    assert git(repo, "ls-remote", "--heads", "origin", "develop").stdout.strip()


def test_ensure_develop_empty_commit_leaves_dirty_tree(tmp_path: Path) -> None:
    repo = tmp_path / "tool"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("new repo\n")
    _bare_remote(repo)

    ensured = gitutil.ensure_develop(repo, push=True)
    assert ensured["status"] == "created"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "develop"
    assert gitutil.is_dirty(repo)
    assert "README.md" not in git(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout
    assert git(repo, "ls-remote", "--heads", "origin", "main").stdout.strip()
    assert git(repo, "ls-remote", "--heads", "origin", "develop").stdout.strip()


def test_ops_start_then_adopt_on_unborn_main(workspace: Path) -> None:
    from gitconvoy import membership
    from gitconvoy.workspace import discover_repos

    helper = workspace / "ops" / "new-tool"
    subprocess.run(["git", "init", "-b", "main", str(helper)], check=True, capture_output=True)
    git(helper, "config", "user.email", "test@example.com")
    git(helper, "config", "user.name", "Test")
    (helper / "gitconvoy.toml").write_text('role = "ops"\n')
    (helper / "tool.py").write_text("print('ok')\n")
    _bare_remote(helper)
    membership.refresh_membership(workspace, discover_repos(workspace))

    started = ops_cmd.start(workspace, State(), "implement")
    skipped = {row["id"]: row for row in started["workspace"]}
    assert skipped["new-tool"]["skipped"] == "dirty"
    assert git(helper, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "develop"
    assert gitutil.is_dirty(helper)
    assert started["repo_count"] == 0

    from gitconvoy.state import load

    adopted = ops_cmd.adopt(workspace, load(workspace))
    ids = {row["id"] for row in adopted["adopted"]}
    assert "new-tool" in ids
    assert git(helper, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "ops/implement"
    assert gitutil.is_dirty(helper)
    assert "tool.py" not in git(helper, "ls-tree", "-r", "--name-only", "HEAD").stdout
