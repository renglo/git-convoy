from __future__ import annotations

import json
import re
from pathlib import Path

WORKFLOWS_DIR = Path(".github") / "workflows"

# Matches publisher templates: tags: / - "v*" / - 'v*' (with optional quotes).
_TAG_PUSH_PATTERN = re.compile(
    r"tags\s*:\s*(?:\n\s*-\s*|[\[\s]*['\"]?)(?:v\*|['\"]v\*['\"])",
    re.IGNORECASE | re.MULTILINE,
)


def triggers_on_version_tag(path: Path) -> bool:
    """True when a workflow file runs on push of v* version tags."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if "push" not in text or "tags" not in text:
        return False
    return bool(_TAG_PUSH_PATTERN.search(text))


def tag_push_workflows(repo: Path) -> list[str]:
    """Workflow filenames under .github/workflows that trigger on v* tag push."""
    wf_dir = repo / WORKFLOWS_DIR
    if not wf_dir.is_dir():
        return []
    names: list[str] = []
    for path in sorted(wf_dir.iterdir()):
        if path.suffix not in {".yml", ".yaml"} or not path.is_file():
            continue
        if triggers_on_version_tag(path):
            names.append(path.name)
    return names


def repo_publishes_on_tag(repo: Path) -> bool | None:
    """True/false when the repo is present locally; None if path missing (unknown)."""
    if not repo.is_dir():
        return None
    return bool(tag_push_workflows(repo))


def repo_registry_ready(repo: Path, repo_id: str) -> bool | None:
    """True when tag-publish workflow exists and the repo can publish packages.

    Console needs package.json name ``@renglo/console`` (workflow alone is not enough).
    None when the repo directory is missing (unknown).
    """
    if not repo.is_dir():
        return None
    if not tag_push_workflows(repo):
        return False
    if repo_id == "console":
        pkg = repo / "package.json"
        if not pkg.is_file():
            return False
        try:
            name = json.loads(pkg.read_text(encoding="utf-8")).get("name", "")
        except (OSError, json.JSONDecodeError):
            return False
        return name == "@renglo/console"
    return True
