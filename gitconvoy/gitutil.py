from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from gitconvoy.errors import GitConvoyError


def git_bin() -> str:
    path = shutil.which("git")
    if not path:
        raise GitConvoyError("git is not on PATH")
    return path


def run(
    repo: Path,
    *args: str,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = [git_bin(), "-C", str(repo), *args]
    result = subprocess.run(
        cmd,
        text=True,
        capture_output=capture,
        check=False,
    )
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise GitConvoyError(f"git {' '.join(args)} failed in {repo}: {err}")
    return result


def capture(repo: Path, *args: str) -> str:
    return run(repo, *args).stdout.strip()


def is_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (path / ".git").exists() or run(
        path, "rev-parse", "--is-inside-work-tree", check=False
    ).returncode == 0


def is_dirty(repo: Path) -> bool:
    return bool(capture(repo, "status", "--porcelain"))


def status_porcelain(repo: Path) -> str:
    return capture(repo, "status", "--porcelain")


def porcelain_paths(porcelain: str) -> list[str]:
    files: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.strip().strip('"'))
    return files


def diff_stat(repo: Path) -> str:
    return capture(repo, "diff", "--stat", "HEAD")


def diff_patch(repo: Path) -> str:
    return capture(repo, "diff", "HEAD")


def commit_all(repo: Path, message: str) -> str:
    run(repo, "add", "-A")
    result = run(repo, "commit", "-m", message, check=False)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise GitConvoyError(f"git commit failed in {repo}: {err}")
    return capture(repo, "rev-parse", "--short", "HEAD")


def current_branch(repo: Path) -> str:
    result = run(repo, "branch", "--show-current", check=False)
    name = (result.stdout or "").strip()
    if not name:
        return "HEAD"
    return name


def rev_parse(repo: Path, ref: str) -> str | None:
    result = run(repo, "rev-parse", "--verify", "--quiet", ref, check=False)
    sha = (result.stdout or "").strip()
    return sha or None


def fetch(repo: Path) -> None:
    run(repo, "fetch", "origin", "--tags", "--prune", check=False)


def checkout(repo: Path, branch: str, create: bool = False, force: bool = False) -> None:
    if create:
        run(repo, "checkout", "-b", branch)
        return
    if force:
        run(repo, "checkout", "-f", branch)
        return
    run(repo, "checkout", branch)


def checkout_branch(repo: Path, branch: str) -> None:
    """Check out branch, creating it from HEAD if it does not exist locally."""
    if rev_parse(repo, f"refs/heads/{branch}"):
        checkout(repo, branch)
        return
    if rev_parse(repo, f"refs/remotes/origin/{branch}"):
        run(repo, "checkout", "-B", branch, f"origin/{branch}")
        return
    checkout(repo, branch, create=True)


def merge(repo: Path, ref: str) -> subprocess.CompletedProcess[str]:
    return run(repo, "merge", "--no-edit", ref, check=False)


def push(repo: Path, *args: str) -> None:
    run(repo, "push", *args)


def reset_hard(repo: Path, ref: str) -> None:
    run(repo, "reset", "--hard", ref)


def has_local_branch(repo: Path, branch: str) -> bool:
    return bool(rev_parse(repo, f"refs/heads/{branch}"))


def has_remote_branch(repo: Path, branch: str) -> bool:
    return bool(rev_parse(repo, f"refs/remotes/origin/{branch}"))


def delete_branch(repo: Path, branch: str) -> None:
    run(repo, "branch", "-D", branch)


def delete_remote_branch(repo: Path, branch: str) -> None:
    run(repo, "push", "origin", "--delete", branch)


def clean_untracked(repo: Path) -> None:
    run(repo, "clean", "-fd")


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = run(
        repo, "merge-base", "--is-ancestor", ancestor, descendant, check=False
    )
    return result.returncode == 0


def ahead_of(repo: Path, local: str, remote: str) -> bool:
    if not rev_parse(repo, local) or not rev_parse(repo, remote):
        return False
    if capture(repo, "rev-parse", local) == capture(repo, "rev-parse", remote):
        return False
    return is_ancestor(repo, remote, local)


def last_stable_tag(repo: Path) -> str | None:
    result = run(repo, "tag", "-l", "v*", check=False)
    tags = []
    for line in (result.stdout or "").splitlines():
        name = line.strip()
        if not name:
            continue
        body = name[1:] if name.startswith("v") else name
        if "rc" in body.lower() or "-" in body:
            continue
        parts = body.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        tags.append((tuple(int(p) for p in parts), name))
    if not tags:
        return None
    tags.sort()
    return tags[-1][1]


def develop_ahead_of_stable(repo: Path) -> bool:
    fetch(repo)
    develop = rev_parse(repo, "origin/develop") or rev_parse(repo, "develop")
    if not develop:
        return False
    tag = last_stable_tag(repo)
    if not tag:
        return True
    if not rev_parse(repo, tag):
        return True
    return ahead_of(repo, develop, tag) or (
        capture(repo, "rev-parse", develop) != capture(repo, "rev-parse", tag)
        and is_ancestor(repo, tag, develop)
    )


def origin_url(repo: Path) -> str | None:
    result = run(repo, "remote", "get-url", "origin", check=False)
    url = (result.stdout or "").strip()
    return url or None


def github_slug(repo: Path) -> str | None:
    url = origin_url(repo)
    if not url:
        return None
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    if url.startswith("git@github.com:"):
        return url[len("git@github.com:") :]
    if "github.com/" in url:
        return url.split("github.com/", 1)[1]
    return None


def gh_bin() -> str | None:
    return shutil.which("gh")
