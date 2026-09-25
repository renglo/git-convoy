from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gitconvoy import gitutil
from gitconvoy import membership
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State
from gitconvoy.workspace import Repo, discover_repos, is_bom_repo_id

_RETRY_WORKSPACE = "git convoy sync"
_RETRY_DEVELOP = "git convoy sync develop"


@dataclass(frozen=True)
class DevelopSyncEntry:
    id: str
    rel: str
    ref: str | None = None


def stable_ref(repo_path: Path) -> str:
    tag = gitutil.last_stable_tag(repo_path)
    if tag:
        return tag
    if gitutil.rev_parse(repo_path, "origin/main"):
        return "origin/main"
    return "main"


def sync_develop_from_ref(
    repo_path: Path,
    *,
    repo_id: str,
    push: bool,
    ref: str | None = None,
    retry_hint: str = _RETRY_DEVELOP,
) -> dict:
    """Merge tagged main (or a stable tag) into develop.

    Fetches first, creates ``develop`` from ``main`` when it is missing (product
    and ops repos always have an integration branch), updates local ``main``
    without leaving you on it, then checks out ``develop``. On merge conflict
    the merge is aborted so the repo is not left mid-merge.
    """
    gitutil.fetch(repo_path)
    ensured = gitutil.ensure_develop(repo_path, push=push)
    if ensured.get("status") == "failed":
        raise GitConvoyError(
            f"{repo_id}: cannot create develop"
            + (f" ({ensured.get('error')})" if ensured.get("error") else "")
            + f"; {retry_hint}"
        )
    has_develop = gitutil.has_local_branch(
        repo_path, "develop"
    ) or gitutil.has_remote_branch(repo_path, "develop")
    if not has_develop:
        return {
            "status": "skipped",
            "synced": False,
            "ref": ref or stable_ref(repo_path),
            "branch": gitutil.current_branch(repo_path),
        }
    main_ff = gitutil.fast_forward_branch(repo_path, "main")
    if main_ff == "diverged":
        raise GitConvoyError(
            f"{repo_id}: cannot fast-forward main from origin; "
            f"fix main, then {retry_hint}"
        )
    merge_ref = ref or stable_ref(repo_path)
    if merge_ref not in {"main", "origin/main"} and not gitutil.rev_parse(
        repo_path, merge_ref
    ):
        raise GitConvoyError(
            f"{repo_id}: missing {merge_ref}; fetch tags, then {retry_hint}"
        )
    gitutil.checkout_branch(repo_path, "develop")
    if gitutil.rev_parse(repo_path, "origin/develop"):
        pulled = gitutil.run(
            repo_path, "merge", "--ff-only", "origin/develop", check=False
        )
        if pulled.returncode != 0:
            raise GitConvoyError(
                f"{repo_id}: cannot fast-forward develop from origin; "
                f"reconcile develop, then {retry_hint}"
            )
    if gitutil.has_tracked_changes(repo_path):
        raise GitConvoyError(
            f"{repo_id} develop is dirty; commit or stash, then {retry_hint}"
        )
    already = gitutil.is_ancestor(repo_path, merge_ref, "develop")
    if not already:
        merged = gitutil.merge(repo_path, merge_ref)
        if merged.returncode != 0:
            gitutil.run(repo_path, "merge", "--abort", check=False)
            raise GitConvoyError(
                f"{repo_id}: merge {merge_ref} into develop failed "
                "(merge aborted, repo left clean). "
                f"resolve on develop, then {retry_hint}"
            )
        status = "merged"
    else:
        status = "already"
    if push and gitutil.origin_url(repo_path) and gitutil.rev_parse(
        repo_path, "origin/develop"
    ):
        gitutil.push(repo_path, "origin", "develop")
    return {
        "status": status,
        "synced": True,
        "ref": merge_ref,
        "branch": "develop",
        "develop_created": bool(ensured.get("created")),
    }


