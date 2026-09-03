from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gitconvoy import gitutil
from gitconvoy.errors import GitConvoyError


@dataclass(frozen=True)
class DevelopSyncEntry:
    id: str
    rel: str
    ref: str | None = None


def stable_ref(repo_path: Path) -> str:
    return gitutil.last_stable_tag(repo_path) or "main"


def sync_develop_from_ref(
    repo_path: Path,
    *,
    repo_id: str,
    push: bool,
    ref: str | None = None,
    retry_hint: str = "git convoy sync develop",
) -> dict:
    """Merge tagged main (or a stable tag) into develop.

    Repos with no develop branch are skipped. On merge conflict the merge is
    aborted so the repo is not left mid-merge.
    """
    merge_ref = ref or stable_ref(repo_path)
    has_develop = gitutil.has_local_branch(
        repo_path, "develop"
    ) or gitutil.has_remote_branch(repo_path, "develop")
    if not has_develop:
        return {"status": "skipped", "synced": False, "ref": merge_ref}
    gitutil.fetch(repo_path)
    gitutil.checkout_branch(repo_path, "main")
    if gitutil.rev_parse(repo_path, "origin/main"):
        pulled = gitutil.run(
            repo_path, "pull", "--ff-only", "origin", "main", check=False
        )
        if pulled.returncode != 0:
            raise GitConvoyError(
                f"{repo_id}: cannot fast-forward main from origin; "
                f"fix main, then {retry_hint}"
            )
    if merge_ref != "main" and not gitutil.rev_parse(repo_path, merge_ref):
        raise GitConvoyError(
            f"{repo_id}: missing {merge_ref}; fetch tags, then {retry_hint}"
        )
    gitutil.checkout_branch(repo_path, "develop")
    if gitutil.rev_parse(repo_path, "origin/develop"):
        pulled = gitutil.run(
            repo_path, "pull", "--ff-only", "origin", "develop", check=False
        )
        if pulled.returncode != 0:
            raise GitConvoyError(
                f"{repo_id}: cannot fast-forward develop from origin; "
                f"reconcile develop, then {retry_hint}"
            )
    if gitutil.is_dirty(repo_path):
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
    return {"status": status, "synced": True, "ref": merge_ref}


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
    retry_hint: str = "git convoy sync develop",
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


def format_develop_sync_text(data: dict, *, label: str) -> str:
    failed = data.get("failed") or []
    counts: dict[str, int] = {}
    for row in data.get("repos") or []:
        status = row.get("status") or "failed"
        counts[status] = counts.get(status, 0) + 1
    summary = ", ".join(
        f"{counts[key]} {key}"
        for key in ("merged", "already", "skipped", "failed")
        if counts.get(key)
    ) or "nothing to do"
    lines = [f"{label}: {summary}"]
    for row in data.get("repos") or []:
        extra = f"  {row['error']}" if row.get("error") else ""
        ref = f" ({row['ref']})" if row.get("ref") else ""
        lines.append(f"  {row['id']:20} {row['status']}{ref}{extra}")
    if failed:
        lines.append(data.get("note") or "")
    return "\n".join(lines)
