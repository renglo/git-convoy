from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gitconvoy.errors import GitConvoyError
from gitconvoy import membership
from gitconvoy.state import STATE_DIRNAME, state_path

# Directory names that are never clones and are not worth walking.
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
    kind: str  # console | core | extension | ops | product | bom | incubating | registry


def is_bom_repo_id(repo_id: str, workspace: Path | None = None) -> bool:
    """BOM repos: explicit .gitconvoy/ops.toml [bom], else *-bom id convention."""
    if workspace is not None:
        return membership.is_bom_id(workspace, repo_id)
    return repo_id.endswith("-bom")


def find_workspace(start: Path | None = None) -> Path:
    here = _resolve_start(start)
    for candidate in [here, *here.parents]:
        if state_path(candidate).exists():
            return candidate
        if _looks_like_workspace(candidate):
            return candidate
    # A fresh clone of this tool has neither state nor dev/extensions.
    # The workspace is the parent that holds the sibling clones.
    for candidate in [here, *here.parents]:
        if _contains_repo_root(candidate):
            return candidate
    return here


def _resolve_start(start: Path | None) -> Path:
    base = start if start is not None else _cwd()
    try:
        return base.resolve()
    except FileNotFoundError:
        if base.is_absolute() and base.exists():
            return base
        raise GitConvoyError(_MISSING_CWD) from None


def _cwd() -> Path:
    try:
        return Path.cwd()
    except FileNotFoundError:
        pwd = os.environ.get("PWD", "")
        candidate = Path(pwd) if pwd else None
        if candidate is not None and candidate.exists():
            return candidate
        raise GitConvoyError(_MISSING_CWD) from None


_MISSING_CWD = (
    "current directory no longer exists; cd to the workspace root or pass --workspace"
)


def _looks_like_workspace(path: Path) -> bool:
    return (path / "dev").is_dir() and (path / "extensions").is_dir()


def _is_repo_root(path: Path) -> bool:
    """True when ``path`` is a clone, not a folder inside one.

    ``git rev-parse --is-inside-work-tree`` is true for every subdirectory of a
    clone, so discovery keys off a ``.git`` entry (directory, or file for a
    linked worktree).
    """
    git_entry = path / ".git"
    return git_entry.is_dir() or git_entry.is_file()


def _contains_repo_root(path: Path) -> bool:
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    for child in children:
        if child.name in SKIP_DIR_NAMES or child.name.startswith("."):
            continue
        if _is_repo_root(child):
            return True
    return False


def _kind_for(rel: str, role: str | None) -> str:
    """Display kind. Classic renglo folders keep their old names; other clones follow role."""
    parts = Path(rel).parts
    if parts == ("console",):
        return "console"
    if len(parts) >= 2 and parts[0] == "dev":
        return "core"
    if len(parts) >= 2 and parts[0] == "extensions":
        return "extension"
    if len(parts) >= 2 and parts[0] == "ops":
        return "ops"
    if role in {"ops", "bom", "incubating", "registry"}:
        return role
    return "product"


def discover_repos(workspace: Path) -> list[Repo]:
    """Every git clone under ``workspace``, at any depth.

    The workspace directory itself is not a participant. Once a directory has
    its own ``.git``, its contents are not scanned. Hidden directories and
    ``SKIP_DIR_NAMES`` (``node_modules``, virtualenvs, build output) are not
    entered. Two clones with the same folder name get ids of their relative
    paths (``gadgets/air``); unique names stay the folder name.
    """
    root = workspace.resolve()
    found: list[tuple[Path, str, str | None]] = []
    seen: set[Path] = set()
    visited: set[Path] = set()

    def walk(directory: Path) -> None:
        try:
            resolved_dir = directory.resolve()
        except OSError:
            return
        if resolved_dir in visited:
            return
        try:
            resolved_dir.relative_to(root)
        except ValueError:
            return
        visited.add(resolved_dir)
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            return
        for child in children:
            if child.name in SKIP_DIR_NAMES or child.name.startswith("."):
                continue
            if not child.is_dir():
                continue
            try:
                resolved = child.resolve()
            except OSError:
                continue
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            if resolved == root or resolved in seen:
                continue
            if _is_repo_root(child):
                seen.add(resolved)
                try:
                    rel = str(child.relative_to(workspace))
                except ValueError:
                    rel = str(resolved.relative_to(root))
                found.append((resolved, rel, membership.repo_role_if_valid(child)))
                continue
            walk(child)

    walk(workspace)
    return _repos_with_ids(found)


def _repos_with_ids(found: list[tuple[Path, str, str | None]]) -> list[Repo]:
    counts: dict[str, int] = {}
    for path, _rel, _role in found:
        counts[path.name] = counts.get(path.name, 0) + 1
    repos: list[Repo] = []
    for path, rel, role in sorted(found, key=lambda item: item[1]):
        repo_id = path.name if counts[path.name] == 1 else rel
        repos.append(
            Repo(
                id=repo_id,
                path=path,
                rel=rel,
                kind=_kind_for(rel, role),
            )
        )
    return repos


def product_repos(workspace: Path) -> list[Repo]:
    """Repos eligible for features, trains, and hotfixes (not ops, not bom)."""
    rows: list[Repo] = []
    for repo in discover_repos(workspace):
        role = membership.repo_role_if_valid(repo.path)
        if role != "product":
            continue
        if is_bom_repo_id(repo.id, workspace):
            continue
        rows.append(repo)
    return rows


def feature_repos(workspace: Path) -> list[Repo]:
    """Same as product_repos — product cycle-1 participants."""
    return product_repos(workspace)


def ops_repos(workspace: Path) -> list[Repo]:
    """Repos whose gitconvoy.toml says role = ops (not the local ops.toml cache)."""
    return [
        repo
        for repo in discover_repos(workspace)
        if membership.repo_role_if_valid(repo.path) == "ops"
    ]


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
