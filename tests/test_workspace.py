from __future__ import annotations

from pathlib import Path

from gitconvoy import gitutil
from gitconvoy.workspace import FEATURE_SKIP_OPS, discover_repos, feature_repos

from conftest import init_repo


def test_feature_repos_includes_tenant_ops_excludes_tooling_and_bom(
    workspace: Path,
) -> None:
    init_repo(workspace / "ops" / "bootstrap")
    init_repo(workspace / "ops" / "stanley-bom", develop=False)
    init_repo(workspace / "ops" / "stanley-wl")
    init_repo(workspace / "ops" / "publisher")
    ids = {repo.id for repo in feature_repos(workspace)}
    assert "bootstrap" in ids
    assert "stanley-wl" in ids
    assert "stanley-bom" not in ids
    assert "publisher" not in ids
    assert "renglo-lib" in ids
    assert "schd" in ids


def test_feature_skip_ops_are_still_discovered(workspace: Path) -> None:
    init_repo(workspace / "ops" / "publisher")
    discovered = {repo.id for repo in discover_repos(workspace)}
    assert "publisher" in discovered
    assert "publisher" in FEATURE_SKIP_OPS


def test_integration_branch_prefers_develop_else_main(workspace: Path) -> None:
    bootstrap = workspace / "ops" / "bootstrap"
    init_repo(bootstrap)
    assert gitutil.integration_branch(bootstrap) == "develop"

    bom = workspace / "ops" / "stanley-bom"
    init_repo(bom, develop=False)
    assert gitutil.integration_branch(bom) == "main"
