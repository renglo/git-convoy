from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from gitconvoy import ghutil
from gitconvoy import gitutil
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import Aux, State, save
from gitconvoy.workspace import Repo, aux_repos, merge_sort

# Aux PRs land on main (hotfix-style). Close merges main back into develop.
_AUX_PR_BASE = "main"


def start(workspace: Path, state: State, name: str) -> dict:
    slug = _slug(name)
    branch = f"aux/{slug}"
    if slug not in state.auxes:
        state.auxes[slug] = Aux(name=slug, branch=branch)
    state.current_aux = slug
    feature = state.auxes[slug]
    checked: list[dict] = []
    picked: list[dict] = []
    for repo in aux_repos(workspace):
        gitutil.fetch(repo.path)
        ensured = gitutil.ensure_develop(repo.path, push=bool(gitutil.origin_url(repo.path)))
        if ensured.get("status") == "failed":
            raise GitConvoyError(
                f"{repo.id}: cannot ensure develop"
                + (f" ({ensured.get('error')})" if ensured.get("error") else "")
            )
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
                        "skipped": "empty-aux-branch",
                        "branch": gitutil.current_branch(repo.path),
                        "existing_branch": branch,
                    }
                )
                continue
            feature.add_repo(repo.id, repo.rel)
            action = (
                "already-on-aux" if current == branch else "picked-up"
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
        "aux": slug,
        "branch": branch,
        "repos": picked,
        "repo_count": len(feature.repos),
        "workspace": checked,
        "dropped": _drop_non_aux_sheet_repos(workspace, feature),
    }


def adopt(workspace: Path, state: State) -> dict:
    feature = state.require_aux()
    adopted: list[dict] = []
    skipped: list[dict] = []
    dropped: list[dict] = []
    dropped.extend(_drop_non_aux_sheet_repos(workspace, feature))
    for repo in aux_repos(workspace):
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
        "aux": feature.name,
        "branch": feature.branch,
        "adopted": adopted,
        "skipped": skipped,
        "dropped": dropped,
        "repo_count": len(feature.repos),
    }


def _drop_non_aux_sheet_repos(workspace: Path, feature: Aux) -> list[dict]:
    """Remove product/bom rows that do not belong on an aux sheet."""
    allowed = {repo.id for repo in aux_repos(workspace)}
    dropped: list[dict] = []
    for row in list(feature.repos):
        if row.id in allowed:
            continue
        feature.drop_repo(row.id)
        dropped.append(
            {
                "id": row.id,
                "path": row.path,
                "reason": "not-an-aux-repo",
            }
        )
    return dropped


def _branch_has_work(repo: Path, branch: str) -> bool:
    """Dirty on this branch, or commits not already contained in main."""
    if gitutil.is_dirty(repo) and gitutil.current_branch(repo) == branch:
        return True
    if not gitutil.has_branch(repo, branch):
        return False
    main_tip = gitutil.rev_parse(repo, "origin/main") or gitutil.rev_parse(repo, "main")
    if main_tip:
        return not gitutil.branch_merged_into(repo, branch, base=main_tip)
    return not gitutil.branch_merged_into(repo, branch)


def _fish_bases(repo_path: Path) -> list[str]:
    """Branches aux adopt may take work from: develop and/or main when present."""
    bases: list[str] = []
    for name in ("develop", "main"):
        if gitutil.has_local_branch(repo_path, name) or gitutil.has_remote_branch(
            repo_path, name
        ):
            bases.append(name)
    return bases


