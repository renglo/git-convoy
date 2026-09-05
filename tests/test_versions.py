from pathlib import Path

import pytest

from gitconvoy.state import TrainRepo
from gitconvoy.adopt import _python_package_names
from gitconvoy.versions import (
    bump,
    drop_rc,
    next_rc,
    parse,
    read_npm_package_name,
    read_python_package_name,
    with_rc,
)


def test_bump_patch() -> None:
    assert bump("1.2.3", "patch") == "1.2.4"


def test_bump_minor_resets_patch() -> None:
    assert bump("1.2.3", "minor") == "1.3.0"


def test_rc_formats() -> None:
    pep, npm = with_rc("1.2.4", 1)
    assert pep == "1.2.4rc1"
    assert npm == "1.2.4-rc.1"


def test_next_rc() -> None:
    pep, npm = next_rc("1.2.4rc1")
    assert pep == "1.2.4rc2"
    assert npm == "1.2.4-rc.2"


def test_drop_rc_does_not_increment() -> None:
    pep, npm = drop_rc("1.2.4rc2")
    assert pep == "1.2.4"
    assert npm == "1.2.4"


def test_parse_npm_rc() -> None:
    assert parse("1.2.4-rc.3") == (1, 2, 4, 3)


def test_read_npm_package_name_prefers_ui(tmp_path: Path) -> None:
    repo = tmp_path / "ext"
    (repo / "ui").mkdir(parents=True)
    (repo / "ui" / "package.json").write_text('{"name":"@renglo/schd","version":"1.0.0"}\n')
    (repo / "package.json").write_text('{"name":"ignored","version":"0.0.1"}\n')
    assert read_npm_package_name(repo) == "@renglo/schd"


def test_read_npm_package_name_root(tmp_path: Path) -> None:
    repo = tmp_path / "wl"
    repo.mkdir()
    (repo / "package.json").write_text('{"name":"@stanley/wl","version":"0.0.1"}\n')
    assert read_npm_package_name(repo) == "@stanley/wl"


def test_read_python_package_name_root(tmp_path: Path) -> None:
    repo = tmp_path / "lib"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "renglo-lib"\nversion = "1.0.0"\n'
        'authors = [{name = "Team"}]\n'
    )
    assert read_python_package_name(repo) == "renglo-lib"


def test_read_python_package_name_under_package(tmp_path: Path) -> None:
    repo = tmp_path / "lab"
    (repo / "package").mkdir(parents=True)
    (repo / "package" / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools"]\n\n'
        '[project]\nname = "arbitium-lab"\nversion = "0.0.4rc1"\n'
    )
    assert read_python_package_name(repo) == "arbitium-lab"


def test_python_package_names_prefers_pyproject(tmp_path: Path) -> None:
    workspace = tmp_path
    root = workspace / "extensions" / "arbitiumlab"
    (root / "package").mkdir(parents=True)
    (root / "package" / "pyproject.toml").write_text(
        '[project]\nname = "arbitium-lab"\nversion = "0.0.4rc1"\n'
    )
    repo = TrainRepo(id="arbitiumlab", path="extensions/arbitiumlab")
    assert _python_package_names(repo, workspace) == ["arbitium-lab"]


def test_python_package_names_requires_name(tmp_path: Path) -> None:
    from gitconvoy.errors import GitConvoyError

    workspace = tmp_path
    root = workspace / "extensions" / "orphan"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    repo = TrainRepo(id="orphan", path="extensions/orphan")
    with pytest.raises(GitConvoyError, match="missing \\[project\\] name"):
        _python_package_names(repo, workspace)
    assert _python_package_names(repo, workspace, required=False) == []
