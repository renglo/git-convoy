from __future__ import annotations

from pathlib import Path

import pytest

from gitconvoy import commit as commit_cmd
from gitconvoy import ops as ops_cmd
from gitconvoy import ops_release as release_cmd
from gitconvoy import membership
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, load
from gitconvoy.workspace import discover_repos

from conftest import git, init_repo


_POLICY = """\
role = "ops"
version = "python"
publish = "none"
pin = "git-tag"
"""

_WHEEL = """\
role = "ops"
version = "python"
publish = "python-wheel"
pin = "registry"
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


def _publish(workspace: Path, *ids: str, **kwargs):
    kwargs.setdefault("push", False)
    return release_cmd.publish(workspace, list(ids), **kwargs)


def test_read_ops_policy_requires_fields(workspace: Path) -> None:
    helper = init_repo(workspace / "ops" / "bom-helper")
    (helper / "gitconvoy.toml").write_text('role = "ops"\n')
    with pytest.raises(GitConvoyError, match="missing version"):
        membership.read_ops_policy(helper)
    (helper / "gitconvoy.toml").write_text(_POLICY)
    policy = membership.read_ops_policy(helper)
    assert policy["publish"] == "none"
    assert policy["pin"] == "git-tag"


def test_ops_release_and_propose_are_gone() -> None:
    with pytest.raises(GitConvoyError, match="ops publish"):
        release_cmd.release()
    with pytest.raises(GitConvoyError, match="ops publish"):
        release_cmd.propose()
    with pytest.raises(GitConvoyError, match="ops publish"):
        ops_cmd.promote()


def test_ops_publish_merges_develop_to_main_and_tags(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    git(helper, "add", "CHANGE.md")
    git(helper, "commit", "-m", "work on develop")

    data = _publish(workspace, "bom-helper")
    assert data["ok"] is True
    row = data["repos"][0]
    assert row["status"] == "tagged"
    assert row["to"] == "1.0.1"
    assert row["bumped"] is True
    assert row["tag"] == "v1.0.1"
    assert "version = \"1.0.1\"" in (helper / "pyproject.toml").read_text()
    assert "v1.0.1" in git(helper, "tag", "-l", "v1.0.1").stdout
    git(helper, "checkout", "main")
    assert (helper / "CHANGE.md").read_text() == "work\n"
    git(helper, "checkout", "develop")


def test_ops_publish_does_not_double_bump(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    _tag_current(helper)
    text = (helper / "pyproject.toml").read_text().replace("1.0.0", "1.2.0")
    (helper / "pyproject.toml").write_text(text)
    git(helper, "add", "pyproject.toml")
    git(helper, "commit", "-m", "already bumped")

    data = _publish(workspace, "bom-helper")
    row = data["repos"][0]
    assert row["to"] == "1.2.0"
    assert row["bumped"] is False
    assert row["status"] == "tagged"
    assert row["tag"] == "v1.2.0"


def test_ops_publish_already_when_rerun_after_tag(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    git(helper, "add", "CHANGE.md")
    git(helper, "commit", "-m", "work")
    first = _publish(workspace, "bom-helper")
    assert first["repos"][0]["status"] == "tagged"

    second = _publish(workspace, "bom-helper")
    row = second["repos"][0]
    assert second["ok"] is True
    assert row["status"] == "already"
    assert row["tag"] == "v1.0.1"
    assert row["to"] == "1.0.1"


def test_ops_publish_bumps_when_same_version_has_unmerged_changes(
    workspace: Path,
) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    git(helper, "checkout", "main")
    git(helper, "tag", "v1.0.0")
    git(helper, "checkout", "develop")
    text = (helper / "pyproject.toml").read_text().replace(
        "bom-helper", "renglo-bom-helper"
    )
    (helper / "pyproject.toml").write_text(text)
    git(helper, "add", "pyproject.toml")
    git(helper, "commit", "-m", "Rename package")

    data = _publish(workspace, "bom-helper")
    row = data["repos"][0]
    assert data["ok"] is True
    assert row["status"] == "tagged"
    assert row["to"] == "1.0.1"
    assert row["bumped"] is True


def test_ops_publish_tags_when_origin_main_has_merge_commit(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    bare = workspace / "bom-helper.git"
    git(workspace, "init", "--bare", str(bare))
    git(helper, "remote", "add", "origin", str(bare))
    git(helper, "push", "-u", "origin", "develop")
    git(helper, "push", "origin", "main")
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    git(helper, "add", "CHANGE.md")
    git(helper, "commit", "-m", "work")
    git(helper, "push", "origin", "develop")

    data = _publish(workspace, "bom-helper")
    row = data["repos"][0]
    assert row["status"] == "tagged"
    assert row["tag"] == "v1.0.1"


def test_ops_publish_ignores_sibling_with_invalid_role(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    publisher = init_repo(workspace / "ops" / "publisher")
    (publisher / "gitconvoy.toml").write_text('role = "aux"\n')
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    git(helper, "add", "CHANGE.md")
    git(helper, "commit", "-m", "work")

    data = _publish(workspace, "bom-helper")
    assert data["ok"] is True
    assert data["repos"][0]["id"] == "bom-helper"
    assert data["repos"][0]["status"] == "tagged"


def test_ops_publish_ignores_dirty_neighbor(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    launcher = _ops_repo(workspace, "launcher")
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    git(helper, "add", "CHANGE.md")
    git(helper, "commit", "-m", "work")
    (launcher / "DIRTY.md").write_text("leave me\n")

    data = _publish(workspace, "bom-helper")
    assert data["ok"] is True
    assert data["repos"][0]["id"] == "bom-helper"
    assert (launcher / "DIRTY.md").read_text() == "leave me\n"


def test_ops_publish_refuses_dirty_target(workspace: Path) -> None:
    helper = _ops_repo(workspace, "bom-helper")
    (helper / "DIRTY.md").write_text("nope\n")
    data = _publish(workspace, "bom-helper")
    assert data["ok"] is False
    assert data["repos"][0]["status"] == "failed"
    assert "dirty" in data["repos"][0]["error"]


def test_ops_publish_refuses_missing_policy(workspace: Path) -> None:
    helper = init_repo(workspace / "ops" / "bom-helper")
    (helper / "gitconvoy.toml").write_text('role = "ops"\n')
    git(helper, "add", "gitconvoy.toml")
    git(helper, "commit", "-m", "role only")
    membership.refresh_membership(workspace, discover_repos(workspace))
    data = _publish(workspace, "bom-helper")
    assert data["ok"] is False
    assert "missing" in data["repos"][0]["error"]


def test_ops_publish_does_not_write_renglo_yaml(workspace: Path) -> None:
    helper = _ops_repo(workspace, "renglo-ops", policy=_WHEEL)
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    git(helper, "add", "CHANGE.md")
    git(helper, "commit", "-m", "work")
    bom = init_repo(workspace / "ops" / "example-bom", develop=False)
    (bom / "gitconvoy.toml").write_text('role = "bom"\n')
    (bom / "renglo.yaml").write_text("name: acme\nplatform: 0.1.0\n")
    git(bom, "add", "-A")
    git(bom, "commit", "-m", "bom")
    membership.refresh_membership(workspace, discover_repos(workspace))

    data = _publish(workspace, "renglo-ops")
    assert data["repos"][0]["status"] == "tagged"
    assert "pin" not in data["repos"][0]
    assert "platform: 0.1.0" in (bom / "renglo.yaml").read_text()


def test_ops_publish_needs_repo_or_sheet(workspace: Path) -> None:
    _ops_repo(workspace, "bom-helper")
    with pytest.raises(GitConvoyError, match="current ops sheet"):
        release_cmd.publish(workspace, [], push=False)


def test_ops_publish_sheet_waits_for_ops_pr_merge(workspace: Path) -> None:
    helper = _ops_repo(workspace, "renglo-ops", policy=_WHEEL)
    _tag_current(helper)
    (helper / "CHANGE.md").write_text("work\n")
    state = State()
    ops_cmd.start(workspace, state, "ship")
    ops_cmd.adopt(workspace, state)
    state = load(workspace)
    commit_cmd.commit(
        workspace,
        state,
        header="fix: ship",
        header_only=True,
        kind="ops",
    )

    data = release_cmd.publish(workspace, state=load(workspace), push=False)
    assert data["ok"] is False
    assert data["sheet"] == "ship"
    row = data["repos"][0]
    assert row["status"] == "pr-needed"
    assert row["next"]
    assert "v1.0.1" not in git(helper, "tag", "-l").stdout


def test_ops_publish_sheet_ships_publishing_repos_only(workspace: Path) -> None:
    helper = _ops_repo(workspace, "renglo-ops", policy=_WHEEL)
    launcher = _ops_repo(workspace, "launcher")
    _tag_current(helper)
    _tag_current(launcher)
    (helper / "CHANGE.md").write_text("wheel\n")
    (launcher / "TOOL.md").write_text("none\n")
    state = State()
    ops_cmd.start(workspace, state, "ship")
    ops_cmd.adopt(workspace, state)
    state = load(workspace)
    commit_cmd.commit(
        workspace,
        state,
        header="fix: ship",
        header_only=True,
        kind="ops",
    )
    git(helper, "checkout", "develop")
    git(helper, "merge", "--no-edit", "ops/ship")
    git(launcher, "checkout", "develop")
    git(launcher, "merge", "--no-edit", "ops/ship")

    data = release_cmd.publish(workspace, state=load(workspace), push=False)
    assert data["ok"] is True
    by_id = {row["id"]: row for row in data["repos"]}
    assert by_id["renglo-ops"]["status"] == "tagged"
    assert by_id["renglo-ops"]["tag"] == "v1.0.1"
    assert by_id["launcher"]["status"] == "skipped"
    assert by_id["launcher"]["reason"] == "publish=none"
    assert "v1.0.1" not in git(launcher, "tag", "-l").stdout
    git(helper, "checkout", "main")
    assert (helper / "CHANGE.md").read_text() == "wheel\n"