def sync_repos_develop(
    workspace: Path,
    entries: list[DevelopSyncEntry],
    *,
    push: bool,
    retry_hint: str,
) -> dict:
    """Sync develop from stable/main for each entry. Continues past per-repo failures."""
    rows: list[dict] = []
    failed: list[str] = []
    for entry in entries:
        repo_path = workspace / entry.rel
        item: dict = {
            "id": entry.id,
            "path": entry.rel,
            "status": "failed",
            "synced": False,
        }
        try:
            result = sync_develop_from_ref(
                repo_path,
                repo_id=entry.id,
                push=push,
                ref=entry.ref,
                retry_hint=retry_hint,
            )
            item["status"] = result["status"]
            item["synced"] = result["synced"]
            item["ref"] = result.get("ref")
            item["branch"] = result.get("branch")
            item["develop_created"] = result.get("develop_created")
        except GitConvoyError as exc:
            item["error"] = exc.message
            failed.append(entry.id)
        rows.append(item)
    data: dict = {
        "ok": not failed,
        "repos": rows,
        "failed": failed,
    }
    if failed:
        data["note"] = (
            f"develop sync failed in: {', '.join(failed)}. "
            f"resolve, then {retry_hint}"
        )
    return data


def sync_product_repos(
    workspace: Path,
    *,
    repo_ids: list[str] | None = None,
    push: bool = True,
    retry_hint: str = _RETRY_DEVELOP,
) -> dict:
    """Merge latest stable tag (or main) into develop for product repos."""
    from gitconvoy.workspace import product_repos, require_repo

    repos = product_repos(workspace)
    if repo_ids:
        chosen = [require_repo(repos, repo_id) for repo_id in repo_ids]
    else:
        chosen = sorted(repos, key=lambda row: row.id)
    entries = [DevelopSyncEntry(id=repo.id, rel=repo.rel) for repo in chosen]
    return sync_repos_develop(
        workspace, entries, push=push, retry_hint=retry_hint
    )


_DONE_STATUSES = frozenset({"merged", "pulled", "already"})


def sync_workspace(
    workspace: Path,
    state: State,
    *,
    push: bool = True,
) -> dict:
    """Bring latest integration commits into every clone, one repo at a time.

    Clean repos update in place and stay on their current branch. ``feature/*``
    and ``ops/*`` receive ``develop``. ``release/*`` receives only
    ``origin/<that branch>`` — commits that landed on ``develop`` after the
    cut stay off the train. ``hotfix/*`` and ``main`` receive ``main``.
    Dirty trees and merge conflicts are reported and skipped. Re-run until
    ``remaining`` is 0.
    Open feature, ops, hotfix, and train sheets do not block other repos.
    """
    del state  # sheets no longer gate sync
    rows: list[dict] = []
    pending: list[str] = []
    for repo in sorted(discover_repos(workspace), key=lambda row: row.id):
        item: dict = {
            "id": repo.id,
            "path": repo.rel,
            "kind": repo.kind,
            "status": "failed",
            "synced": False,
        }
        try:
            result = _sync_one_workspace_repo(workspace, repo, push=push)
            item.update(result)
        except GitConvoyError as exc:
            item["error"] = exc.message
            item["next"] = f"fix {repo.id}, then {_RETRY_WORKSPACE}"
            item["branch"] = gitutil.current_branch(repo.path)
        if item.get("status") not in _DONE_STATUSES:
            pending.append(repo.id)
        rows.append(item)
    data: dict = {
        "ok": not pending,
        "repos": rows,
        "pending": pending,
        "remaining": len(pending),
        "failed": [row["id"] for row in rows if row.get("status") == "failed"],
    }
    if pending:
        data["note"] = (
            f"{len(pending)} still to sync ({', '.join(pending)}). "
            f"Re-run: {_RETRY_WORKSPACE}"
        )
    else:
        data["note"] = "all repos synchronized"
    return data


