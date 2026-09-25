from __future__ import annotations

from pathlib import Path

import pytest

from gitconvoy import ops_release as release_cmd
from gitconvoy import membership
from gitconvoy.errors import GitConvoyError
from gitconvoy.workspace import discover_repos

from conftest import git, init_repo


_POLICY = """\
role = "ops"
version = "python"
publish = "none"
pin = "git-tag"
"""


def _mark(path: Path, policy: str = _POLICY) -> None:
    (path / "gitconvoy.toml").write_text(policy)
    git(path, "add", "gitconvoy.toml")
    git(path, "commit", "-m", "ops policy")


def _ops_repo(workspace: Path, name: str, *, policy: str = _POLICY) -> Path:
    path = init_repo(workspace / "ops" / name)
    _mark(path, policy)
    membership.refresh_membership(workspace, discover_repos(workspace))
    return path


def _tag_current(path: Path, tag: str = "v1.0.0") -> None:
    git(path, "checkout", "main")
    git(path, "tag", tag)
    git(path, "checkout", "develop")


def test_read_ops_policy_requires_fields(workspace: Path) -> None:
    helper = init_repo(workspace / "ops" / "bom-helper")
    (helper / "gitconvoy.toml").write_text('role = "ops"\n')
    with pytest.raises(GitConvoyError, match="missing version"):
        membership.read_ops_policy(helper)
    (helper / "gitconvoy.toml").write_text(_POLICY)
    policy = membership.read_ops_policy(helper)
    assert policy["publish"] == "none"
    assert policy["pin"] == "git-tag"


