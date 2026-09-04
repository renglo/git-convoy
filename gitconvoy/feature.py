from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from gitconvoy import ghutil
from gitconvoy import gitutil
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import Feature, State, save
from gitconvoy.sync import DevelopSyncEntry, sync_repos_develop
from gitconvoy.workspace import Repo, feature_repos, is_bom_repo_id, merge_sort


def start(workspace: Path, state: State, name: str) -> dict:
    slug = _slug(name)
    branch = f"feature/{slug}"
    if slug not in state.features:
        state.features[slug] = Feature(name=slug, branch=branch)
    state.current_feature = slug
    feature = state.features[slug]
    checked: list[dict] = []
    picked: list[dict] = []
    for repo in feature_repos(workspace):
        gitutil.fetch(repo.path)
        current = gitutil.current_branch(repo.path)
        dirty = gitutil.is_dirty(repo.path)
        exists = gitutil.has_branch(repo.path, branch)
        if exists:
            if current != branch:
                if dirty:
                    checked.append(
                        {
                            "id": repo.id,
                            "path": repo.rel,
                            "skipped": "dirty",
                            "branch": current,
                            "existing_branch": branch,
                        }
                    )
                    continue
                gitutil.checkout_branch(repo.path, branch)
            if not _branch_has_work(repo.path, branch):
                if repo.id in feature.repo_ids():
                    feature.drop_repo(repo.id)
                if not gitutil.is_dirty(repo.path):
                    gitutil.checkout_integration(repo.path)
                checked.append(
                    {
                        "id": repo.id,
                        "path": repo.rel,
                        "skipped": "empty-feature-branch",
                        "branch": gitutil.current_branch(repo.path),
                        "existing_branch": branch,
                    }
                )
                continue
            feature.add_repo(repo.id, repo.rel)
            action = (
                "already-on-feature" if current == branch else "picked-up"
            )
            row = {
                "id": repo.id,
                "path": repo.rel,
                "branch": branch,
                "action": action,
                "dirty": gitutil.is_dirty(repo.path),
            }
            picked.append(row)
            checked.append(row)
            continue
        if dirty:
            checked.append(
                {
                    "id": repo.id,
                    "path": repo.rel,
                    "skipped": "dirty",
                    "branch": current,
                }
            )
            continue
        integration = gitutil.checkout_integration(repo.path)
        checked.append(
            {
                "id": repo.id,
                "path": repo.rel,
                "branch": gitutil.current_branch(repo.path),
                "integration_branch": integration,
            }
        )
    save(workspace, state)
    return {
        "ok": True,
        "feature": slug,
        "branch": branch,
        "repos": picked,
        "repo_count": len(feature.repos),
        "workspace": checked,
        "dropped": _drop_non_feature_sheet_repos(feature),
    }


def adopt(workspace: Path, state: State) -> dict:
    feature = state.require_feature()
    adopted: list[dict] = []
    skipped: list[dict] = []
    dropped: list[dict] = []
    dropped.extend(_drop_non_feature_sheet_repos(feature))
    for repo in feature_repos(workspace):
        result = _adopt_one(repo, feature)
        if result.get("adopted"):
            feature.add_repo(repo.id, repo.rel)
            adopted.append(result)
            continue
        skipped.append(result)
        if result.get("drop") and feature.drop_repo(repo.id):
            dropped.append(
                {
                    "id": repo.id,
                    "path": repo.rel,
                    "reason": result.get("reason"),
                }
            )
    save(workspace, state)
    return {
        "ok": True,
        "feature": feature.name,
        "branch": feature.branch,
        "adopted": adopted,
        "skipped": skipped,
        "dropped": dropped,
        "repo_count": len(feature.repos),
    }


def _drop_non_feature_sheet_repos(feature: Feature) -> list[dict]:
    """Remove *-bom (and other non-feature) rows left on an older sheet."""
    dropped: list[dict] = []
    for row in list(feature.repos):
        if not is_bom_repo_id(row.id):
            continue
        feature.drop_repo(row.id)
        dropped.append(
            {
                "id": row.id,
                "path": row.path,
                "reason": "bom-not-a-feature-repo",
            }
        )
    return dropped


