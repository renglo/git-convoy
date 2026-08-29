from __future__ import annotations

import json
from pathlib import Path

import pytest

from gitconvoy import adopt as adopt_cmd
from gitconvoy.cli import main
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, Train, TrainRepo, save


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
    assert dest["npm"]["@renglo/console"] == "0.8.1"
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
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
    data = adopt_cmd.promote(tmp_path, bom=str(bom_repo))
    assert data["version"] == "v1.4.1"
    text = (bom_repo / "deploy_targets.yml").read_text()
    assert "bom: 1.4.1" in text
    assert "enabled: true" in text


def test_promote_cli_flag(tmp_path: Path) -> None:
    bom_repo = _bom_repo(tmp_path)
    state = _train()
    save(tmp_path, state)
    assert main(["--workspace", str(tmp_path), "--json", "adopt", "--bom", str(bom_repo)]) == 0
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
    adopt_cmd.take(tmp_path, state, bom=str(bom_repo))
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