def sync_ops_develop(
    repo_path: Path,
    *,
    repo_id: str,
    push: bool,
    retry_hint: str = _RETRY_DEVELOP,
) -> dict:
    """Fast-forward ops ``develop`` from origin.

    Day-to-day ops work integrates on ``develop``; ``main`` is updated only by
    platform release or hotfix. When a ``v*`` stable tag exists on ``main`` and
    is not yet in ``develop`` (hotfix landed on ``main``), merge that tag.
    """
    gitutil.fetch(repo_path)
    ensured = gitutil.ensure_develop(repo_path, push=push)
    if ensured.get("status") == "failed":
        raise GitConvoyError(
            f"{repo_id}: cannot create develop"
            + (f" ({ensured.get('error')})" if ensured.get("error") else "")
            + f"; {retry_hint}"
        )
    has_develop = gitutil.has_local_branch(
        repo_path, "develop"
    ) or gitutil.has_remote_branch(repo_path, "develop")
    if not has_develop:
        return {
            "status": "skipped",
            "synced": False,
            "ref": "develop",
            "branch": gitutil.current_branch(repo_path),
        }
    gitutil.checkout_branch(repo_path, "develop")
    if gitutil.rev_parse(repo_path, "origin/develop"):
        pulled = gitutil.run(
            repo_path, "merge", "--ff-only", "origin/develop", check=False
        )
        if pulled.returncode != 0:
            raise GitConvoyError(
                f"{repo_id}: cannot fast-forward develop from origin; "
                f"reconcile develop, then {retry_hint}"
            )
    if gitutil.has_tracked_changes(repo_path):
        raise GitConvoyError(
            f"{repo_id} develop is dirty; commit or stash, then {retry_hint}"
        )
    before = gitutil.rev_parse(repo_path, "develop")
    merge_ref = "origin/develop"
    status = "already"
    tag = gitutil.last_stable_tag(repo_path)
    if tag and not gitutil.is_ancestor(repo_path, tag, "develop"):
        if not gitutil.rev_parse(repo_path, tag):
            raise GitConvoyError(
                f"{repo_id}: missing {tag}; fetch tags, then {retry_hint}"
            )
        merged = gitutil.merge(repo_path, tag)
        if merged.returncode != 0:
            gitutil.run(repo_path, "merge", "--abort", check=False)
            raise GitConvoyError(
                f"{repo_id}: merge hotfix tag {tag} into develop failed "
                "(merge aborted, repo left clean). "
                f"resolve on develop, then {retry_hint}"
            )
        merge_ref = tag
        status = "merged"
    elif before != gitutil.rev_parse(repo_path, "develop"):
        status = "pulled"
    if push and gitutil.origin_url(repo_path) and gitutil.rev_parse(
        repo_path, "origin/develop"
    ):
        gitutil.push(repo_path, "origin", "develop")
    return {
        "status": status,
        "synced": True,
        "ref": merge_ref or "origin/develop",
        "branch": "develop",
        "develop_created": bool(ensured.get("created")),
    }


def sync_ops_repos(
    workspace: Path,
    *,
    repo_ids: list[str] | None = None,
    push: bool = True,
    retry_hint: str = _RETRY_DEVELOP,
) -> dict:
    """Fast-forward ``develop`` for ops repos (no merge of raw ``main``)."""
    from gitconvoy.workspace import ops_repos, require_repo

    repos = ops_repos(workspace)
    if repo_ids:
        chosen = [require_repo(repos, repo_id) for repo_id in repo_ids]
    else:
        chosen = sorted(repos, key=lambda row: row.id)
    entries = [DevelopSyncEntry(id=repo.id, rel=repo.rel) for repo in chosen]
    rows: list[dict] = []
    failed: list[str] = []
    for entry in entries:
        repo_path = workspace / entry.rel
        item: dict = {
            "id": entry.id,
            "path": entry.rel,
            "status": "failed",
            "synced": False,
        }
        try:
            result = sync_ops_develop(
                repo_path,
                repo_id=entry.id,
                push=push,
                retry_hint=retry_hint,
            )
            item["status"] = result["status"]
            item["synced"] = result["synced"]
            item["ref"] = result.get("ref")
            item["branch"] = result.get("branch")
            item["develop_created"] = result.get("develop_created")
        except GitConvoyError as exc:
            item["error"] = exc.message
            failed.append(entry.id)
        rows.append(item)
    data: dict = {
        "ok": not failed,
        "repos": rows,
        "failed": failed,
    }
    if failed:
        data["note"] = (
            f"develop sync failed in: {', '.join(failed)}. "
            f"resolve, then {retry_hint}"
        )
    return data