def _branch_has_work(repo: Path, branch: str) -> bool:
    """Dirty on this branch, or commits not already contained in develop/main."""
    if gitutil.is_dirty(repo) and gitutil.current_branch(repo) == branch:
        return True
    if not gitutil.has_branch(repo, branch):
        return False
    return not gitutil.branch_merged_into(repo, branch)


def _adopt_one(repo: Repo, feature: Feature) -> dict:
    branch = feature.branch
    current = gitutil.current_branch(repo.path)
    dirty = gitutil.is_dirty(repo.path)
    gitutil.fetch(repo.path)
    integration = gitutil.integration_branch(repo.path)
    origin_int = gitutil.origin_integration(repo.path)
    on_integration = current == integration
    ahead = bool(
        origin_int
        and on_integration
        and gitutil.ahead_of(repo.path, "HEAD", f"origin/{integration}")
    )
    exists = gitutil.has_branch(repo.path, branch)
    unique = exists and not gitutil.branch_merged_into(repo.path, branch)

    if current == branch:
        if dirty or unique:
            return {
                "id": repo.id,
                "path": repo.rel,
                "adopted": True,
                "action": "already-on-feature",
                "dirty": dirty,
            }
        if not dirty:
            gitutil.checkout_integration(repo.path)
        return {
            "id": repo.id,
            "path": repo.rel,
            "adopted": False,
            "reason": "on-feature-no-changes",
            "drop": True,
        }

    if exists and unique and not dirty:
        if not on_integration:
            raise GitConvoyError(
                f"{repo.id} has work on {current}, not {integration} or {branch}. "
                "commit/stash or checkout the right branch first"
            )
        gitutil.checkout_branch(repo.path, branch)
        return {
            "id": repo.id,
            "path": repo.rel,
            "adopted": True,
            "action": "picked-up",
            "dirty": False,
        }

    if not dirty and not ahead:
        return {
            "id": repo.id,
            "path": repo.rel,
            "adopted": False,
            "reason": "empty-feature-branch" if exists else "unchanged",
            "branch": current,
            "drop": bool(exists),
        }

    if not on_integration and current != branch:
        raise GitConvoyError(
            f"{repo.id} has work on {current}, not {integration} or {branch}. "
            "commit/stash or checkout the right branch first"
        )

    gitutil.checkout_branch(repo.path, branch)

    if ahead and origin_int and gitutil.rev_parse(repo.path, f"refs/heads/{integration}"):
        if not gitutil.is_ancestor(repo.path, f"origin/{integration}", branch):
            raise GitConvoyError(
                f"{repo.id}: {integration} has diverged from origin/{integration}"
            )
        gitutil.checkout(repo.path, integration)
        if gitutil.rev_parse(repo.path, "HEAD") == origin_int:
            gitutil.checkout(repo.path, branch)
        else:
            if gitutil.ahead_of(repo.path, integration, f"origin/{integration}"):
                gitutil.reset_hard(repo.path, f"origin/{integration}")
            gitutil.checkout(repo.path, branch)

    return {
        "id": repo.id,
        "path": repo.rel,
        "adopted": True,
        "action": "branched",
        "dirty": dirty,
        "reset_integration": bool(ahead),
        "integration_branch": integration,
    }


