from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from conftest import git, init_repo
from gitconvoy import adopt as adopt_cmd
from gitconvoy.cli import main
from gitconvoy.platform_check import (
    check,
    compatibility,
    declared_platform_package_json,
    declared_platform_pyproject,
    format_check_text,
)
from gitconvoy.state import State, Train, TrainRepo, save


def test_compatibility_window() -> None:
    assert compatibility("0.1.4", "0.1.4") == "match"
    assert compatibility("0.1.4", "0.1.5") == "compatible"
    assert compatibility("0.1.4", "0.1.5rc1") == "compatible"
    assert compatibility("0.1.4", "0.1.2") == "ahead"
    assert compatibility("0.1.4", "0.2.1") == "stale"
    assert compatibility("0.2.0", "0.2.1") == "compatible"


def test_reads_declaration_tables() -> None:
    assert (
        declared_platform_pyproject(
            '[project]\nname = "renglo-lib"\nversion = "1.0.0"\n\n'
            '[tool.renglo]\nplatform = "0.1.4"\n'
        )
        == "0.1.4"
    )
    assert (
        declared_platform_package_json(
            '{"name":"@renglo/console","version":"0.0.11","renglo":{"platform":"0.1.4"}}\n'
        )
        == "0.1.4"
    )


def _workspace(tmp_path: Path, platform: str) -> tuple[Path, Path]:
    root = tmp_path / "ws"
    (root / "dev").mkdir(parents=True)
    (root / "extensions").mkdir()
    lib = root / "dev" / "renglo-lib"
    lib.mkdir()
    (lib / "pyproject.toml").write_text(
        '[project]\nname = "renglo-lib"\nversion = "1.2.4"\n\n'
        '[tool.renglo]\nplatform = "0.1.4"\n'
    )
    bom = root / "ops" / "acme-bom"
    (bom / "bom").mkdir(parents=True)
    (bom / "bom" / "v1.4.0.json").write_text(
        json.dumps({"version": "v1.4.0", "python": {"renglo-lib": "1.2.3"}}) + "\n"
    )
    (bom / "renglo.yaml").write_text(
        f"platform: {platform}\nrelease:\n  bom: 1.4.0\n"
    )
    return root, bom


def _state() -> State:
    state = State(current_train="2026-W34")
    train = Train(name="2026-W34", branch="release/2026-W34", status="published")
    train.add_repo(
        TrainRepo(
            id="renglo-lib",
            path="dev/renglo-lib",
            to="1.2.4",
            stable_tag="v1.2.4",
        )
    )
    state.trains["2026-W34"] = train
    return state


def _statuses(report: dict) -> list[str]:
    return [row["status"] for row in report["platform_warnings"]]


def test_check_warns_when_package_is_ahead(tmp_path: Path) -> None:
    root, bom = _workspace(tmp_path, "0.1.2")
    report = check(root, _state(), bom=str(bom))
    assert _statuses(report) == ["ahead"]
    assert "is ahead of platform 0.1.2" in report["platform_warnings"][0]["message"]
    assert "Upgrade the platform to 0.1.4" in report["platform_warnings"][0]["message"]
    assert not (bom / "bom" / "v1.4.1.json").exists()
    assert "platform: 0.1.2\n" in (bom / "renglo.yaml").read_text()


def test_check_is_quiet_on_a_later_patch(tmp_path: Path) -> None:
    root, bom = _workspace(tmp_path, "0.1.5")
    report = check(root, _state(), bom=str(bom))
    assert report["platform_warnings"] == []
    assert report["warning_count"] == 0
    assert report["packages"][0]["status"] == "compatible"
    text = format_check_text(report)
    assert "compatible" in text
    assert "renglo-lib 1.2.4" in text
    assert "requires 0.1.4" in text
    assert text.endswith("1 compatible")


