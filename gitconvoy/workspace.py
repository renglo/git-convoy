from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gitconvoy.errors import GitConvoyError
from gitconvoy.gitutil import is_git_repo
from gitconvoy import membership
from gitconvoy.state import STATE_DIRNAME, state_path

SCAN_ROOTS = ("console", "dev", "extensions", "ops")
SKIP_DIR_NAMES = {
    ".git",
    ".gitconvoy",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "gitconvoy-venv",
    "dist",
    "build",
    ".pytest_cache",
}

MERGE_RANK = {
    "renglo-lib": 0,
    "renglo-api": 1,
    "console": 2,
}


@dataclass(frozen=True)
class Repo:
    id: str
    path: Path
    rel: str
    kind: str  # console | core | extension | ops


def is_bom_repo_id(repo_id: str, workspace: Path | None = None) -> bool:
    """BOM repos: explicit .gitconvoy/aux.toml [bom], else *-bom id convention."""
    if workspace is not None:
        return membership.is_bom_id(workspace, repo_id)
    return repo_id.endswith("-bom")


def find_workspace(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if state_path(candidate).exists():
            return candidate
        if _looks_like_workspace(candidate):
            return candidate
    return here


def _looks_like_workspace(path: Path) -> bool:
    return (path / "dev").is_dir() and (path / "extensions").is_dir()


def discover_repos(workspace: Path) -> list[Repo]:
    found: list[Repo] = []
    seen: set[Path] = set()
    console = workspace / "console"
    if is_git_repo(console):
        found.append(Repo("console", console.resolve(), "console", "console"))
        seen.add(console.resolve())
    for kind, folder in (
        ("core", workspace / "dev"),
        ("extension", workspace / "extensions"),
        ("ops", workspace / "ops"),
    ):
        if not folder.is_dir():
            continue
        for child in sorted(folder.iterdir()):
            if child.name in SKIP_DIR_NAMES or not child.is_dir():
                continue
            if not is_git_repo(child):
                continue
            resolved = child.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(
                Repo(
                    id=child.name,
                    path=resolved,
                    rel=str(child.relative_to(workspace)),
                    kind=kind,
                )
            )
    return found


def product_repos(workspace: Path) -> list[Repo]:
    """Repos eligible for features, trains, and hotfixes (not aux, not bom)."""
    return [
        repo
        for repo in discover_repos(workspace)
        if not membership.is_aux_id(workspace, repo.id)
        and not is_bom_repo_id(repo.id, workspace)
    ]


def feature_repos(workspace: Path) -> list[Repo]:
    """Same as product_repos — product cycle-1 participants."""
    return product_repos(workspace)


def aux_repos(workspace: Path) -> list[Repo]:
    """Repos listed as aux in local membership (from gitconvoy.toml markers via init)."""
    allowed = set(membership.load_membership(workspace)["aux"])
    return [repo for repo in discover_repos(workspace) if repo.id in allowed]


def bom_repos(workspace: Path) -> list[Repo]:
    return [
        repo
        for repo in discover_repos(workspace)
        if is_bom_repo_id(repo.id, workspace)
    ]


def require_repo(repos: list[Repo], repo_id: str) -> Repo:
    for repo in repos:
        if repo.id == repo_id or repo.rel == repo_id:
            return repo
    raise GitConvoyError(f"repo not in workspace: {repo_id}")


def merge_sort(repo_ids: list[str]) -> list[str]:
    return sorted(repo_ids, key=lambda name: (MERGE_RANK.get(name, 3), name))


def ensure_gitignore(workspace: Path) -> Path:
    path = workspace / ".gitignore"
    line = f"{STATE_DIRNAME}/"
    if path.exists():
        text = path.read_text()
        if line not in text.splitlines() and STATE_DIRNAME not in text:
            if text and not text.endswith("\n"):
                text += "\n"
            path.write_text(text + line + "\n")
    else:
        path.write_text(line + "\n")
    return path
