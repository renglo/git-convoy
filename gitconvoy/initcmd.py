from __future__ import annotations

from pathlib import Path

from gitconvoy import membership
from gitconvoy.skill_text import SKILL_MARKDOWN
from gitconvoy.state import State, save
from gitconvoy.workspace import discover_repos, ensure_gitignore


def init(workspace: Path, state: State) -> dict:
    path = save(workspace, state)
    gitignore = ensure_gitignore(workspace)
    skill = workspace / ".cursor" / "skills" / "gitconvoy" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(SKILL_MARKDOWN)
    leftover = workspace / ".cursor" / "skills" / "releaser"
    leftover_skill = leftover / "SKILL.md"
    if leftover_skill.exists():
        leftover_skill.unlink()
    if leftover.is_dir():
        try:
            leftover.rmdir()
        except OSError:
            pass
    repos = discover_repos(workspace)
    membership_info = membership.refresh_membership(workspace, repos)
    return {
        "ok": True,
        "workspace": str(workspace),
        "state": str(path),
        "gitignore": str(gitignore),
        "skill": str(skill),
        "membership": membership_info["path"],
        "aux": membership_info["aux"],
        "bom": membership_info["bom"],
        "repo_count": len(repos),
        "repos": [{"id": repo.id, "path": repo.rel, "kind": repo.kind} for repo in repos],
    }
