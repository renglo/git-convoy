from __future__ import annotations

import json
from pathlib import Path

import pytest

from gitconvoy import gitutil
from gitconvoy import train as train_cmd
from gitconvoy.cli import main
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, Train, TrainRepo, load, save

from conftest import git, init_repo


def _service_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("service\n")
    git(path, "add", "-A")
    git(path, "commit", "-m", "init")
    git(path, "checkout", "-b", "develop")
    (path / "handler.py").write_text("print('x')\n")
    git(path, "add", "-A")
    git(path, "commit", "-m", "work")
    return path


def test_cut_skips_repos_without_version_file(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    _service_repo(workspace / "dev" / "webhook")
    schd = workspace / "extensions" / "schd"
    (schd / "note.txt").write_text("ahead\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "ahead on schd")
    state = State()
    data = train_cmd.cut(workspace, state, "2026-08-29")
    repo_ids = {repo["id"] for repo in data["repos"]}
    skipped_ids = {item["id"] for item in data["skipped"]}
    assert "schd" in repo_ids
    assert "webhook" in skipped_ids
    assert "webhook" not in repo_ids


def test_cut_includes_main_only_repo_with_version(
    workspace: Path, monkeypatch
) -> None:
    """White-label / main-only packs integrate on main; cut must still see them."""
    monkeypatch.chdir(workspace)
    wl = workspace / "dev" / "arbitium-wl"
    wl.mkdir(parents=True)
    git(wl, "init", "-b", "main")
    git(wl, "config", "user.email", "test@example.com")
    git(wl, "config", "user.name", "Test")
    (wl / "package.json").write_text(
        json.dumps({"name": "@arbitium/wl", "version": "0.0.1"}) + "\n"
    )
    git(wl, "add", "-A")
    git(wl, "commit", "-m", "init")
    (wl / "assets.txt").write_text("logo\n")
    git(wl, "add", "-A")
    git(wl, "commit", "-m", "custom assets")
    assert not gitutil.has_local_branch(wl, "develop")
    assert gitutil.develop_ahead_of_stable(wl)

    state = State()
    data = train_cmd.cut(workspace, state, "2026-09-03")
    repo_ids = {repo["id"] for repo in data["repos"]}
    assert "arbitium-wl" in repo_ids
    assert gitutil.current_branch(wl) == "release/2026-09-03"
    assert not gitutil.has_local_branch(wl, "develop")


def test_cut_explicit_repo_requires_version_file(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    _service_repo(workspace / "dev" / "webhook")
    state = State()
    with pytest.raises(GitConvoyError, match="webhook: no version file"):
        train_cmd.cut(workspace, state, "2026-08-29", repo_ids=["webhook"])


def test_cut_all_skipped_raises(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (root / "dev").mkdir(parents=True)
    (root / "extensions").mkdir()
    console = init_repo(root / "console")
    git(console, "tag", "v1.0.0")
    _service_repo(root / "dev" / "webhook")
    state = State()
    with pytest.raises(GitConvoyError, match="skipped without version files"):
        train_cmd.cut(root, state, "2026-08-29")


def test_delete_removes_release_branches_and_train_sheet(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State(current_train="2026-08-29")
    train = Train(name="2026-08-29", branch="release/2026-08-29", status="cut")
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "-b", "release/2026-08-29")
    git(schd, "commit", "--allow-empty", "-m", "train")
    git(schd, "checkout", "develop")
    git(schd, "merge", "--no-edit", "release/2026-08-29")
    git(schd, "checkout", "release/2026-08-29")
    train.add_repo(TrainRepo(id="schd", path="extensions/schd", to="1.0.1rc1"))
    state.trains["2026-08-29"] = train
    save(workspace, state)
    data = train_cmd.delete(workspace, load(workspace), yes=True)
    assert data["deleted"] is True
    assert gitutil.current_branch(schd) == "develop"
    assert not gitutil.has_local_branch(schd, "release/2026-08-29")
    state = load(workspace)
    assert state.current_train is None
    assert "2026-08-29" not in state.trains


def test_delete_requires_yes_for_json(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    state = State(current_train="2026-08-29")
    train = Train(name="2026-08-29", branch="release/2026-08-29")
    train.add_repo(TrainRepo(id="schd", path="extensions/schd"))
    state.trains["2026-08-29"] = train
    save(workspace, state)
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "-b", "release/2026-08-29")
    capsys.readouterr()
    assert main(["--json", "train", "delete"]) == 1
    err = json.loads(capsys.readouterr().out)
    assert "--yes" in err["error"]
    assert gitutil.has_local_branch(schd, "release/2026-08-29")


def test_delete_refuses_unmerged_commits(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State(current_train="2026-08-29")
    train = Train(name="2026-08-29", branch="release/2026-08-29", status="cut")
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "-b", "release/2026-08-29")
    git(schd, "commit", "--allow-empty", "-m", "train")
    train.add_repo(TrainRepo(id="schd", path="extensions/schd", to="1.0.1rc1"))
    state.trains["2026-08-29"] = train
    save(workspace, state)
    with pytest.raises(GitConvoyError, match="would lose work"):
        train_cmd.delete(workspace, load(workspace), yes=True)
    assert gitutil.has_local_branch(schd, "release/2026-08-29")
    assert gitutil.current_branch(schd) == "release/2026-08-29"


def test_delete_refuses_unmerged_origin_commits(
    workspace: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State(current_train="2026-08-29")
    train = Train(name="2026-08-29", branch="release/2026-08-29", status="cut")
    schd = workspace / "extensions" / "schd"
    origin = tmp_path / "schd.git"
    git(origin.parent, "init", "--bare", str(origin))
    git(schd, "remote", "add", "origin", str(origin))
    git(schd, "checkout", "-b", "release/2026-08-29")
    git(schd, "commit", "--allow-empty", "-m", "train")
    git(schd, "push", "-u", "origin", "release/2026-08-29")
    git(schd, "checkout", "develop")
    git(schd, "merge", "--no-edit", "release/2026-08-29")
    git(schd, "checkout", "release/2026-08-29")
    git(schd, "commit", "--allow-empty", "-m", "only-on-origin")
    git(schd, "push", "origin", "release/2026-08-29")
    git(schd, "reset", "--hard", "HEAD~1")
    git(schd, "fetch")
    train.add_repo(TrainRepo(id="schd", path="extensions/schd", to="1.0.1rc1"))
    state.trains["2026-08-29"] = train
    save(workspace, state)
    with pytest.raises(GitConvoyError, match="origin/release/2026-08-29"):
        train_cmd.delete(workspace, load(workspace), yes=True, remote=True)
    assert gitutil.has_local_branch(schd, "release/2026-08-29")
    assert gitutil.has_remote_branch(schd, "release/2026-08-29")
    assert gitutil.current_branch(schd) == "release/2026-08-29"


def test_delete_refuses_uncommitted_files(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State(current_train="2026-08-29")
    train = Train(name="2026-08-29", branch="release/2026-08-29", status="cut")
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "-b", "release/2026-08-29")
    (schd / "scratch.txt").write_text("keep me\n")
    train.add_repo(TrainRepo(id="schd", path="extensions/schd"))
    state.trains["2026-08-29"] = train
    save(workspace, state)
    with pytest.raises(GitConvoyError, match="uncommitted"):
        train_cmd.delete(workspace, load(workspace), yes=True)
    assert (schd / "scratch.txt").read_text() == "keep me\n"
    assert gitutil.current_branch(schd) == "release/2026-08-29"
    assert gitutil.has_local_branch(schd, "release/2026-08-29")


def test_publish_merges_main_into_develop(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31")
    train_cmd.tag_rc(workspace, state, push=False)
    data = train_cmd.publish(workspace, state, push=False)
    assert data["repos"]
    for row in data["repos"]:
        assert row["synced_develop"] is True
        rel = "extensions/schd" if row["id"] == "schd" else "dev/renglo-lib"
        repo = workspace / rel
        assert gitutil.is_ancestor(repo, row["tag"], "develop")
        assert gitutil.current_branch(repo) == "develop"
    with pytest.raises(GitConvoyError, match="no repos are ahead"):
        train_cmd.cut(workspace, state, "2026-09-01")


def test_publish_then_new_develop_work_is_cuttable(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    train_cmd.tag_rc(workspace, state, push=False)
    train_cmd.publish(workspace, state, push=False)
    lib = workspace / "dev" / "renglo-lib"
    git(lib, "tag", "v1.0.0")
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    (schd / "next.py").write_text("print('next')\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "next feature")
    data = train_cmd.cut(workspace, state, "2026-09-01")
    assert {repo["id"] for repo in data["repos"]} == {"schd"}


def test_publish_recreates_develop_when_missing(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    train_cmd.tag_rc(workspace, state, push=False)
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "main")
    git(schd, "branch", "-D", "develop")
    data = train_cmd.publish(workspace, state, push=False)
    schd_row = next(row for row in data["repos"] if row["id"] == "schd")
    assert schd_row["synced_develop"] is True
    assert gitutil.has_local_branch(schd, "develop")
    assert gitutil.current_branch(schd) == "develop"


def test_publish_develop_conflict_leaves_train_published(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    train_cmd.tag_rc(workspace, state, push=False)
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "diverge develop")
    data = train_cmd.publish(workspace, state, push=False)
    assert data["ok"] is False
    assert "train mergeback" in (data.get("note") or "")
    assert load(workspace).trains["2026-08-31"].status == "published"
    assert gitutil.rev_parse(schd, "MERGE_HEAD") is None
    retry = train_cmd.mergeback(workspace, load(workspace), push=False)
    assert retry["ok"] is False
    assert retry["failed"] == ["schd"]


def test_mergeback_continues_past_one_conflict(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31")
    train_cmd.tag_rc(workspace, state, push=False)
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "diverge develop")
    data = train_cmd.publish(workspace, state, push=False)
    assert data["ok"] is False
    assert data["mergeback"]["failed"] == ["schd"]
    lib_row = next(row for row in data["repos"] if row["id"] == "renglo-lib")
    schd_row = next(row for row in data["repos"] if row["id"] == "schd")
    assert lib_row["synced_develop"] is True
    assert schd_row["synced_develop"] is False
    lib = workspace / "dev" / "renglo-lib"
    assert gitutil.is_ancestor(lib, lib_row["tag"], "develop")


def test_mergeback_unsticks_develop_behind_tagged_main(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    train_cmd.tag_rc(workspace, state, push=False)
    schd = workspace / "extensions" / "schd"
    before = gitutil.rev_parse(schd, "develop")
    train_cmd.publish(workspace, state, push=False)
    git(schd, "checkout", "develop")
    git(schd, "reset", "--hard", before)
    tag = load(workspace).trains["2026-08-31"].repos[0].stable_tag
    assert tag
    assert not gitutil.is_ancestor(schd, tag, "develop")
    data = train_cmd.mergeback(workspace, load(workspace), push=False)
    assert data["ok"] is True
    schd_row = next(row for row in data["repos"] if row["id"] == "schd")
    assert schd_row["status"] == "merged"
    assert gitutil.is_ancestor(schd, tag, "develop")
    again = train_cmd.mergeback(workspace, load(workspace), push=False)
    already = next(row for row in again["repos"] if row["id"] == "schd")
    assert again["ok"] is True
    assert already["status"] == "already"


def test_mergeback_refuses_before_publish(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    with pytest.raises(GitConvoyError, match="mergeback runs after train publish"):
        train_cmd.mergeback(workspace, state, push=False)


def test_mergeback_heals_non_participant_repo(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    data_repo = init_repo(workspace / "extensions" / "data")
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    train_cmd.tag_rc(workspace, state, push=False)
    git(data_repo, "checkout", "main")
    (data_repo / "pyproject.toml").write_text(
        '[project]\nname = "data"\nversion = "2.0.0"\n'
    )
    git(data_repo, "add", "-A")
    git(data_repo, "commit", "-m", "hotfix on main")
    git(data_repo, "tag", "v2.0.0")
    assert not gitutil.is_ancestor(data_repo, "v2.0.0", "develop")
    train_cmd.publish(workspace, state, push=False)
    data_row = next(
        row
        for row in load(workspace).trains["2026-08-31"].repos
        if row.id == "schd"
    )
    assert data_row.stable_tag
    mb = train_cmd.mergeback(workspace, load(workspace), push=False)
    healed = next(row for row in mb["repos"] if row["id"] == "data")
    assert healed["status"] in {"merged", "already"}
    assert gitutil.is_ancestor(data_repo, "v2.0.0", "develop")


def test_tag_rc_syncs_develop_before_tagging(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "main")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "2.0.0"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "stable on main")
    git(schd, "tag", "v2.0.0")
    before = gitutil.rev_parse(schd, "develop")
    assert not gitutil.is_ancestor(schd, "v2.0.0", "develop")
    data = train_cmd.tag_rc(workspace, state, push=False)
    assert data["develop_sync"]["ok"] is True
    assert gitutil.is_ancestor(schd, "v2.0.0", "develop")
    assert gitutil.current_branch(schd) == "release/2026-08-31"
    assert gitutil.rev_parse(schd, "develop") != before


def test_tag_rc_again_bumps_rc_suffix(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    first = train_cmd.tag_rc(workspace, state, push=False)
    schd_first = next(row for row in first["repos"] if row["id"] == "schd")
    assert schd_first["tag"] == "v1.0.1-rc.1"
    assert schd_first["version"] == "1.0.1rc1"

    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "release/2026-08-31")
    (schd / "fix.py").write_text("print('fix')\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "stabilization fix")

    second = train_cmd.tag_rc(workspace, load(workspace), push=False)
    schd_second = next(row for row in second["repos"] if row["id"] == "schd")
    assert schd_second["tag"] == "v1.0.1-rc.2"
    assert schd_second["version"] == "1.0.1rc2"
    assert gitutil.rev_parse(schd, "refs/tags/v1.0.1-rc.2")
    assert gitutil.rev_parse(schd, "HEAD") == gitutil.rev_parse(
        schd, "refs/tags/v1.0.1-rc.2"
    )
    sheet = load(workspace).trains["2026-08-31"].repos[0]
    assert sheet.rc_tag == "v1.0.1-rc.2"
    assert sheet.to == "1.0.1rc2"


def test_tag_rc_again_keeps_rc_when_head_matches_tag(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    train_cmd.tag_rc(workspace, state, push=False)
    second = train_cmd.tag_rc(workspace, load(workspace), push=False)
    schd_row = next(row for row in second["repos"] if row["id"] == "schd")
    assert schd_row["tag"] == "v1.0.1-rc.1"
    assert schd_row["version"] == "1.0.1rc1"
    sheet = load(workspace).trains["2026-08-31"].repos[0]
    assert sheet.rc_tag == "v1.0.1-rc.1"
    assert sheet.to == "1.0.1rc1"


def test_tag_rc_skips_already_used_rc_tags(
    workspace: Path, monkeypatch
) -> None:
    """A previous train's vX.Y.Z-rc.N must not be reused on a new HEAD."""
    monkeypatch.chdir(workspace)
    schd = workspace / "extensions" / "schd"
    git(schd, "tag", "v1.0.1-rc.1")
    git(schd, "commit", "--allow-empty", "-m", "previous-train-rc2")
    git(schd, "tag", "v1.0.1-rc.2")
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    data = train_cmd.tag_rc(workspace, load(workspace), push=False)
    schd_row = next(row for row in data["repos"] if row["id"] == "schd")
    assert schd_row["tag"] == "v1.0.1-rc.3"
    assert schd_row["version"] == "1.0.1rc3"
    assert gitutil.rev_parse(schd, "HEAD") == gitutil.rev_parse(
        schd, "refs/tags/v1.0.1-rc.3"
    )


def test_tag_rc_starts_past_released_stable(
    workspace: Path, monkeypatch
) -> None:
    """After v0.0.5 is released, late-join tag-rc must not mint 0.0.5-rc.N."""
    monkeypatch.chdir(workspace)
    lib = workspace / "dev" / "renglo-lib"
    git(lib, "tag", "v1.0.0-rc.1")
    git(lib, "commit", "--allow-empty", "-m", "previous-rc2")
    git(lib, "tag", "v1.0.0-rc.2")
    git(lib, "commit", "--allow-empty", "-m", "release-1.0.0")
    git(lib, "tag", "v1.0.0")
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    (lib / "late.py").write_text("join\n")
    train_cmd.adopt(workspace, load(workspace))
    git(lib, "add", "-A")
    git(lib, "commit", "-m", "late join")
    data = train_cmd.tag_rc(workspace, load(workspace), push=False)
    lib_row = next(row for row in data["repos"] if row["id"] == "renglo-lib")
    assert lib_row["tag"] == "v1.0.1-rc.1"
    assert lib_row["version"] == "1.0.1rc1"


def test_adopt_dirty_product_keeps_version(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    schd_row = next(
        row for row in load(workspace).trains["2026-09-03"].repos if row.id == "schd"
    )
    schd_to = schd_row.to
    lib = workspace / "dev" / "renglo-lib"
    (lib / "fix.py").write_text("print('late join')\n")
    assert gitutil.current_branch(lib) == "develop"

    data = train_cmd.adopt(workspace, load(workspace))
    adopted = {row["id"]: row for row in data["adopted"]}
    assert "renglo-lib" in adopted
    assert adopted["renglo-lib"]["action"] == "branched"
    assert gitutil.current_branch(lib) == "release/2026-09-03"
    assert gitutil.is_dirty(lib)
    assert 'version = "1.0.0"' in (lib / "pyproject.toml").read_text()
    sheet = load(workspace).trains["2026-09-03"]
    lib_row = next(row for row in sheet.repos if row.id == "renglo-lib")
    assert lib_row.from_version == "1.0.0"
    assert lib_row.to is None
    assert next(row for row in sheet.repos if row.id == "schd").to == schd_to


def test_adopt_repos_includes_clean_product(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    lib = workspace / "dev" / "renglo-lib"
    assert not gitutil.is_dirty(lib)
    data = train_cmd.adopt(workspace, load(workspace), repo_ids=["renglo-lib"])
    assert {row["id"] for row in data["adopted"]} == {"renglo-lib"}
    assert gitutil.current_branch(lib) == "release/2026-09-03"
    assert 'version = "1.0.0"' in (lib / "pyproject.toml").read_text()


def test_adopt_refuses_dirty_feature_branch(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    lib = workspace / "dev" / "renglo-lib"
    git(lib, "checkout", "-b", "feature/late")
    (lib / "fix.py").write_text("nope\n")
    with pytest.raises(GitConvoyError, match="feature/late"):
        train_cmd.adopt(workspace, load(workspace))


def test_adopt_ignores_dirty_aux(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    from gitconvoy import membership
    from gitconvoy.workspace import discover_repos

    launcher = init_repo(workspace / "ops" / "launcher")
    (launcher / "gitconvoy.toml").write_text('role = "aux"\n')
    git(launcher, "add", "gitconvoy.toml")
    git(launcher, "commit", "-m", "marker")
    membership.refresh_membership(workspace, discover_repos(workspace))
    (launcher / "TOOL.md").write_text("aux dirty\n")
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    with pytest.raises(GitConvoyError, match="no dirty product repos"):
        train_cmd.adopt(workspace, load(workspace))
    assert gitutil.current_branch(launcher) != "release/2026-09-03"


def test_adopt_refuses_published_train(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    train_cmd.tag_rc(workspace, state, push=False)
    train_cmd.publish(workspace, state, push=False)
    lib = workspace / "dev" / "renglo-lib"
    git(lib, "checkout", "develop")
    (lib / "fix.py").write_text("too late\n")
    with pytest.raises(GitConvoyError, match="published"):
        train_cmd.adopt(workspace, load(workspace))


def test_adopt_repos_rejects_aux(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    from gitconvoy import membership
    from gitconvoy.workspace import discover_repos

    helper = init_repo(workspace / "ops" / "bom-helper")
    (helper / "gitconvoy.toml").write_text('role = "aux"\n')
    git(helper, "add", "gitconvoy.toml")
    git(helper, "commit", "-m", "marker")
    membership.refresh_membership(workspace, discover_repos(workspace))
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    with pytest.raises(GitConvoyError, match="aux repo"):
        train_cmd.adopt(workspace, load(workspace), repo_ids=["bom-helper"])


def test_tag_rc_refuses_dirty_train_participant(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    schd = workspace / "extensions" / "schd"
    (schd / "fix.py").write_text("uncommitted\n")
    with pytest.raises(GitConvoyError, match="train commit"):
        train_cmd.tag_rc(workspace, load(workspace), push=False)
    assert gitutil.is_dirty(schd)


def test_tag_rc_ignores_dirty_non_participant(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    lib = workspace / "dev" / "renglo-lib"
    (lib / "side.py").write_text("not on train\n")
    data = train_cmd.tag_rc(workspace, load(workspace), push=False)
    assert any(row["id"] == "schd" for row in data["repos"])
    assert gitutil.is_dirty(lib)


def test_train_commit_then_tag_rc(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    schd = workspace / "extensions" / "schd"
    (schd / "fix.py").write_text("stabilize\n")
    capsys.readouterr()
    assert main(
        [
            "--json",
            "train",
            "commit",
            "--header",
            "fix: stabilize schd",
            "--header-only",
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "commit"
    assert result["train"] == "2026-09-03"
    assert [row["id"] for row in result["repos"]] == ["schd"]
    assert not gitutil.is_dirty(schd)
    data = train_cmd.tag_rc(workspace, load(workspace), push=False)
    assert any(row["id"] == "schd" for row in data["repos"])


def test_train_commit_plan_lists_dirty(
    workspace: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    schd = workspace / "extensions" / "schd"
    (schd / "fix.py").write_text("plan me\n")
    capsys.readouterr()
    assert main(["--json", "train", "commit"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "plan"
    assert plan["train"] == "2026-09-03"
    assert [row["id"] for row in plan["repos"]] == ["schd"]
    assert gitutil.is_dirty(schd)


def test_train_commit_ignores_dirty_bom_when_aux_toml_stale(
    workspace: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(workspace)
    from gitconvoy import membership

    bom = init_repo(workspace / "ops" / "example-bom", develop=False)
    (bom / "gitconvoy.toml").write_text('role = "bom"\n')
    membership.write_membership(workspace, aux=[], bom=["arbitium-bom"])
    (bom / "NOTE.md").write_text("docs\n")
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    schd = workspace / "extensions" / "schd"
    (schd / "fix.py").write_text("on train\n")
    capsys.readouterr()
    assert main(["--json", "train", "commit"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "plan"
    assert [row["id"] for row in plan["repos"]] == ["schd"]
    assert gitutil.is_dirty(bom)


def test_train_commit_refuses_unadopted_dirty(
    workspace: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    schd = workspace / "extensions" / "schd"
    lib = workspace / "dev" / "renglo-lib"
    (schd / "fix.py").write_text("on train\n")
    (lib / "extra.py").write_text("not on train\n")
    capsys.readouterr()
    assert main(["--json", "train", "commit"]) == 1
    err = json.loads(capsys.readouterr().out)
    assert "not on the train sheet" in err["error"]
    assert "renglo-lib" in err["error"]
    assert gitutil.is_dirty(schd)


def test_adopt_cli_dirty(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-09-03", repo_ids=["schd"])
    lib = workspace / "dev" / "renglo-lib"
    (lib / "fix.py").write_text("cli\n")
    capsys.readouterr()
    assert main(["--json", "train", "adopt"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert {row["id"] for row in payload["adopted"]} == {"renglo-lib"}
    assert gitutil.current_branch(lib) == "release/2026-09-03"
