from __future__ import annotations

from pathlib import Path

from gitconvoy.workflows import repo_publishes_on_tag, repo_registry_ready, tag_push_workflows, triggers_on_version_tag


def _write(repo: Path, name: str, body: str) -> Path:
    wf = repo / ".github" / "workflows" / name
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(body, encoding="utf-8")
    return wf


def test_triggers_on_version_tag_publish_extension(tmp_path: Path) -> None:
    text = """
name: Publish extension
on:
  push:
    tags:
      - "v*"
"""
    repo = tmp_path / "ext"
    repo.mkdir()
    path = _write(repo, "publish-extension.yml", text)
    assert triggers_on_version_tag(path) is True
    assert tag_push_workflows(repo) == ["publish-extension.yml"]
    assert repo_publishes_on_tag(repo) is True


def test_deploy_on_main_not_version_tag(tmp_path: Path) -> None:
    repo = tmp_path / "bom"
    repo.mkdir()
    _write(
        repo,
        "deploy_console.yml",
        """
on:
  push:
    branches:
      - main
    paths:
      - "bom/**"
""",
    )
    assert tag_push_workflows(repo) == []


def test_multiple_tag_workflows(tmp_path: Path) -> None:
    repo = tmp_path / "multi"
    repo.mkdir()
    _write(
        repo,
        "publish-python.yml",
        "on:\n  push:\n    tags:\n      - 'v*'\n",
    )
    _write(
        repo,
        "publish-npm.yml",
        "on:\n  push:\n    tags:\n      - v*\n",
    )
    assert tag_push_workflows(repo) == ["publish-npm.yml", "publish-python.yml"]


def test_missing_repo_is_unknown() -> None:
    assert repo_publishes_on_tag(Path("/nonexistent/repo")) is None
    assert repo_registry_ready(Path("/nonexistent/repo"), "claw") is None


def test_console_workflow_without_scoped_name_is_not_registry_ready(tmp_path: Path) -> None:
    repo = tmp_path / "console"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{"name":"console","version":"0.0.1","private":true}\n',
        encoding="utf-8",
    )
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "publish-npm.yml").write_text(
        "on:\n  push:\n    tags:\n      - 'v*'\n",
        encoding="utf-8",
    )
    assert repo_publishes_on_tag(repo) is True
    assert repo_registry_ready(repo, "console") is False