def test_rc_pin_marks_status_as_provisional(tmp_path: Path) -> None:
    root, bom = _workspace(tmp_path, "0.1.5rc1")
    lib = root / "dev" / "renglo-lib" / "pyproject.toml"
    lib.write_text(
        '[project]\nname = "renglo-lib"\nversion = "1.2.4rc1"\n\n'
        '[tool.renglo]\nplatform = "0.1.4"\n'
    )
    state = _state()
    state.trains["2026-W34"].repos[0].to = "1.2.4rc1"
    state.trains["2026-W34"].repos[0].stable_tag = None
    state.trains["2026-W34"].repos[0].rc_tag = "v1.2.4-rc.1"
    report = check(root, state, bom=str(bom))
    assert report["packages"][0]["status"] == "compatible"
    assert report["packages"][0]["aspirational"] is True
    text = format_check_text(report)
    assert "compatible*" in text
    assert "provisional" in text


def test_check_marks_an_exact_pin_as_match(tmp_path: Path) -> None:
    root, bom = _workspace(tmp_path, "0.1.4")
    report = check(root, _state(), bom=str(bom))
    assert report["platform_warnings"] == []
    assert report["packages"][0]["status"] == "match"
    assert "match" in format_check_text(report)


def test_check_warns_when_package_is_behind(tmp_path: Path) -> None:
    root, bom = _workspace(tmp_path, "0.2.1")
    report = check(root, _state(), bom=str(bom))
    assert _statuses(report) == ["stale"]
    assert "declares the 0.2 line" in report["platform_warnings"][0]["message"]


def test_check_warns_when_declaration_is_missing(tmp_path: Path) -> None:
    root, bom = _workspace(tmp_path, "0.1.4")
    lib = root / "dev" / "renglo-lib" / "pyproject.toml"
    lib.write_text('[project]\nname = "renglo-lib"\nversion = "1.2.4"\n')
    report = check(root, _state(), bom=str(bom))
    assert _statuses(report) == ["missing"]


def test_check_reads_the_tagged_declaration(tmp_path: Path) -> None:
    root, bom = _workspace(tmp_path, "0.1.5")
    lib_path = root / "dev" / "renglo-lib"
    shutil.rmtree(lib_path)
    lib = init_repo(lib_path, develop=False)
    declared = (
        '[project]\nname = "renglo-lib"\nversion = "1.2.4"\n\n'
        '[tool.renglo]\nplatform = "0.1.4"\n'
    )
    (lib / "pyproject.toml").write_text(declared)
    git(lib, "add", "-A")
    git(lib, "commit", "-m", "declare platform")
    git(lib, "tag", "v1.2.4")
    (lib / "pyproject.toml").write_text(declared.replace("0.1.4", "0.9.0"))
    report = check(root, _state(), bom=str(bom))
    assert report["platform_warnings"] == []
    assert report["packages"][0]["status"] == "compatible"


def test_take_warns_and_still_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gitconvoy.ghutil.gh_available", lambda: False)
    root, bom = _workspace(tmp_path, "0.1.2")
    wf = root / "dev" / "renglo-lib" / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "publish.yml").write_text("on:\n  push:\n    tags:\n      - 'v*'\n")
    data = adopt_cmd.take(root, _state(), bom=str(bom))
    assert _statuses(data) == ["ahead"]
    written = json.loads((bom / "bom" / "v1.4.1.json").read_text())
    assert written["python"]["renglo-lib"] == "1.2.4"
    assert written["platform"] == "0.1.2"


def test_cli_check_exits_zero_with_warnings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, bom = _workspace(tmp_path, "0.2.1")
    save(root, _state())
    code = main(
        ["--json", "--workspace", str(root), "bom", "check", "--bom", str(bom)]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["warning_count"] == 1
    assert payload["platform_warnings"][0]["status"] == "stale"
    assert payload["packages"][0]["requires"] == "0.1.4"
    assert not (bom / "bom" / "v1.4.1.json").exists()
