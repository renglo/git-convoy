from __future__ import annotations

from pathlib import Path

from gitconvoy import ops_cycle
from gitconvoy.state import State, load

from conftest import git, init_repo


def _ops_repo(path: Path) -> Path:
    init_repo(path)
    (path / "gitconvoy.toml").write_text(
        'role = "ops"\nversion = "python"\npublish = "python-wheel"\npin = "registry"\n'
    )
    git(path, "add", "-A")
    git(path, "commit", "-m", "mark ops")
    return path


def test_cut_takes_every_ahead_ops_repo_and_tag_rc_pins_platform(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "dev").mkdir()
    (root / "extensions").mkdir()
    (root / "ops").mkdir()
    product = init_repo(root / "dev" / "renglo-lib")
    (product / "feature.txt").write_text("product\n")
    git(product, "add", "-A")
    git(product, "commit", "-m", "product work")
    _ops_repo(root / "ops" / "git-convoy")
    renglo = _ops_repo(root / "ops" / "renglo-ops")
    bom = init_repo(root / "ops" / "apollo-bom", develop=False)
    (bom / "renglo.yaml").write_text("name: apollo1\nplatform: 0.1.0\n")
    git(bom, "add", "-A")
    git(bom, "commit", "-m", "bom")

    state = State()
    cut = ops_cycle.cut(root, state, "2026-W40")
    ids = {row["id"] for row in cut["repos"]}
    assert ids == {"git-convoy", "renglo-ops"}
    assert "renglo-lib" not in ids
    assert git(renglo, "branch", "--show-current").stdout.strip() == "release/2026-W40"

    tagged = ops_cycle.tag_rc(root, load(root), push=False)
    tags = {row["id"]: row["tag"] for row in tagged["repos"]}
    assert set(tags) == {"git-convoy", "renglo-ops"}
    assert tags["renglo-ops"].startswith("v")
    version = next(row["version"] for row in tagged["repos"] if row["id"] == "renglo-ops")
    assert tagged["pin"]["status"] == "updated"
    assert f"platform: {version}" in (bom / "renglo.yaml").read_text()
