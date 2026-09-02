from __future__ import annotations

import json
from pathlib import Path

import pytest

from gitconvoy import gitutil
from gitconvoy import hotfix as hotfix_cmd
from gitconvoy.cli import main
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import Hotfix, HotfixRepo, State, load, save
from gitconvoy.versions import read_version

from conftest import git


def _bom_repo(root: Path) -> Path:
    bom_repo = root / "ops" / "acme-bom"
    (bom_repo / "bom").mkdir(parents=True)
    (bom_repo / "bom" / "v1.4.0.json").write_text(
        json.dumps(
            {
                "version": "v1.4.0",
                "python": {"renglo-lib": "1.2.3", "renglo-schd": "1.0.0"},
                "npm": {},
            },
            indent=2,
        )
        + "\n"
    )
    (bom_repo / "deploy_targets.yml").write_text(
        "bom: 1.4.0\n\ntenants:\n  stanley:\n    stages:\n"
        "      staging:\n        enabled: true\n"
        "      production:\n        enabled: true\n"
    )
    return bom_repo


def test_state_hotfix_roundtrip(workspace: Path) -> None:
    state = State(
        current_hotfix="fetch-file",
        hotfixes={
            "fetch-file": Hotfix(
                name="fetch-file",
                branch="hotfix/fetch-file",
                status="in-progress",
                repos=[
                    HotfixRepo(
                        id="console",
                        path="console",
                        from_version="0.0.2",
                        to="0.0.3",
                        stable_tag="v0.0.3",
                    )
                ],
            )
        },
    )
    save(workspace, state)
    loaded = load(workspace)
    assert loaded.current_hotfix == "fetch-file"
    item = loaded.hotfixes["fetch-file"]
    assert item.branch == "hotfix/fetch-file"
    assert item.repos[0].to == "0.0.3"
    assert item.repos[0].stable_tag == "v0.0.3"


def test_start_two_repos_from_develop_dirty(workspace: Path) -> None:
    schd = workspace / "extensions" / "schd"
    lib = workspace / "dev" / "renglo-lib"
    (schd / "fix.py").write_text("print('hotfix')\n")
    (lib / "fix.py").write_text("print('hotfix')\n")
    state = State()
    data = hotfix_cmd.start(workspace, state, "fetch-file")
    ids = {row["id"] for row in data["repos"]}
    assert ids == {"schd", "renglo-lib"}
    assert gitutil.current_branch(schd) == "hotfix/fetch-file"
    assert gitutil.current_branch(lib) == "hotfix/fetch-file"
    assert read_version(schd)["python"] == "1.0.1"
    assert read_version(lib)["python"] == "1.0.1"
    assert gitutil.is_dirty(schd)
    state = load(workspace)
    assert state.current_hotfix == "fetch-file"
    assert set(state.hotfixes["fetch-file"].repo_ids()) == {"schd", "renglo-lib"}


def test_start_refuses_feature_branch(workspace: Path) -> None:
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "-b", "feature/other")
    (schd / "fix.py").write_text("x\n")
    with pytest.raises(GitConvoyError, match="feature/other"):
        hotfix_cmd.start(workspace, State(), "oops")


def test_commit_publish_absorbs_feature_branch(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    git(schd, "checkout", "-b", "feature/wip")
    (schd / "wip.py").write_text("wip\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "wip")
    git(schd, "checkout", "develop")
    (schd / "fix.py").write_text("print('hotfix')\n")
    save(workspace, State())
    assert main(["--json", "hotfix", "start", "console-fetch"]) == 0
    assert (
        main(
            [
                "--json",
                "hotfix",
                "commit",
                "--header",
                "fix: restore fetchStoredFile",
                "--header-only",
            ]
        )
        == 0
    )
    git(schd, "checkout", "main")
    merged = git(schd, "merge", "--no-edit", "hotfix/console-fetch")
    assert merged.returncode == 0
    data = hotfix_cmd.publish(workspace, load(workspace), push_remote=False)
    assert data["repos"][0]["tag"] == "v1.0.1"
    assert data["repos"][0]["develop"]["synced"] is True
    git(schd, "checkout", "develop")
    assert (schd / "fix.py").read_text() == "print('hotfix')\n"
    assert read_version(schd)["python"] == "1.0.1"
    absorbed = {row["branch"]: row for row in data["repos"][0]["feature_branches"]}
    assert absorbed["feature/wip"]["ok"] is True
    git(schd, "checkout", "feature/wip")
    assert (schd / "fix.py").read_text() == "print('hotfix')\n"
    assert (schd / "wip.py").read_text() == "wip\n"


def test_adopt_pins_only_hotfix_packages(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    schd = workspace / "extensions" / "schd"
    (schd / "fix.py").write_text("print('hotfix')\n")
    save(workspace, State())
    assert main(["--json", "hotfix", "start", "patch"]) == 0
    assert (
        main(
            [
                "--json",
                "hotfix",
                "commit",
                "--header",
                "fix: patch",
                "--header-only",
            ]
        )
        == 0
    )
    git(schd, "checkout", "main")
    git(schd, "merge", "--no-edit", "hotfix/patch")
    hotfix_cmd.publish(workspace, load(workspace), push_remote=False)
    bom = _bom_repo(workspace)
    data = hotfix_cmd.adopt(workspace, load(workspace), bom=str(bom))
    dest = json.loads((bom / "bom" / "v1.4.1.json").read_text())
    assert dest["python"]["renglo-schd"] == "1.0.1"
    assert dest["python"]["renglo-lib"] == "1.2.3"
    assert data["version"] == "v1.4.1"
    text = (bom / "deploy_targets.yml").read_text()
    assert "bom: 1.4.1" in text
    assert "enabled: false" in text
    assert any(row["package"] == "renglo-schd" for row in data["pins"])


def test_prs_compare_targets_main(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    schd = workspace / "extensions" / "schd"
    (schd / "fix.py").write_text("x\n")
    save(workspace, State())
    assert main(["--json", "hotfix", "start", "x"]) == 0
    assert (
        main(["--json", "hotfix", "commit", "--header", "fix: x", "--header-only"])
        == 0
    )
    git(schd, "remote", "add", "origin", "git@github.com:renglo/schd.git")
    monkeypatch.setattr("gitconvoy.hotfix.gitutil.push", lambda *args, **kwargs: None)
    data = hotfix_cmd.prs(workspace, load(workspace), use_gh=False)
    assert data["repos"][0]["compare"].endswith("compare/main...hotfix/x")