def abandon(
    workspace: Path,
    state: State,
    name: str | None = None,
    *,
    yes: bool = False,
    remote: bool = False,
    as_json: bool = False,
    input_fn=None,
    is_tty: bool | None = None,
) -> dict:
    feature = state.require_feature(name)
    branch = feature.branch
    targets = _abandon_targets(workspace, feature)
    if not yes:
        if as_json or not (sys.stdin.isatty() if is_tty is None else is_tty):
            raise GitConvoyError(
                "abandon discards the feature branch; pass --yes to confirm"
            )
        ids = ", ".join(item.id for item in targets) or "(none)"
        prompt = (
            f"This will delete local branch {branch} in {len(targets)} repos "
            f"({ids}) and discard uncommitted work on that branch "
            "(including untracked files). "
            "Continue? : "
        )
        answer = _confirm_yes(input_fn or input, prompt)
        if not answer:
            return {
                "ok": True,
                "abandoned": False,
                "feature": feature.name,
                "branch": branch,
                "repos": [],
            }

    removed: list[dict] = []
    for repo in targets:
        gitutil.fetch(repo.path)
        on_origin = gitutil.has_remote_branch(repo.path, branch)
        dirty = gitutil.is_dirty(repo.path)
        current = gitutil.current_branch(repo.path)
        if current == branch:
            gitutil.reset_hard(repo.path, "HEAD")
            gitutil.clean_untracked(repo.path)
            gitutil.checkout_integration(repo.path)
        else:
            gitutil.checkout_integration(repo.path)
        deleted_local = False
        if gitutil.has_local_branch(repo.path, branch):
            gitutil.delete_branch(repo.path, branch)
            deleted_local = True
        deleted_remote = False
        if remote and on_origin:
            gitutil.delete_remote_branch(repo.path, branch)
            deleted_remote = True
        removed.append(
            {
                "id": repo.id,
                "path": repo.rel,
                "deleted_local": deleted_local,
                "deleted_remote": deleted_remote,
                "on_origin": on_origin and not deleted_remote,
                "discarded_dirty": dirty and current == branch,
                "branch": gitutil.current_branch(repo.path),
            }
        )

    if state.current_feature == feature.name:
        state.current_feature = None
    state.features.pop(feature.name, None)
    save(workspace, state)
    still_on_origin = [row["id"] for row in removed if row["on_origin"]]
    note = (
        "Local feature branches deleted. Check out the integration branch. "
        "Uncommitted work on those branches is gone."
    )
    if still_on_origin and not remote:
        note += (
            " Still on origin (not deleted): "
            + ", ".join(still_on_origin)
            + ". Re-run with --remote to delete there."
        )
    return {
        "ok": True,
        "abandoned": True,
        "feature": feature.name,
        "branch": branch,
        "note": note,
        "repos": removed,
    }


def _abandon_targets(workspace: Path, feature: Feature):
    from gitconvoy.workspace import Repo

    products = feature_repos(workspace)
    by_id = {repo.id: repo for repo in products}
    seen: set[str] = set()
    targets: list[Repo] = []
    for row in feature.repos:
        repo = by_id.get(row.id)
        if repo and repo.id not in seen:
            seen.add(repo.id)
            targets.append(repo)
    for repo in products:
        if repo.id in seen:
            continue
        if gitutil.has_local_branch(repo.path, feature.branch):
            seen.add(repo.id)
            targets.append(repo)
    return targets


def _confirm_yes(input_fn, prompt: str) -> bool:
    while True:
        answer = input_fn(prompt).strip().lower()
        if answer in {"yes", "y"}:
            return True
        if answer in {"no", "n"}:
            return False


def switch(workspace: Path, state: State, name: str) -> dict:
    slug = _slug(name)
    feature = state.require_feature(slug)
    repos = feature_repos(workspace)
    dirty = [
        {"id": repo.id, "path": repo.rel, "branch": gitutil.current_branch(repo.path)}
        for repo in repos
        if gitutil.is_dirty(repo.path)
    ]
    if dirty:
        raise GitConvoyError(
            "dirty repos; commit or stash before switch: "
            + ", ".join(item["id"] for item in dirty)
        )
    participant_ids = set(feature.repo_ids())
    switched: list[dict] = []
    for repo in repos:
        if repo.id in participant_ids:
            gitutil.checkout_branch(repo.path, feature.branch)
            switched.append(
                {"id": repo.id, "path": repo.rel, "branch": feature.branch}
            )
        else:
            integration = gitutil.checkout_integration(repo.path)
            switched.append(
                {
                    "id": repo.id,
                    "path": repo.rel,
                    "branch": integration,
                }
            )
    state.current_feature = slug
    save(workspace, state)
    return {
        "ok": True,
        "feature": slug,
        "branch": feature.branch,
        "participants": feature.repo_ids(),
        "repos": switched,
    }