def _adopt_one(repo: Repo, feature: Aux) -> dict:
    branch = feature.branch
    current = gitutil.current_branch(repo.path)
    dirty = gitutil.is_dirty(repo.path)
    gitutil.fetch(repo.path)
    bases = _fish_bases(repo.path)
    if not bases:
        bases = [gitutil.integration_branch(repo.path)]
    on_base = current in bases
    ahead = False
    ahead_base: str | None = None
    if on_base:
        origin_tip = gitutil.rev_parse(repo.path, f"origin/{current}")
        if origin_tip and gitutil.ahead_of(repo.path, "HEAD", f"origin/{current}"):
            ahead = True
            ahead_base = current
    exists = gitutil.has_branch(repo.path, branch)
    unique = exists and not gitutil.branch_merged_into(repo.path, branch)
    allowed = ", ".join(bases) if bases else "develop/main"

    if current == branch:
        if dirty or unique:
            return {
                "id": repo.id,
                "path": repo.rel,
                "adopted": True,
                "action": "already-on-aux",
                "dirty": dirty,
            }
        if not dirty:
            gitutil.checkout_integration(repo.path)
        return {
            "id": repo.id,
            "path": repo.rel,
            "adopted": False,
            "reason": "on-aux-no-changes",
            "drop": True,
        }

    if exists and unique and not dirty:
        if not on_base:
            raise GitConvoyError(
                f"{repo.id} has work on {current}, not {allowed} or {branch}. "
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
            "reason": "empty-aux-branch" if exists else "unchanged",
            "branch": current,
            "drop": bool(exists),
        }

    if not on_base and current != branch:
        raise GitConvoyError(
            f"{repo.id} has work on {current}, not {allowed} or {branch}. "
            "commit/stash or checkout the right branch first"
        )

    gitutil.checkout_branch(repo.path, branch)

    if ahead and ahead_base and gitutil.rev_parse(repo.path, f"refs/heads/{ahead_base}"):
        origin_ref = f"origin/{ahead_base}"
        if not gitutil.is_ancestor(repo.path, origin_ref, branch):
            raise GitConvoyError(
                f"{repo.id}: {ahead_base} has diverged from {origin_ref}"
            )
        gitutil.checkout(repo.path, ahead_base)
        if gitutil.rev_parse(repo.path, "HEAD") == gitutil.rev_parse(repo.path, origin_ref):
            gitutil.checkout(repo.path, branch)
        else:
            if gitutil.ahead_of(repo.path, ahead_base, origin_ref):
                gitutil.reset_hard(repo.path, origin_ref)
            gitutil.checkout(repo.path, branch)

    return {
        "id": repo.id,
        "path": repo.rel,
        "adopted": True,
        "action": "branched",
        "dirty": dirty,
        "reset_base": ahead_base if ahead else None,
        "fish_from": current if on_base else None,
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
    feature = state.require_aux(name)
    branch = feature.branch
    targets = _abandon_targets(workspace, feature)
    if not yes:
        if as_json or not (sys.stdin.isatty() if is_tty is None else is_tty):
            raise GitConvoyError(
                "abandon discards the aux branch; pass --yes to confirm"
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
                "aux": feature.name,
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

    if state.current_aux == feature.name:
        state.current_aux = None
    state.auxes.pop(feature.name, None)
    save(workspace, state)
    still_on_origin = [row["id"] for row in removed if row["on_origin"]]
    note = (
        "Local aux branches deleted. Check out the integration branch. "
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
        "aux": feature.name,
        "branch": branch,
        "note": note,
        "repos": removed,
    }


def _abandon_targets(workspace: Path, feature: Aux):
    from gitconvoy.workspace import Repo

    products = aux_repos(workspace)
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
    feature = state.require_aux(slug)
    repos = aux_repos(workspace)
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
    state.current_aux = slug
    save(workspace, state)
    return {
        "ok": True,
        "aux": slug,
        "branch": feature.branch,
        "participants": feature.repo_ids(),
        "repos": switched,
    }


def refresh(workspace: Path, state: State) -> dict:
    feature = state.require_aux()
    results: list[dict] = []
    conflicts: list[str] = []
    for repo_row in feature.repos:
        repo_path = workspace / repo_row.path
        ensured = gitutil.ensure_develop(repo_path, push=bool(gitutil.origin_url(repo_path)))
        if ensured.get("status") == "failed":
            raise GitConvoyError(
                f"{repo_row.id}: cannot ensure develop"
                + (f" ({ensured.get('error')})" if ensured.get("error") else "")
            )
        gitutil.checkout_branch(repo_path, feature.branch)
        gitutil.fetch(repo_path)
        main_ref = (
            "origin/main"
            if gitutil.has_remote_branch(repo_path, "main")
            else "main"
        )
        merged = gitutil.merge(repo_path, main_ref)
        item = {
            "id": repo_row.id,
            "path": repo_row.path,
            "ok": merged.returncode == 0,
            "ref": main_ref,
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
    return {"ok": True, "aux": feature.name, "repos": results}


def push(workspace: Path, state: State) -> dict:
    feature = state.require_aux()
    rows = _push_aux_branches(workspace, feature)
    return {
        "ok": True,
        "aux": feature.name,
        "branch": feature.branch,
        "note": (
            "Pushed aux branches to origin. No PRs opened. "
            "Uncommitted files are not on the remote."
        ),
        "repos": rows,
    }


def prs(workspace: Path, state: State, use_gh: bool = True) -> dict:
    feature = state.require_aux()
    branch = feature.branch
    ensured_rows: list[dict] = []
    for repo_row in feature.repos:
        repo_path = workspace / repo_row.path
        ensured = gitutil.ensure_develop(
            repo_path, push=bool(gitutil.origin_url(repo_path))
        )
        if ensured.get("status") == "failed":
            raise GitConvoyError(
                f"{repo_row.id}: cannot ensure develop"
                + (f" ({ensured.get('error')})" if ensured.get("error") else "")
                + "; fix, then git convoy aux prs"
            )
        ensured_rows.append(
            {
                "id": repo_row.id,
                "path": repo_row.path,
                "status": ensured.get("status"),
                "created": bool(ensured.get("created")),
            }
        )
        gitutil.checkout_branch(repo_path, "main")
        if gitutil.rev_parse(repo_path, "origin/main"):
            pulled = gitutil.run(
                repo_path, "pull", "--ff-only", "origin", "main", check=False
            )
            if pulled.returncode != 0:
                raise GitConvoyError(
                    f"{repo_row.id}: cannot fast-forward main from origin; "
                    "fix main, then git convoy aux prs"
                )
        gitutil.checkout_branch(repo_path, branch)
    _push_aux_branches(workspace, feature)
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
            compare = (
                f"https://github.com/{slug}/compare/{_AUX_PR_BASE}...{feature.branch}"
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
        "PRs target main. Approve with: git convoy aux approve (Full mode). "
        "Merge only when all sibling PRs are approved, in merge_order. "
        "git-convoy does not merge. After merge: git convoy aux close "
        "(merges main → develop)."
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
        "aux": feature.name,
        "branch": branch,
        "base": _AUX_PR_BASE,
        "merge_order": merge_sort(feature.repo_ids()),
        "ensure_develop": ensured_rows,
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
    feature = state.require_aux(name)
    if not feature.repos:
        raise GitConvoyError("aux has no participant repos; run aux adopt")
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
        merge_status = gitutil.pr_merge_status(
            repo_path, feature.branch, repo_row.pr, base=_AUX_PR_BASE
        )
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
        "aux": feature.name,
        "branch": feature.branch,
        "merge_order": order,
        "approved_count": approved_count,
        "repo_count": len(rows),
        "repos": rows,
        "note": (
            "Merge only when every sibling PR is approved, in merge_order. "
            "Merge into main. git-convoy does not merge. "
            "After merge: git convoy aux close."
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
    feature = state.require_aux(name)
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
    """Human caption for what to do next after ``aux show``."""
    if not rows:
        return "No participants yet. Run: git convoy aux adopt"
    statuses = {row["merge_status"] for row in rows}
    if statuses <= {"merged"}:
        return (
            "All participants merged into main. "
            "Run: git convoy aux close (merges main → develop)"
        )
    if "uncommitted" in statuses:
        return (
            "Uncommitted changes on one or more participants. "
            "Run: git convoy aux commit"
        )
    if "committed" in statuses and "pending" not in statuses:
        return (
            "Changes committed. Run: git convoy aux prs to open pull requests "
            "for these changes."
        )
    if "pending" in statuses:
        return (
            "PRs open (or recorded). Approve with: git convoy aux approve "
            "(Full mode), then merge in GitHub when every sibling is approved."
        )
    if "closed" in statuses:
        return (
            "One or more PRs were closed without merging. "
            "Re-open or run: git convoy aux prs"
        )
    return ""


def _merge_rows(workspace: Path, feature: Aux) -> list[dict]:
    rows: list[dict] = []
    for repo in feature.repos:
        repo_path = workspace / repo.path
        merge_status = gitutil.pr_merge_status(
            repo_path, feature.branch, repo.pr, base=_AUX_PR_BASE
        )
        rows.append(
            {
                "id": repo.id,
                "path": repo.path,
                "pr": repo.pr,
                "merge_status": merge_status,
            }
        )
    return rows


def _merge_main_into_develop(repo: Path, repo_id: str, *, push_remote: bool) -> dict:
    """Merge main into develop after aux work landed on main (hotfix-style)."""
    ensured = gitutil.ensure_develop(repo, push=push_remote and bool(gitutil.origin_url(repo)))
    if ensured.get("status") == "failed":
        return {
            "status": "failed",
            "synced": False,
            "error": ensured.get("error") or f"{repo_id}: cannot ensure develop",
        }
    gitutil.checkout_branch(repo, "main")
    if gitutil.rev_parse(repo, "origin/main"):
        pulled = gitutil.run(
            repo, "pull", "--ff-only", "origin", "main", check=False
        )
        if pulled.returncode != 0:
            return {
                "status": "failed",
                "synced": False,
                "error": f"{repo_id}: cannot fast-forward main",
            }
    gitutil.checkout_branch(repo, "develop")
    if gitutil.rev_parse(repo, "origin/develop"):
        pulled = gitutil.run(
            repo, "pull", "--ff-only", "origin", "develop", check=False
        )
        if pulled.returncode != 0:
            return {
                "status": "failed",
                "synced": False,
                "error": f"{repo_id}: cannot fast-forward develop",
            }
    if gitutil.is_ancestor(repo, "main", "develop"):
        return {"status": "already", "synced": True}
    merged = gitutil.merge(repo, "main")
    if merged.returncode != 0:
        gitutil.run(repo, "merge", "--abort", check=False)
        return {
            "status": "failed",
            "synced": False,
            "error": (merged.stderr or merged.stdout or "").strip(),
        }
    if push_remote and gitutil.origin_url(repo) and (
        gitutil.rev_parse(repo, "origin/develop") or ensured.get("created")
    ):
        gitutil.push(repo, "origin", "develop")
    return {"status": "merged", "synced": True}


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
    feature = state.require_aux(name)
    rows = _merge_rows(workspace, feature)
    pending = [row for row in rows if row["merge_status"] != "merged"]
    if pending:
        raise GitConvoyError(
            "not all participants merged into main: "
            + ", ".join(f"{row['id']} ({row['merge_status']})" for row in pending)
            + ". Run: git convoy aux show"
        )

    if not yes:
        if as_json or not (sys.stdin.isatty() if is_tty is None else is_tty):
            raise GitConvoyError("close removes the aux sheet; pass --yes to confirm")
        ids = ", ".join(row["id"] for row in rows) or "(none)"
        prompt = (
            f"This will merge main → develop in {len(rows)} repos ({ids}), "
            f"check out develop, "
        )
        if keep_branch:
            prompt += "and keep local aux branches. Continue? : "
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
                "aux": feature.name,
                "branch": feature.branch,
                "repos": [],
            }

    mergeback_rows: list[dict] = []
    mergeback_failed: list[str] = []
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
        mergeback = _merge_main_into_develop(
            repo_path,
            row["id"],
            push_remote=True,
        )
        item = {
            "id": row["id"],
            "path": row["path"],
            "merge_status": row["merge_status"],
            "mergeback": mergeback,
        }
        if mergeback.get("status") == "failed":
            item["error"] = mergeback.get("error")
            mergeback_failed.append(row["id"])
        mergeback_rows.append(item)

    if mergeback_failed:
        raise GitConvoyError(
            "main → develop mergeback failed in: "
            + ", ".join(mergeback_failed)
            + ". resolve on develop, then re-run: git convoy aux close --yes"
        )

    cleaned: list[dict] = []
    for item in mergeback_rows:
        repo_path = workspace / item["path"]
        deleted_local = False
        if not keep_branch and gitutil.has_local_branch(repo_path, feature.branch):
            if gitutil.current_branch(repo_path) == feature.branch:
                gitutil.checkout_branch(repo_path, "develop")
            gitutil.delete_branch(repo_path, feature.branch)
            deleted_local = True
        on_origin = gitutil.has_remote_branch(repo_path, feature.branch)
        deleted_remote = False
        if remote and on_origin:
            gitutil.delete_remote_branch(repo_path, feature.branch)
            deleted_remote = True
        if gitutil.current_branch(repo_path) != "develop":
            gitutil.checkout_branch(repo_path, "develop")
        cleaned.append(
            {
                **item,
                "branch": gitutil.current_branch(repo_path),
                "integration_branch": "develop",
                "deleted_local": deleted_local,
                "deleted_remote": deleted_remote,
                "on_origin": on_origin and not deleted_remote,
            }
        )

    if state.current_aux == feature.name:
        state.current_aux = None
    state.auxes.pop(feature.name, None)
    save(workspace, state)
    still_on_origin = [row["id"] for row in cleaned if row.get("on_origin")]
    note = (
        "Merged main → develop and checked out develop in every participant."
    )
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
        "aux": feature.name,
        "branch": feature.branch,
        "note": note,
        "repos": cleaned,
    }



def _push_aux_branches(workspace: Path, feature: Aux) -> list[dict]:
    if not feature.repos:
        raise GitConvoyError("aux has no participant repos; run aux adopt")
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


def _gh_create_pr(repo: Path, feature: Aux, slug: str) -> str | None:
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
        f"Part of cross-repo aux change `{feature.name}`.\n\n"
        f"Participants: {', '.join(feature.repo_ids()) or '(this repo)'}\n\n"
        "Merge into **main**. Do not merge until every sibling PR is approved. "
        "After merge: `git convoy aux close` (merges main → develop)."
    )
    created = subprocess.run(
        [
            gh,
            "pr",
            "create",
            "--repo",
            slug,
            "--base",
            _AUX_PR_BASE,
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



def promote(
    workspace: Path,
    state: State,
    name: str | None = None,
    *,
    use_gh: bool = True,
) -> dict:
    """Open or link develop→main PRs for aux participants ahead of main."""
    feature = state.require_aux(name)
    if not feature.repos:
        raise GitConvoyError("aux has no participant repos; run aux adopt")
    opened: list[dict] = []
    for repo_row in feature.repos:
        repo_path = workspace / repo_row.path
        gitutil.fetch(repo_path)
        if not gitutil.has_local_branch(repo_path, "develop") and not gitutil.has_remote_branch(
            repo_path, "develop"
        ):
            opened.append(
                {
                    "id": repo_row.id,
                    "path": repo_row.path,
                    "skipped": "no-develop",
                }
            )
            continue
        if not gitutil.has_local_branch(repo_path, "main") and not gitutil.has_remote_branch(
            repo_path, "main"
        ):
            opened.append(
                {
                    "id": repo_row.id,
                    "path": repo_row.path,
                    "skipped": "no-main",
                }
            )
            continue
        develop_ref = (
            "origin/develop"
            if gitutil.has_remote_branch(repo_path, "develop")
            else "develop"
        )
        main_ref = (
            "origin/main" if gitutil.has_remote_branch(repo_path, "main") else "main"
        )
        if not gitutil.ahead_of(repo_path, develop_ref, main_ref):
            opened.append(
                {
                    "id": repo_row.id,
                    "path": repo_row.path,
                    "skipped": "develop-not-ahead-of-main",
                }
            )
            continue
        slug = gitutil.github_slug(repo_path)
        pr_url = None
        compare = None
        if slug:
            compare = f"https://github.com/{slug}/compare/main...develop"
            if use_gh and gitutil.gh_bin():
                pr_url = _gh_create_promote_pr(repo_path, feature, slug)
        opened.append(
            {
                "id": repo_row.id,
                "path": repo_row.path,
                "pr": pr_url,
                "compare": compare,
            }
        )
    note = (
        "Promote is recovery only: opens develop→main PRs (or compare URLs) when "
        "develop is already ahead of main. Normal aux flow is aux prs → merge to "
        "main → aux close (main → develop)."
    )
    return {
        "ok": True,
        "aux": feature.name,
        "note": note,
        "repos": opened,
    }


def _gh_create_promote_pr(repo: Path, feature: Aux, slug: str) -> str | None:
    gh = gitutil.gh_bin()
    if not gh:
        return None
    existing = subprocess.run(
        [gh, "pr", "list", "--repo", slug, "--head", "develop", "--base", "main", "--json", "url"],
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
    title = f"Promote develop → main ({feature.name})"
    body = (
        f"Promote aux work from `{feature.name}` already on develop into main.\n\n"
        f"Participants: {', '.join(feature.repo_ids()) or '(this repo)'}"
    )
    created = subprocess.run(
        [
            gh,
            "pr",
            "create",
            "--repo",
            slug,
            "--base",
            "main",
            "--head",
            "develop",
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
    if slug.startswith("aux/"):
        slug = slug[len("aux/") :]
    if not slug:
        raise GitConvoyError("aux name is empty")
    return slug
