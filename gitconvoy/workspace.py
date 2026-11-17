from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gitconvoy.errors import GitConvoyError
from gitconvoy import membership
from gitconvoy.state import STATE_DIRNAME, state_path

SCAN_ROOTS = ("console", "dev", "extensions", "ops")
# Workspace-root siblings that are containers, not single-repo clones.
ROOT_CONTAINER_NAMES = frozenset(SCAN_ROOTS)
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


def _is_flat_workspace(path: Path) -> bool:
    """A checkout of sibling clones, with no dev/ or extensions/ containers."""
    return not (path / "dev").is_dir() and not (path / "extensions").is_dir()


def _is_repo_root(path: Path) -> bool:
    """True only for a clone of its own, not a folder inside a parent work tree."""
    return path.is_dir() and (path / ".git").exists()


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


def _kind_for_root_role(role: str) -> str:
    if role in {"ops", "bom", "registry"}:
        return "ops"
    return "core"


def discover_repos(workspace: Path) -> list[Repo]:
    found: list[Repo] = []
    seen: set[Path] = set()
    console = workspace / "console"
    if _is_repo_root(console):
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
            if not _is_repo_root(child):
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
    flat = _is_flat_workspace(workspace)
    if flat and _is_repo_root(workspace):
        resolved = workspace.resolve()
        role = membership.repo_role_if_valid(workspace)
        if resolved not in seen and role is not None:
            seen.add(resolved)
            found.append(
                Repo(
                    id=workspace.name,
                    path=resolved,
                    rel=".",
                    kind=_kind_for_root_role(role),
                )
            )
    for child in sorted(workspace.iterdir()):
        if not child.is_dir():
            continue
        if child.name in ROOT_CONTAINER_NAMES or child.name in SKIP_DIR_NAMES:
            continue
        if not _is_repo_root(child):
            continue
        resolved = child.resolve()
        if resolved in seen:
            continue
        role = membership.repo_role_if_valid(child)
        if role is None:
            continue
        # Standard installations keep product clones under dev/ and extensions/.
        # A root clone joins only when it is ops, unless this checkout is flat.
        if role != "ops" and not flat:
            continue
        seen.add(resolved)
        found.append(
            Repo(
                id=child.name,
                path=resolved,
                rel=str(child.relative_to(workspace)),
                kind=_kind_for_root_role(role),
            )
        )
    return found


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