def refresh(workspace: Path, state: State) -> dict:
    feature = state.require_feature()
    results: list[dict] = []
    conflicts: list[str] = []
    for repo_row in feature.repos:
        repo_path = workspace / repo_row.path
        integration = gitutil.integration_branch(repo_path)
        gitutil.checkout_branch(repo_path, feature.branch)
        gitutil.fetch(repo_path)
        merged = gitutil.merge(repo_path, f"origin/{integration}")
        item = {
            "id": repo_row.id,
            "path": repo_row.path,
            "ok": merged.returncode == 0,
        }
        if merged.returncode != 0:
            item["error"] = (merged.stderr or merged.stdout or "").strip()
            conflicts.append(repo_row.id)
        results.append(item)
    if conflicts:
        raise GitConvoyError(
            "merge conflicts in: "
            + ", ".join(conflicts)
            + ". resolve them, then re-run refresh"
        )
    return {"ok": True, "feature": feature.name, "repos": results}


def push(workspace: Path, state: State) -> dict:
    feature = state.require_feature()
    rows = _push_feature_branches(workspace, feature)
    return {
        "ok": True,
        "feature": feature.name,
        "branch": feature.branch,
        "note": (
            "Pushed feature branches to origin. No PRs opened. "
            "Uncommitted files are not on the remote."
        ),
        "repos": rows,
    }


def prs(workspace: Path, state: State, use_gh: bool = True) -> dict:
    feature = state.require_feature()
    branch = feature.branch
    entries = [
        DevelopSyncEntry(id=repo_row.id, rel=repo_row.path)
        for repo_row in feature.repos
    ]
    develop_sync = sync_repos_develop(
        workspace,
        entries,
        push=True,
        retry_hint="git convoy feature prs",
    )
    for repo_row in feature.repos:
        gitutil.checkout_branch(workspace / repo_row.path, branch)
    if not develop_sync["ok"]:
        raise GitConvoyError(
            develop_sync.get("note")
            or "develop sync failed; resolve conflicts, then git convoy feature prs"
        )
    _push_feature_branches(workspace, feature)
    opened: list[dict] = []
    for repo_row in feature.repos:
        repo_path = workspace / repo_row.path
        url = repo_row.pr
        slug = gitutil.github_slug(repo_path)
        if use_gh and gitutil.gh_bin() and slug:
            created = _gh_create_pr(repo_path, feature, slug)
            if created:
                url = created
                repo_row.pr = created
        compare = None
        if slug:
            integration = gitutil.integration_branch(repo_path)
            compare = (
                f"https://github.com/{slug}/compare/{integration}...{feature.branch}"
            )
        opened.append(
            {
                "id": repo_row.id,
                "path": repo_row.path,
                "pr": url,
                "compare": compare,
                "merge_order": merge_sort(feature.repo_ids()).index(repo_row.id)
                if repo_row.id in feature.repo_ids()
                else None,
            }
        )
    feature.status = "in-review"
    save(workspace, state)
    opened_prs = sum(1 for row in opened if row.get("pr"))
    note = (
        "Merged latest stable/main into develop before opening PRs. "
        "Approve with: git convoy feature approve (Full mode). Merge only when all "
        "sibling PRs are approved, in merge_order. git-convoy does not merge."
    )
    if use_gh and opened and opened_prs == 0:
        note += (
            " No PRs were opened via gh (check `gh auth status`); "
            "compare URLs below open the PR form in the browser."
        )
    missing = [row["id"] for row in opened if not row.get("pr") and not row.get("compare")]
    if missing:
        note += (
            " No GitHub URL for: "
            + ", ".join(missing)
            + " (origin remote not recognized as GitHub)."
        )
    return {
        "ok": True,
        "feature": feature.name,
        "merge_order": merge_sort(feature.repo_ids()),
        "develop_sync": develop_sync,
        "note": note,
        "repos": opened,
    }


