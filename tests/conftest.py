from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        text=True,
        capture_output=True,
    )


def init_repo(path: Path, *, develop: bool = True) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("hello\n")
    (path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.0"\n')
    git(path, "add", "-A")
    git(path, "commit", "-m", "init")
    if develop:
        git(path, "checkout", "-b", "develop")
    return path


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "dev").mkdir()
    (root / "extensions").mkdir()
    init_repo(root / "dev" / "renglo-lib")
    init_repo(root / "extensions" / "schd")
    return root