def _sync_one_workspace_repo(
    workspace: Path, repo: Repo, *, push: bool
) -> dict:
    gitutil.fetch(repo.path)
    role = membership.read_repo_role(repo.path)
    branch = gitutil.current_branch(repo.path)
    if gitutil.cherry_pick_in_progress(repo.path):
        raise GitConvoyError(
            f"{repo.id}: cherry-pick in progress on {branch}; "
            f"finish or abort it, then {_RETRY_WORKSPACE}"
        )
    if gitutil.has_tracked_changes(repo.path):
        return {
            "status": "needs-commit",
            "synced": False,
            "branch": branch,
            "role": role,
            "next": f"commit or stash on {branch}, then {_RETRY_WORKSPACE}",
        }
    if role == "bom" or is_bom_repo_id(repo.id, workspace):
        if branch == "main":
            return _sync_main_only(repo, push=push, role="bom")
        return _sync_into_current_branch(
            repo, role="bom", upstream=_main_ref(repo.path), absorb_stable=False
        )
    if branch == "develop":
        if role == "ops":
            result = sync_ops_develop(
                repo.path,
                repo_id=repo.id,
                push=push,
                retry_hint=_RETRY_WORKSPACE,
            )
        else:
            result = sync_develop_from_ref(
                repo.path,
                repo_id=repo.id,
                push=push,
                retry_hint=_RETRY_WORKSPACE,
            )
        return {
            "status": result["status"],
            "synced": result["synced"],
            "ref": result.get("ref"),
            "branch": result.get("branch") or "develop",
            "role": role,
            "develop_created": result.get("develop_created"),
        }
    if branch == "main" or branch.startswith("hotfix/"):
        return _sync_into_current_branch(
            repo,
            role=role,
            upstream=_main_ref(repo.path),
            absorb_stable=False,
        )
    if branch.startswith("release/"):
        return _sync_into_current_branch(
            repo,
            role=role,
            upstream="",
            absorb_stable=False,
        )
    upstream = _integration_ref(repo.path, role=role)
    return _sync_into_current_branch(
        repo,
        role=role,
        upstream=upstream,
        absorb_stable=True,
    )


def _integration_ref(repo_path: Path, *, role: str) -> str:
    if gitutil.rev_parse(repo_path, "origin/develop"):
        return "origin/develop"
    if gitutil.rev_parse(repo_path, "refs/heads/develop"):
        return "develop"
    if role != "ops" and gitutil.rev_parse(repo_path, "origin/main"):
        return "origin/main"
    if gitutil.rev_parse(repo_path, "refs/heads/main"):
        return "main"
    return ""


def _main_ref(repo_path: Path) -> str:
    if gitutil.rev_parse(repo_path, "origin/main"):
        return "origin/main"
    if gitutil.rev_parse(repo_path, "refs/heads/main"):
        return "main"
    return ""


