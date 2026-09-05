from __future__ import annotations

from pathlib import Path

import pytest

from gitconvoy import gitutil
from gitconvoy import membership
from gitconvoy.errors import GitConvoyError
from gitconvoy.workspace import (
    aux_repos,
    discover_repos,
    feature_repos,
    find_workspace,
    product_repos,
)

from conftest import init_repo


def _mark_aux(path: Path) -> None:
    (path / "gitconvoy.toml").write_text('role = "aux"\n')


def _mark_bom(path: Path) -> None:
    (path / "gitconvoy.toml").write_text('role = "bom"\n')


def test_feature_repos_excludes_aux_and_bom_when_membership_refreshed(
    workspace: Path,
) -> None:
    bootstrap = init_repo(workspace / "ops" / "bootstrap")
    bom = init_repo(workspace / "ops" / "stanley-bom", develop=False)
    init_repo(workspace / "ops" / "stanley-wl")
    publisher = init_repo(workspace / "ops" / "publisher")
    _mark_aux(bootstrap)
    _mark_aux(publisher)
    _mark_bom(bom)
    membership.refresh_membership(workspace, discover_repos(workspace))

    ids = {repo.id for repo in feature_repos(workspace)}
    assert "bootstrap" not in ids
    assert "stanley-wl" in ids
    assert "stanley-bom" not in ids
    assert "publisher" not in ids
    assert "renglo-lib" in ids
    assert "schd" in ids

    aux_ids = {repo.id for repo in aux_repos(workspace)}
    assert aux_ids == {"bootstrap", "publisher"}


def test_without_aux_toml_unmarked_ops_are_product(workspace: Path) -> None:
    init_repo(workspace / "ops" / "publisher")
    discovered = {repo.id for repo in discover_repos(workspace)}
    assert "publisher" in discovered
    assert "publisher" in {repo.id for repo in product_repos(workspace)}
    assert "publisher" not in {repo.id for repo in aux_repos(workspace)}


def test_bom_id_fallback_without_membership(workspace: Path) -> None:
    init_repo(workspace / "ops" / "stanley-bom", develop=False)
    ids = {repo.id for repo in feature_repos(workspace)}
    assert "stanley-bom" not in ids


def _raise_cwd(cls: type[Path]) -> Path:
    raise FileNotFoundError(2, "No such file or directory")


def test_find_workspace_falls_back_to_pwd(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "dev").mkdir()
    (tmp_path / "extensions").mkdir()
    monkeypatch.setattr(
        "gitconvoy.workspace.Path.cwd",
        classmethod(_raise_cwd),
    )
    monkeypatch.setenv("PWD", str(tmp_path))
    assert find_workspace() == tmp_path.resolve()


def test_find_workspace_missing_cwd_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        "gitconvoy.workspace.Path.cwd",
        classmethod(_raise_cwd),
    )
    monkeypatch.delenv("PWD", raising=False)
    with pytest.raises(GitConvoyError, match="current directory no longer exists"):
        find_workspace()


def test_integration_branch_prefers_develop_else_main(workspace: Path) -> None:
    bootstrap = workspace / "ops" / "bootstrap"
    init_repo(bootstrap)
    assert gitutil.integration_branch(bootstrap) == "develop"

    bom = workspace / "ops" / "stanley-bom"
    init_repo(bom, develop=False)
    assert gitutil.integration_branch(bom) == "main"