def approve(
    workspace: Path,
    state: State,
    name: str | None = None,
    *,
    force: bool = False,
) -> dict:
    feature = state.require_feature(name)
    if not feature.repos:
        raise GitConvoyError("feature has no participant repos; run feature adopt")
    ghutil.require_gh()
    order = merge_sort(feature.repo_ids())
    by_id = {repo.id: repo for repo in feature.repos}
    rows: list[dict] = []
    blocked: list[str] = []
    for repo_id in order:
        repo_row = by_id.get(repo_id)
        if not repo_row:
            continue
        repo_path = workspace / repo_row.path
        slug = gitutil.github_slug(repo_path)
        if not slug:
            blocked.append(f"{repo_id} (no github remote)")
            rows.append(
                {
                    "id": repo_id,
                    "path": repo_row.path,
                    "slug": None,
                    "pr": repo_row.pr,
                    "status": "no-remote",
                }
            )
            continue
        merge_status = gitutil.pr_merge_status(repo_path, feature.branch, repo_row.pr)
        if merge_status == "merged":
            rows.append(
                {
                    "id": repo_id,
                    "path": repo_row.path,
                    "slug": slug,
                    "pr": repo_row.pr,
                    "status": "merged",
                }
            )
            continue
        pr_url = repo_row.pr or ghutil.find_pr_url(slug, feature.branch, cwd=repo_path)
        if pr_url and not repo_row.pr:
            repo_row.pr = pr_url
        number = gitutil.pr_number(pr_url)
        if not number:
            blocked.append(f"{repo_id} (no open PR)")
            rows.append(
                {
                    "id": repo_id,
                    "path": repo_row.path,
                    "slug": slug,
                    "pr": pr_url,
                    "status": "no-pr",
                }
            )
            continue
        details = ghutil.pr_details(slug, number, cwd=repo_path)
        checks = ghutil.checks_state(details)
        review = (details.get("reviewDecision") or "").upper() if details else ""
        if review == "APPROVED":
            rows.append(
                {
                    "id": repo_id,
                    "path": repo_row.path,
                    "slug": slug,
                    "pr": pr_url,
                    "status": "already-approved",
                    "checks": checks,
                }
            )
            continue
        if not force and checks in {"pending", "failure", "error", "action_required"}:
            blocked.append(f"{repo_id} (checks {checks})")
            rows.append(
                {
                    "id": repo_id,
                    "path": repo_row.path,
                    "slug": slug,
                    "pr": pr_url,
                    "status": "blocked",
                    "checks": checks,
                }
            )
            continue
        ok, message = ghutil.approve_pr(slug, number, cwd=repo_path)
        if not ok:
            blocked.append(f"{repo_id} ({message})")
        rows.append(
            {
                "id": repo_id,
                "path": repo_row.path,
                "slug": slug,
                "pr": pr_url,
                "status": "approved" if ok else "failed",
                "checks": checks,
                "error": None if ok else message,
            }
        )
    save(workspace, state)
    approved_count = sum(
        1 for row in rows if row["status"] in {"approved", "already-approved", "merged"}
    )
    payload = {
        "ok": not blocked,
        "feature": feature.name,
        "branch": feature.branch,
        "merge_order": order,
        "approved_count": approved_count,
        "repo_count": len(rows),
        "repos": rows,
        "note": (
            "Merge only when every sibling PR is approved, in merge_order. "
            "git-convoy does not merge."
        ),
    }
    if blocked:
        raise GitConvoyError(
            "could not approve all PRs: "
            + ", ".join(blocked)
            + ("" if force else "; pass --force to approve despite failing checks")
        )
    return payload