def test_ops_release_no_sheet_bumps_and_opens_pr(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    git(helper, "add", "CHANGE.md")
    git(helper, "commit", "-m", "work on develop")

    data = release_cmd.release(workspace, ["bom-helper"], use_gh=False, push=False)
    assert data["ok"] is True
    row = data["repos"][0]
    assert row["status"] == "pr-needed"
    assert row["to"] == "1.0.1"
    assert row["bumped"] is True
    assert "version = \"1.0.1\"" in (helper / "pyproject.toml").read_text()
    assert git(helper, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "develop"


def test_ops_release_does_not_double_bump(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    _tag_current(helper)
    text = (helper / "pyproject.toml").read_text().replace("1.0.0", "1.2.0")
    (helper / "pyproject.toml").write_text(text)
    git(helper, "add", "pyproject.toml")
    git(helper, "commit", "-m", "already bumped")

    data = release_cmd.release(workspace, ["bom-helper"], use_gh=False, push=False)
    row = data["repos"][0]
    assert row["to"] == "1.2.0"
    assert row["bumped"] is False
    assert row["status"] == "pr-needed"


def test_ops_release_tags_after_merge(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    git(helper, "add", "CHANGE.md")
    git(helper, "commit", "-m", "work")
    first = release_cmd.release(workspace, ["bom-helper"], use_gh=False, push=False)
    assert first["repos"][0]["status"] == "pr-needed"

    git(helper, "checkout", "main")
    git(helper, "merge", "--no-edit", "develop")
    git(helper, "checkout", "develop")
    second = release_cmd.release(workspace, ["bom-helper"], use_gh=False, push=False)
    row = second["repos"][0]
    assert row["status"] == "tagged"
    assert row["tag"] == "v1.0.1"
    assert "v1.0.1" in git(helper, "tag", "-l", "v1.0.1").stdout


def test_ops_release_ignores_dirty_neighbor(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    launcher = _ops_repo(workspace, "launcher")
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    git(helper, "add", "CHANGE.md")
    git(helper, "commit", "-m", "work")
    (launcher / "DIRTY.md").write_text("leave me\n")

    data = release_cmd.release(workspace, ["bom-helper"], use_gh=False, push=False)
    assert data["ok"] is True
    assert data["repos"][0]["id"] == "bom-helper"
    assert (launcher / "DIRTY.md").read_text() == "leave me\n"


def test_ops_release_refuses_dirty_target(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    (helper / "DIRTY.md").write_text("nope\n")
    data = release_cmd.release(workspace, ["bom-helper"], use_gh=False, push=False)
    assert data["ok"] is False
    assert data["repos"][0]["status"] == "failed"
    assert "dirty" in data["repos"][0]["error"]


def test_ops_release_refuses_missing_policy(workspace: Path) -> None:
    helper = init_repo(workspace / "ops" / "bom-helper")
    (helper / "gitconvoy.toml").write_text('role = "ops"\n')
    git(helper, "add", "gitconvoy.toml")
    git(helper, "commit", "-m", "role only")
    membership.refresh_membership(workspace, discover_repos(workspace))
    data = release_cmd.release(workspace, ["bom-helper"], use_gh=False, push=False)
    assert data["ok"] is False
    assert "missing" in data["repos"][0]["error"]


def test_ops_release_pin_tag_updates_helper(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    git(helper, "add", "CHANGE.md")
    git(helper, "commit", "-m", "work")
    release_cmd.release(workspace, ["bom-helper"], use_gh=False, push=False)
    git(helper, "checkout", "main")
    git(helper, "merge", "--no-edit", "develop")
    git(helper, "checkout", "develop")

    bom = init_repo(workspace / "ops" / "example-bom", develop=False)
    (bom / "gitconvoy.toml").write_text('role = "bom"\n')
    (bom / "deploy_targets.yml").write_text(
        "helper:\n  repository: renglo/bom-helper\n  ref: oldsha\n"
    )
    git(bom, "add", "-A")
    git(bom, "commit", "-m", "bom helper pin")
    membership.refresh_membership(workspace, discover_repos(workspace))

    data = release_cmd.release(
        workspace,
        ["bom-helper"],
        pin="tag",
        use_gh=False,
        push=False,
    )
    assert data["repos"][0]["status"] == "tagged"
    pin = data["repos"][0]["pin"]
    assert pin["status"] == "updated"
    assert pin["kind"] == "tag"
    assert pin["ref"] == "v1.0.1"
    text = (bom / "deploy_targets.yml").read_text()
    assert "ref: v1.0.1" in text
    assert "oldsha" not in text


def test_ops_release_pin_skips_non_helper(workspace: Path) -> None:
    launcher = _ops_repo(workspace, "launcher")
    bom = init_repo(workspace / "ops" / "example-bom", develop=False)
    (bom / "gitconvoy.toml").write_text('role = "bom"\n')
    (bom / "deploy_targets.yml").write_text(
        "helper:\n  repository: renglo/bom-helper\n  ref: oldsha\n"
    )
    git(bom, "add", "-A")
    git(bom, "commit", "-m", "bom")
    membership.refresh_membership(workspace, discover_repos(workspace))

    data = release_cmd.release(
        workspace, ["launcher"], pin="tag", use_gh=False, push=False
    )
    assert data["repos"][0]["pin"]["status"] == "skipped"
    assert (bom / "deploy_targets.yml").read_text().count("oldsha") == 1
    assert launcher  # repo exists


def test_ops_release_pin_sha_fallback_before_merge(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    git(helper, "add", "CHANGE.md")
    git(helper, "commit", "-m", "work")
    bom = init_repo(workspace / "ops" / "example-bom", develop=False)
    (bom / "gitconvoy.toml").write_text('role = "bom"\n')
    (bom / "deploy_targets.yml").write_text(
        "helper:\n  repository: renglo/bom-helper\n  ref: oldsha\n"
    )
    git(bom, "add", "-A")
    git(bom, "commit", "-m", "bom")
    membership.refresh_membership(workspace, discover_repos(workspace))

    data = release_cmd.release(
        workspace, ["bom-helper"], pin="tag", use_gh=False, push=False
    )
    assert data["repos"][0]["status"] == "pr-needed"
    pin = data["repos"][0]["pin"]
    assert pin["kind"] == "sha"
    sha = git(helper, "rev-parse", "develop").stdout.strip()
    assert pin["ref"] == sha