def _merge_if_missing(
    repo_path: Path, ref: str, *, repo_id: str, branch: str
) -> bool:
    """Merge ``ref`` into HEAD when it is not already contained."""
    if not ref or not gitutil.rev_parse(repo_path, ref):
        return False
    if gitutil.is_ancestor(repo_path, ref, "HEAD"):
        return False
    before = gitutil.rev_parse(repo_path, "HEAD")
    merged = gitutil.merge(repo_path, ref)
    if merged.returncode != 0:
        gitutil.run(repo_path, "merge", "--abort", check=False)
        raise GitConvoyError(
            f"{repo_id}: merge {ref} into {branch} failed "
            "(merge aborted, repo left clean). "
            f"resolve on {branch}, then {_RETRY_WORKSPACE}"
        )
    return gitutil.rev_parse(repo_path, "HEAD") != before


def _sync_into_current_branch(
    repo: Repo,
    *,
    role: str,
    upstream: str,
    absorb_stable: bool,
) -> dict:
    """Merge upstream into the checked-out branch. Does not switch branches."""
    branch = gitutil.current_branch(repo.path)
    moved = False
    refs: list[str] = []
    remote_self = f"origin/{branch}"
    if _merge_if_missing(
        repo.path, remote_self, repo_id=repo.id, branch=branch
    ):
        moved = True
        refs.append(remote_self)
    if _merge_if_missing(repo.path, upstream, repo_id=repo.id, branch=branch):
        moved = True
        refs.append(upstream)
    if absorb_stable:
        tag = gitutil.last_stable_tag(repo.path)
        if tag and _merge_if_missing(
            repo.path, tag, repo_id=repo.id, branch=branch
        ):
            moved = True
            refs.append(tag)
    if branch != "develop":
        gitutil.fast_forward_branch(repo.path, "develop")
    return {
        "status": "merged" if moved else "already",
        "synced": True,
        "ref": (refs[-1] if refs else upstream) or branch,
        "branch": branch,
        "role": role,
    }


def _sync_main_only(repo: Repo, *, push: bool, role: str) -> dict:
    gitutil.fetch(repo.path)
    gitutil.checkout_branch(repo.path, "main")
    main_ff = gitutil.fast_forward_branch(repo.path, "main")
    if main_ff == "diverged":
        raise GitConvoyError(
            f"{repo.id}: cannot fast-forward main from origin; "
            f"fix main, then {_RETRY_WORKSPACE}"
        )
    if gitutil.is_dirty(repo.path):
        raise GitConvoyError(
            f"{repo.id} main is dirty; commit or stash, then {_RETRY_WORKSPACE}"
        )
    if (
        push
        and gitutil.origin_url(repo.path)
        and gitutil.rev_parse(repo.path, "origin/main")
        and gitutil.ahead_of(repo.path, "HEAD", "origin/main")
    ):
        gitutil.push(repo.path, "origin", "main")
    status = "pulled" if main_ff == "updated" else "already"
    return {
        "status": status,
        "synced": True,
        "ref": "main",
        "branch": "main",
        "role": role,
    }


def format_develop_sync_text(data: dict, *, label: str) -> str:
    failed = data.get("failed") or []
    counts: dict[str, int] = {}
    for row in data.get("repos") or []:
        status = row.get("status") or "failed"
        counts[status] = counts.get(status, 0) + 1
    order = ("merged", "pulled", "already", "needs-commit", "skipped", "failed")
    summary = ", ".join(
        f"{counts[key]} {key}" for key in order if counts.get(key)
    ) or "nothing to do"
    remaining = data.get("remaining")
    if remaining is None:
        remaining = len(failed)
    lines = [f"{label}: {summary}"]
    if remaining:
        lines.append(
            data.get("note")
            or f"{remaining} still to sync. Re-run: {_RETRY_WORKSPACE}"
        )
    elif data.get("note") and label == "sync":
        lines.append(data["note"])
    for row in data.get("repos") or []:
        detail = row.get("error") or row.get("next") or ""
        extra = f"  {detail}" if detail else ""
        ref = f" ({row['ref']})" if row.get("ref") else ""
        branch = f" [{row['branch']}]" if row.get("branch") else ""
        lines.append(f"  {row['id']:20} {row['status']}{ref}{branch}{extra}")
    return "\n".join(lines)
