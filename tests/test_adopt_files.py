from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from gitconvoy import adopt as adopt_cmd
from gitconvoy.cli import main
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, Train, TrainRepo, save


@pytest.fixture(autouse=True)
def _disable_adopt_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gitconvoy.ghutil.gh_available", lambda: False)


def _bom_repo(root: Path) -> Path:
    bom_repo = root / "ops" / "acme-bom"
    (bom_repo / "bom").mkdir(parents=True)
    (bom_repo / "bom" / "v1.4.0.json").write_text(
        json.dumps(
            {
                "version": "v1.4.0",
                "python": {
                    "renglo-lib": "1.2.3",
                    "renglo-api": "2.3.0",
                    "renglo-schd": "1.1.0",
                },
                "npm": {"@renglo/console": "0.8.0", "@renglo/schd": "1.1.0"},
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


def _train(status: str = "published") -> State:
    state = State(current_train="2026-W34")
    train = Train(name="2026-W34", branch="release/2026-W34", status=status)
    train.add_repo(
        TrainRepo(
            id="renglo-lib",
            path="dev/renglo-lib",
            from_version="1.2.3",
            to="1.2.4",
            stable_tag="v1.2.4",
        )
    )
    train.add_repo(
        TrainRepo(
            id="schd",
            path="extensions/schd",
            from_version="1.1.0",
            to="1.2.0",
            stable_tag="v1.2.0",
        )
    )
    train.add_repo(
        TrainRepo(
            id="console",
            path="console",
            from_version="0.8.0",
            to="0.8.1",
            stable_tag="v0.8.1",
        )
    )
    state.trains["2026-W34"] = train
    return state


def test_draft_and_pin(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = State()
    adopt_cmd.draft(tmp_path, state, "1.4.0", "1.5.0", bom=str(bom_repo), train="2026-W34")
    dest = bom_repo / "bom" / "v1.5.0.json"
    data = json.loads(dest.read_text())
    assert data["version"] == "v1.5.0"
    assert data["train"] == "2026-W34"
    adopt_cmd.pin(tmp_path, "1.5.0", "renglo-lib", "1.2.4", bom=str(bom_repo))
    data = json.loads(dest.read_text())
    assert data["python"]["renglo-lib"] == "1.2.4"
    adopt_cmd.point(tmp_path, "1.5.0", bom=str(bom_repo), production=False)
    text = (bom_repo / "deploy_targets.yml").read_text()
    assert "bom: 1.5.0" in text
    assert "enabled: false" in text


def test_take_drafts_pins_train_and_points(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train()
    data = adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    assert data["version"] == "v1.4.1"
    assert data["train"] == "2026-W34"
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["python"]["renglo-lib"] == "1.2.4"
    assert dest["python"]["renglo-schd"] == "1.2.0"
    assert dest["python"]["renglo-api"] == "2.3.0"
    assert dest["npm"]["@renglo/schd"] == "1.2.0"
    assert "@renglo/console" not in dest.get("npm", {})
    text = (bom_repo / "deploy_targets.yml").read_text()
    assert "bom: 1.4.1" in text
    assert "enabled: false" in text


def test_take_pins_rc_in_both_ecosystems(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train(status="stabilizing")
    state.trains["2026-W34"].repos[1].to = "1.2.0rc1"
    state.trains["2026-W34"].repos[1].stable_tag = None
    state.trains["2026-W34"].repos[1].rc_tag = "v1.2.0-rc.1"
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["python"]["renglo-schd"] == "1.2.0rc1"
    assert dest["npm"]["@renglo/schd"] == "1.2.0-rc.1"


def test_take_refuses_train_without_versions(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train(status="cut")
    for repo in state.trains["2026-W34"].repos:
        repo.to = None
    with pytest.raises(GitConvoyError, match="no versions to pin"):
        adopt_cmd.take(tmp_path, state, bom=str(bom_repo))


def test_take_updates_bom_repo_shas(tmp_path: Path) -> None:
    from conftest import git, init_repo

    bom_repo = _bom_repo(tmp_path)
    src = json.loads((bom_repo / "bom" / "v1.4.0.json").read_text())
    src["repos"] = {
        "renglo/pes": {
            "url": "git@github.com:renglo/pes.git",
            "commit": "oldsha0000000000000000000000000000000000",
            "branch": "main",
        }
    }
    (bom_repo / "bom" / "v1.4.0.json").write_text(json.dumps(src, indent=2) + "\n")
    (tmp_path / "extensions").mkdir()
    pes = init_repo(tmp_path / "extensions" / "pes")
    subprocess.run(
        ["git", "-C", str(pes), "remote", "add", "origin", "git@github.com:renglo/pes.git"],
        check=True,
        capture_output=True,
    )
    git(pes, "checkout", "-b", "release/2026-W34")
    git(pes, "commit", "--allow-empty", "-m", "train cut")
    tagged = git(pes, "rev-parse", "HEAD").stdout.strip()
    git(pes, "tag", "v1.2.0-rc.1")
    state = State(current_train="2026-W34")
    train = Train(name="2026-W34", branch="release/2026-W34", status="stabilizing")
    train.add_repo(
        TrainRepo(
            id="pes",
            path="extensions/pes",
            from_version="1.1.0",
            to="1.2.0rc1",
            rc_tag="v1.2.0-rc.1",
        )
    )
    state.trains["2026-W34"] = train
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["repos"]["renglo/pes"]["commit"] == tagged


def test_take_refresh_same_train_updates_in_place(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train(status="stabilizing")
    first = adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    assert first["mode"] == "draft"
    assert first["version"] == "v1.4.1"
    state.trains["2026-W34"].repos[1].to = "1.2.0rc2"
    state.trains["2026-W34"].repos[1].rc_tag = "v1.2.0-rc.2"
    second = adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    assert second["mode"] == "refresh"
    assert second["version"] == "v1.4.1"
    assert not (bom_repo / "bom" / "v1.4.2.json").exists()
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["python"]["renglo-schd"] == "1.2.0rc2"
    assert "Release B" in dest["description"]
    text = (bom_repo / "deploy_targets.yml").read_text()
    assert "bom: 1.4.1" in text


def test_take_after_production_bumps_new_version(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train(status="published")
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    adopt_cmd.promote(tmp_path, state, bom=str(bom_repo))
    next_train = Train(name="2026-W35", branch="release/2026-W35", status="published")
    next_train.add_repo(
        TrainRepo(
            id="renglo-lib",
            path="dev/renglo-lib",
            from_version="1.2.4",
            to="1.2.5",
            stable_tag="v1.2.5",
        )
    )
    state.trains["2026-W35"] = next_train
    state.current_train = "2026-W35"
    again = adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    assert again["mode"] == "draft"
    assert again["version"] == "v1.4.2"
    assert (bom_repo / "bom" / "v1.4.2.json").exists()


def test_take_same_train_refreshes_after_production(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train(status="published")
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    adopt_cmd.promote(tmp_path, state, bom=str(bom_repo))
    state.trains["2026-W34"].repos[0].to = "1.2.5"
    again = adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    assert again["mode"] == "refresh"
    assert again["version"] == "v1.4.1"
    assert not (bom_repo / "bom" / "v1.4.2.json").exists()
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["python"]["renglo-lib"] == "1.2.5"


def test_promote_refuses_stabilizing_train(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train(status="stabilizing")
    state.trains["2026-W34"].repos[1].to = "1.2.0rc1"
    state.trains["2026-W34"].repos[1].stable_tag = None
    state.trains["2026-W34"].repos[1].rc_tag = "v1.2.0-rc.1"
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    with pytest.raises(GitConvoyError, match="train publish"):
        adopt_cmd.promote(tmp_path, state, bom=str(bom_repo))
    text = (bom_repo / "deploy_targets.yml").read_text()
    assert "enabled: false" in text


def test_promote_refreshes_rc_bom_and_enables_production(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train(status="stabilizing")
    state.trains["2026-W34"].repos[1].to = "1.2.0rc1"
    state.trains["2026-W34"].repos[1].stable_tag = None
    state.trains["2026-W34"].repos[1].rc_tag = "v1.2.0-rc.1"
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    train = state.trains["2026-W34"]
    train.status = "published"
    train.repos[1].to = "1.2.0"
    train.repos[1].stable_tag = "v1.2.0"
    data = adopt_cmd.promote(tmp_path, state, bom=str(bom_repo))
    assert data["mode"] == "refresh"
    assert data["description"] == "Production. Release 2026-W34."
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["python"]["renglo-schd"] == "1.2.0"
    text = (bom_repo / "deploy_targets.yml").read_text()
    assert "enabled: true" in text


def test_take_cli_uses_current_train(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train()
    save(tmp_path, state)
    assert main(["--workspace", str(tmp_path), "--json", "adopt", "--bom", str(bom_repo)]) == 0
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["python"]["renglo-lib"] == "1.2.4"
    assert dest["train"] == "2026-W34"


def test_take_named_subcommand(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train()
    save(tmp_path, state)
    assert (
        main(
            [
                "--workspace",
                str(tmp_path),
                "--json",
                "adopt",
                "take",
                "--bom",
                str(bom_repo),
            ]
        )
        == 0
    )
    assert (bom_repo / "bom" / "v1.4.1.json").exists()


def test_promote_enables_production_on_current_bom(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train()
    data = adopt_cmd.promote(tmp_path, state, bom=str(bom_repo))
    assert data["version"] == "v1.4.1"
    assert data["mode"] in ("draft", "refresh")
    assert data["description"] == "Production. Release 2026-W34."
    text = (bom_repo / "deploy_targets.yml").read_text()
    assert "bom: 1.4.1" in text
    assert "enabled: true" in text
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["description"] == "Production. Release 2026-W34."


def test_refresh_after_publish_sets_staging_description(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train(status="stabilizing")
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    state.trains["2026-W34"].status = "published"
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["description"] == "Staging. Release 2026-W34."


def test_refresh_preserves_production_enabled(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train(status="published")
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    adopt_cmd.promote(tmp_path, state, bom=str(bom_repo))
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    text = (bom_repo / "deploy_targets.yml").read_text()
    assert "enabled: true" in text
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["description"] == "Production. Release 2026-W34."


def test_promote_cli_flag(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train()
    save(tmp_path, state)
    assert (
        main(
            [
                "--workspace",
                str(tmp_path),
                "--json",
                "adopt",
                "--production",
                "--bom",
                str(bom_repo),
            ]
        )
        == 0
    )
    text = (bom_repo / "deploy_targets.yml").read_text()
    assert "bom: 1.4.1" in text
    assert "enabled: true" in text


def test_promote_named_subcommand(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train()
    save(tmp_path, state)
    assert (
        main(
            [
                "--workspace",
                str(tmp_path),
                "--json",
                "adopt",
                "production",
                "--bom",
                str(bom_repo),
            ]
        )
        == 0
    )
    text = (bom_repo / "deploy_targets.yml").read_text()
    assert "enabled: true" in text


def test_discovers_bom_outside_ops(tmp_path: Path) -> None:
    bom = tmp_path / "tenants" / "acme-bom"
    bom.mkdir(parents=True)
    found = adopt_cmd.find_bom_repo(tmp_path)
    assert found.resolve() == bom.resolve()


def test_discovers_nested_bom_and_skips_vendor_dirs(tmp_path: Path) -> None:
    real = tmp_path / "customers" / "west" / "acme-bom"
    real.mkdir(parents=True)
    decoy = tmp_path / "node_modules" / "other-bom"
    decoy.mkdir(parents=True)
    found = adopt_cmd.find_bom_repo(tmp_path)
    assert found.resolve() == real.resolve()


def test_refuses_when_several_bom_repos(tmp_path: Path) -> None:
    (tmp_path / "ops" / "acme-bom").mkdir(parents=True)
    (tmp_path / "other-bom").mkdir()
    with pytest.raises(GitConvoyError, match="multiple \\*-bom repos"):
        adopt_cmd.find_bom_repo(tmp_path)


def test_console_clears_npm_pin_without_tag_publish_workflow(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train()
    console = tmp_path / "console"
    console.mkdir()
    (console / "package.json").write_text('{"name":"console","version":"0.8.1"}\n')
    data = adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert "@renglo/console" not in dest.get("npm", {})
    assert dest["python"]["renglo-lib"] == "1.2.4"
    cleared = [row for row in data["pins"] if row.get("action") == "cleared"]
    assert any(row["package"] == "@renglo/console" for row in cleared)


def test_take_pins_tenant_wl_from_package_json(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    src = json.loads((bom_repo / "bom" / "v1.4.0.json").read_text())
    src["repos"] = {
        "renglo/stanley-wl": {
            "url": "git@github.com:renglo/stanley-wl.git",
            "commit": "oldsha0000000000000000000000000000000000",
            "branch": "main",
        }
    }
    (bom_repo / "bom" / "v1.4.0.json").write_text(json.dumps(src, indent=2) + "\n")
    wl = tmp_path / "dev" / "stanley-wl"
    wl.mkdir(parents=True)
    (wl / "package.json").write_text('{"name":"@stanley/wl","version":"0.0.1"}\n')
    wf = wl / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "publish-npm.yml").write_text("on:\n  push:\n    tags:\n      - 'v*'\n")
    state = State(current_train="2026-W34")
    train = Train(name="2026-W34", branch="release/2026-W34", status="published")
    train.add_repo(
        TrainRepo(
            id="stanley-wl",
            path="dev/stanley-wl",
            from_version="0.0.1",
            to="0.0.1",
            stable_tag="v0.0.1",
        )
    )
    state.trains["2026-W34"] = train
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["npm"]["@stanley/wl"] == "0.0.1"
    assert "@renglo/stanley-wl" not in dest.get("npm", {})
    assert "renglo-stanley-wl" not in dest.get("python", {})
    assert "renglo/stanley-wl" not in dest.get("repos", {})


def _fake_verify_result(repos: list[dict], *, train: str = "2026-W34") -> dict:
    verified = [row for row in repos if row.get("status") == "success"]
    skipped = [row for row in repos if row.get("status") == "skip"]
    failed = [row for row in repos if row.get("status") not in {"success", "skip"}]
    return {
        "ok": not failed,
        "train": train,
        "tag_kind": "stable",
        "verified_count": len(verified),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "repo_count": len(repos),
        "repos": repos,
    }


def test_adopt_verify_failure_self_heals_to_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from conftest import git, init_repo

    bom_repo = _bom_repo(tmp_path)
    src = json.loads((bom_repo / "bom" / "v1.4.0.json").read_text())
    src["repos"] = {
        "renglo/schd": {
            "url": "git@github.com:renglo/schd.git",
            "commit": "oldsha0000000000000000000000000000000000",
            "branch": "main",
        }
    }
    (bom_repo / "bom" / "v1.4.0.json").write_text(json.dumps(src, indent=2) + "\n")
    schd = init_repo(tmp_path / "extensions" / "schd")
    subprocess.run(
        ["git", "-C", str(schd), "remote", "add", "origin", "git@github.com:renglo/schd.git"],
        check=True,
        capture_output=True,
    )
    git(schd, "tag", "v1.2.0")
    state = _train()

    def fake_verify(workspace, state, name, **kwargs):
        return _fake_verify_result(
            [
                {"id": "renglo-lib", "status": "success"},
                {"id": "schd", "status": "failure"},
                {"id": "console", "status": "skip"},
            ]
        )

    monkeypatch.setattr("gitconvoy.ghutil.gh_available", lambda: True)
    monkeypatch.setattr("gitconvoy.train.verify", fake_verify)

    data = adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["python"]["renglo-lib"] == "1.2.4"
    assert "renglo-schd" not in dest.get("python", {})
    assert "@renglo/schd" not in dest.get("npm", {})
    assert data["verify"]["failed_count"] == 1
    cleared = [row for row in data["pins"] if row.get("action") == "cleared" and row["id"] == "schd"]
    assert len(cleared) >= 1
    fallback = [row for row in data["pins"] if row.get("kind") == "fallback" and row["id"] == "schd"]
    assert fallback
    assert dest["repos"]["renglo/schd"]["commit"] != "oldsha0000000000000000000000000000000000"


def test_adopt_require_verify_refuses_on_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train()

    def fake_verify(workspace, state, name, **kwargs):
        return _fake_verify_result([{"id": "renglo-lib", "status": "failure"}])

    monkeypatch.setattr("gitconvoy.ghutil.gh_available", lambda: True)
    monkeypatch.setattr("gitconvoy.train.verify", fake_verify)

    with pytest.raises(GitConvoyError, match="verified"):
        adopt_cmd.take(tmp_path, state, bom=str(bom_repo), require_verify=True)
    assert not (bom_repo / "bom" / "v1.4.1.json").exists()


def test_adopt_no_verify_skips_gh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train()

    def boom(*args, **kwargs):
        raise AssertionError("verify should not run")

    monkeypatch.setattr("gitconvoy.ghutil.gh_available", lambda: True)
    monkeypatch.setattr("gitconvoy.train.verify", boom)

    data = adopt_cmd.take(tmp_path, state, bom=str(bom_repo), no_verify=True)
    dest = json.loads((bom_repo / "bom" / "v1.4.1.json").read_text())
    assert dest["python"]["renglo-lib"] == "1.2.4"
    assert "verify" not in data