def show(workspace: Path, state: State, name: str | None = None) -> dict:
    feature = state.require_feature(name)
    rows = _merge_rows(workspace, feature)
    merged_count = sum(1 for row in rows if row["merge_status"] == "merged")
    if rows and merged_count == len(rows):
        feature.status = "merged"
    elif any(repo.pr for repo in feature.repos):
        feature.status = "in-review"
    else:
        feature.status = "in-progress"
    save(workspace, state)
    return {
        "ok": True,
        "name": feature.name,
        "branch": feature.branch,
        "status": feature.status,
        "repo_count": len(feature.repos),
        "merged_count": merged_count,
        "repos": rows,
        "merge_order": merge_sort(feature.repo_ids()),
        "note": _show_next_steps(rows),
    }


def _show_next_steps(rows: list[dict]) -> str:
    """Human caption for what to do next after ``feature show``."""
    if not rows:
        return "No participants yet. Run: git convoy feature adopt"
    statuses = {row["merge_status"] for row in rows}
    if statuses <= {"merged"}:
        return "All participants merged. Run: git convoy feature close"
    if "uncommitted" in statuses:
        return (
            "Uncommitted changes on one or more participants. "
            "Run: git convoy feature commit"
        )
    if "committed" in statuses and "pending" not in statuses:
        return (
            "Changes committed. Run: git convoy feature prs to open pull requests "
            "for these changes."
        )
    if "pending" in statuses:
        return (
            "PRs open (or recorded). Approve with: git convoy feature approve "
            "(Full mode), then merge in GitHub when every sibling is approved."
        )
    if "closed" in statuses:
        return (
            "One or more PRs were closed without merging. "
            "Re-open or run: git convoy feature prs"
        )
    return ""


def _merge_rows(workspace: Path, feature: Feature) -> list[dict]:
    rows: list[dict] = []
    for repo in feature.repos:
        repo_path = workspace / repo.path
        merge_status = gitutil.pr_merge_status(repo_path, feature.branch, repo.pr)
        rows.append(
            {
                "id": repo.id,
                "path": repo.path,
                "pr": repo.pr,
                "merge_status": merge_status,
            }
        )
    return rows


