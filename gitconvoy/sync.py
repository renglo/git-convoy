from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gitconvoy import gitutil
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State
from gitconvoy.workspace import Repo, discover_repos, is_bom_repo_id

_TOPIC_PREFIXES = ("feature/", "hotfix/", "aux/", "release/")
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

    Fetches first, updates local ``main`` without leaving you on it, then
    checks out ``develop``. Repos with no develop branch are skipped. On merge
    conflict the merge is aborted so the repo is not left mid-merge.
    """
    gitutil.fetch(repo_path)
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
    return {
        "status": status,
        "synced": True,
        "ref": merge_ref,
        "branch": "develop",
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


def sync_workspace(
    workspace: Path,
    state: State,
    *,
    push: bool = True,
) -> dict:
    """Fetch every clone and leave a clean integration branch to start work.

    Product and aux repos end on ``develop`` (or ``main`` when there is no
    develop). BOM repos stay on ``main``. Refuses when the workspace is not
    idle: dirty trees, in-progress sheets, or leftover topic-branch work.
    """
    blockers = _neutrality_errors(workspace, state)
    if blockers:
        raise GitConvoyError(
            "workspace is not idle; "
            "git convoy sync is for a clean starting point:\n  "
            + "\n  ".join(blockers)
        )
    rows: list[dict] = []
    failed: list[str] = []
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
            failed.append(repo.id)
        rows.append(item)
    data: dict = {
        "ok": not failed,
        "repos": rows,
        "failed": failed,
    }
    if failed:
        data["note"] = (
            f"sync failed in: {', '.join(failed)}. "
            f"resolve, then {_RETRY_WORKSPACE}"
        )
    return data


def _sync_one_workspace_repo(
    workspace: Path, repo: Repo, *, push: bool
) -> dict:
    gitutil.fetch(repo.path)
    if is_bom_repo_id(repo.id, workspace):
        return _sync_main_only(repo, push=push, role="bom")
    has_develop = gitutil.has_local_branch(
        repo.path, "develop"
    ) or gitutil.has_remote_branch(repo.path, "develop")
    if not has_develop:
        return _sync_main_only(repo, push=push, role="product")
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
        "role": "product",
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


def _neutrality_errors(workspace: Path, state: State) -> list[str]:
    errors: list[str] = []
    dirty = [
        repo.id
        for repo in discover_repos(workspace)
        if gitutil.is_dirty(repo.path)
    ]
    if dirty:
        errors.append("dirty: " + ", ".join(dirty) + " (commit or stash first)")
    errors.extend(_pending_sheet_errors(state))
    for repo in discover_repos(workspace):
        errors.extend(_pending_repo_errors(repo))
    return errors


def _pending_sheet_errors(state: State) -> list[str]:
    errors: list[str] = []
    if state.current_feature and state.current_feature in state.features:
        feat = state.features[state.current_feature]
        if feat.repos and feat.status in {"in-progress", "in-review"}:
            ids = ", ".join(feat.repo_ids())
            errors.append(
                f"feature {feat.name} is {feat.status} ({ids}). "
                "git convoy feature refresh, or close/abandon first"
            )
    if state.current_hotfix and state.current_hotfix in state.hotfixes:
        item = state.hotfixes[state.current_hotfix]
        if item.repos and item.status != "published":
            ids = ", ".join(item.repo_ids())
            errors.append(
                f"hotfix {item.name} is {item.status} ({ids}). "
                "finish or abandon it first"
            )
    if state.current_aux and state.current_aux in state.auxes:
        item = state.auxes[state.current_aux]
        if item.repos and item.status in {"in-progress", "in-review"}:
            ids = ", ".join(item.repo_ids())
            errors.append(
                f"aux {item.name} is {item.status} ({ids}). "
                "git convoy aux refresh, or close/abandon first"
            )
    if state.current_train and state.current_train in state.trains:
        train = state.trains[state.current_train]
        if train.status in {"cut", "stabilizing"}:
            errors.append(
                f"train {train.name} is {train.status}. "
                "finish the train or git convoy train delete first"
            )
    return errors


def _pending_repo_errors(repo: Repo) -> list[str]:
    branch = gitutil.current_branch(repo.path)
    if gitutil.cherry_pick_in_progress(repo.path):
        return [f"{repo.id}: cherry-pick in progress; finish or abort it first"]
    errors: list[str] = []
    if any(branch.startswith(prefix) for prefix in _TOPIC_PREFIXES):
        if not gitutil.branch_merged_into(repo.path, branch):
            errors.append(
                f"{repo.id} is on {branch} with commits not in develop/main. "
                "close that work, or check out develop first"
            )
    develop = gitutil.rev_parse(repo.path, "refs/heads/develop")
    origin_dev = gitutil.rev_parse(repo.path, "origin/develop")
    if develop and origin_dev:
        if gitutil.ahead_of(repo.path, "develop", "origin/develop"):
            errors.append(
                f"{repo.id} has local commits on develop not on origin; "
                "git convoy feature adopt, or reset develop to origin"
            )
        elif not gitutil.is_ancestor(
            repo.path, "develop", "origin/develop"
        ) and not gitutil.is_ancestor(repo.path, "origin/develop", "develop"):
            errors.append(
                f"{repo.id} develop has diverged from origin/develop; "
                f"reconcile, then {_RETRY_WORKSPACE}"
            )
    return errors


def format_develop_sync_text(data: dict, *, label: str) -> str:
    failed = data.get("failed") or []
    counts: dict[str, int] = {}
    for row in data.get("repos") or []:
        status = row.get("status") or "failed"
        counts[status] = counts.get(status, 0) + 1
    order = ("merged", "pulled", "already", "skipped", "failed")
    summary = ", ".join(
        f"{counts[key]} {key}" for key in order if counts.get(key)
    ) or "nothing to do"
    lines = [f"{label}: {summary}"]
    for row in data.get("repos") or []:
        extra = f"  {row['error']}" if row.get("error") else ""
        ref = f" ({row['ref']})" if row.get("ref") else ""
        branch = f" [{row['branch']}]" if row.get("branch") else ""
        lines.append(f"  {row['id']:20} {row['status']}{ref}{branch}{extra}")
    if failed:
        lines.append(data.get("note") or "")
    return "\n".join(lines)