def close(
    workspace: Path,
    state: State,
    name: str | None = None,
    *,
    yes: bool = False,
    remote: bool = False,
    keep_branch: bool = False,
    as_json: bool = False,
    input_fn=None,
    is_tty: bool | None = None,
) -> dict:
    feature = state.require_feature(name)
    rows = _merge_rows(workspace, feature)
    pending = [row for row in rows if row["merge_status"] != "merged"]
    if pending:
        raise GitConvoyError(
            "not all participants merged: "
            + ", ".join(f"{row['id']} ({row['merge_status']})" for row in pending)
            + ". Run: git convoy feature show"
        )

    if not yes:
        if as_json or not (sys.stdin.isatty() if is_tty is None else is_tty):
            raise GitConvoyError("close removes the feature sheet; pass --yes to confirm")
        ids = ", ".join(row["id"] for row in rows) or "(none)"
        prompt = (
            f"This will check out the integration branch in {len(rows)} repos ({ids}), "
            f"pull from origin, "
        )
        if keep_branch:
            prompt += "and keep local feature branches. Continue? : "
        else:
            prompt += (
                f"delete local {feature.branch}"
                + (" and origin" if remote else "")
                + ". Continue? : "
            )
        answer = _confirm_yes(input_fn or input, prompt)
        if not answer:
            return {
                "ok": True,
                "closed": False,
                "feature": feature.name,
                "branch": feature.branch,
                "repos": [],
            }

    cleaned: list[dict] = []
    for row in rows:
        repo_path = workspace / row["path"]
        gitutil.fetch(repo_path)
        current = gitutil.current_branch(repo_path)
        dirty = gitutil.is_dirty(repo_path)
        if dirty and current == feature.branch:
            raise GitConvoyError(
                f"{row['id']} has uncommitted changes on {feature.branch}; "
                "commit or stash before close"
            )
        integration = gitutil.checkout_integration(repo_path)
        deleted_local = False
        if not keep_branch and gitutil.has_local_branch(repo_path, feature.branch):
            gitutil.delete_branch(repo_path, feature.branch)
            deleted_local = True
        on_origin = gitutil.has_remote_branch(repo_path, feature.branch)
        deleted_remote = False
        if remote and on_origin:
            gitutil.delete_remote_branch(repo_path, feature.branch)
            deleted_remote = True
        cleaned.append(
            {
                "id": row["id"],
                "path": row["path"],
                "merge_status": row["merge_status"],
                "branch": gitutil.current_branch(repo_path),
                "integration_branch": integration,
                "deleted_local": deleted_local,
                "deleted_remote": deleted_remote,
                "on_origin": on_origin and not deleted_remote,
            }
        )

    if state.current_feature == feature.name:
        state.current_feature = None
    state.features.pop(feature.name, None)
    save(workspace, state)
    still_on_origin = [row["id"] for row in cleaned if row["on_origin"]]
    note = "Checked out the integration branch and pulled from origin in every participant."
    if keep_branch:
        note += f" Local {feature.branch} branches kept."
    else:
        note += f" Local {feature.branch} deleted where present."
    if still_on_origin and not remote:
        note += (
            f" {feature.branch} still on origin in: "
            + ", ".join(still_on_origin)
            + ". Re-run with --remote to delete there."
        )
    return {
        "ok": True,
        "closed": True,
        "feature": feature.name,
        "branch": feature.branch,
        "note": note,
        "repos": cleaned,
    }



def _push_feature_branches(workspace: Path, feature: Feature) -> list[dict]:
    if not feature.repos:
        raise GitConvoyError("feature has no participant repos; run feature adopt")
    rows: list[dict] = []
    failed: list[str] = []
    for repo_row in feature.repos:
        repo_path = workspace / repo_row.path
        gitutil.checkout_branch(repo_path, feature.branch)
        dirty = gitutil.is_dirty(repo_path)
        item: dict = {
            "id": repo_row.id,
            "path": repo_row.path,
            "branch": feature.branch,
            "dirty": dirty,
            "ok": True,
        }
        try:
            gitutil.push(repo_path, "-u", "origin", feature.branch)
        except GitConvoyError as exc:
            item["ok"] = False
            item["error"] = exc.message
            failed.append(repo_row.id)
        rows.append(item)
    if failed:
        raise GitConvoyError("push failed in: " + ", ".join(failed))
    return rows


def _gh_create_pr(repo: Path, feature: Feature, slug: str) -> str | None:
    gh = gitutil.gh_bin()
    if not gh:
        return None
    existing = subprocess.run(
        [gh, "pr", "list", "--repo", slug, "--head", feature.branch, "--json", "url"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if existing.returncode == 0 and '"url"' in (existing.stdout or ""):
        import json

        rows = json.loads(existing.stdout)
        if rows:
            return rows[0].get("url")
    title = f"{feature.branch}"
    body = (
        f"Part of cross-repo feature `{feature.name}`.\n\n"
        f"Participants: {', '.join(feature.repo_ids()) or '(this repo)'}\n\n"
        "Do not merge until every sibling PR is approved."
    )
    integration = gitutil.integration_branch(repo)
    created = subprocess.run(
        [
            gh,
            "pr",
            "create",
            "--repo",
            slug,
            "--base",
            integration,
            "--head",
            feature.branch,
            "--title",
            title,
            "--body",
            body,
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        return None
    return (created.stdout or "").strip() or None


def _slug(name: str) -> str:
    slug = name.strip().replace(" ", "-")
    if slug.startswith("feature/"):
        slug = slug[len("feature/") :]
    if not slug:
        raise GitConvoyError("feature name is empty")
    return slug
