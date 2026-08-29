from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from gitconvoy import gitutil
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import Feature, State, save
from gitconvoy.workspace import Repo, merge_sort, product_repos


def start(workspace: Path, state: State, name: str) -> dict:
    slug = _slug(name)
    branch = f"feature/{slug}"
    if slug not in state.features:
        state.features[slug] = Feature(name=slug, branch=branch)
    state.current_feature = slug
    save(workspace, state)
    checked: list[dict] = []
    for repo in product_repos(workspace):
        if gitutil.is_dirty(repo.path):
            checked.append(
                {
                    "id": repo.id,
                    "path": repo.rel,
                    "skipped": "dirty",
                    "branch": gitutil.current_branch(repo.path),
                }
            )
            continue
        gitutil.fetch(repo.path)
        if gitutil.rev_parse(repo.path, "origin/develop") or gitutil.rev_parse(
            repo.path, "develop"
        ):
            if gitutil.rev_parse(repo.path, "origin/develop"):
                gitutil.checkout(repo.path, "develop")
                gitutil.run(repo.path, "pull", "--ff-only", "origin", "develop", check=False)
            else:
                gitutil.checkout(repo.path, "develop")
        checked.append(
            {
                "id": repo.id,
                "path": repo.rel,
                "branch": gitutil.current_branch(repo.path),
            }
        )
    return {
        "ok": True,
        "feature": slug,
        "branch": branch,
        "repos": [],
        "workspace": checked,
    }


def adopt(workspace: Path, state: State) -> dict:
    feature = state.require_feature()
    adopted: list[dict] = []
    skipped: list[dict] = []
    for repo in product_repos(workspace):
        result = _adopt_one(repo, feature)
        if result.get("adopted"):
            feature.add_repo(repo.id, repo.rel)
            adopted.append(result)
        else:
            skipped.append(result)
    save(workspace, state)
    return {
        "ok": True,
        "feature": feature.name,
        "branch": feature.branch,
        "adopted": adopted,
        "skipped": skipped,
        "repo_count": len(feature.repos),
    }


def _adopt_one(repo: Repo, feature: Feature) -> dict:
    branch = feature.branch
    current = gitutil.current_branch(repo.path)
    dirty = gitutil.is_dirty(repo.path)
    gitutil.fetch(repo.path)
    origin_dev = gitutil.rev_parse(repo.path, "origin/develop")
    on_develop = current == "develop"
    ahead = bool(
        origin_dev
        and on_develop
        and gitutil.ahead_of(repo.path, "HEAD", "origin/develop")
    )

    if current == branch:
        if dirty or repo.id in feature.repo_ids():
            return {
                "id": repo.id,
                "path": repo.rel,
                "adopted": True,
                "action": "already-on-feature",
                "dirty": dirty,
            }
        return {
            "id": repo.id,
            "path": repo.rel,
            "adopted": False,
            "reason": "on-feature-no-changes",
        }

    if not dirty and not ahead:
        return {
            "id": repo.id,
            "path": repo.rel,
            "adopted": False,
            "reason": "unchanged",
            "branch": current,
        }

    if not on_develop and current != branch:
        raise GitConvoyError(
            f"{repo.id} has work on {current}, not develop or {branch}. "
            "commit/stash or checkout the right branch first"
        )

    gitutil.checkout_branch(repo.path, branch)

    if ahead and origin_dev and gitutil.rev_parse(repo.path, "refs/heads/develop"):
        if not gitutil.is_ancestor(repo.path, "origin/develop", branch):
            raise GitConvoyError(
                f"{repo.id}: develop has diverged from origin/develop"
            )
        gitutil.checkout(repo.path, "develop")
        if gitutil.rev_parse(repo.path, "HEAD") == origin_dev:
            gitutil.checkout(repo.path, branch)
        else:
            if gitutil.ahead_of(repo.path, "develop", "origin/develop"):
                gitutil.reset_hard(repo.path, "origin/develop")
            gitutil.checkout(repo.path, branch)

    return {
        "id": repo.id,
        "path": repo.rel,
        "adopted": True,
        "action": "branched",
        "dirty": dirty,
        "reset_develop": bool(ahead),
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
            gitutil.checkout(repo.path, "develop")
        elif gitutil.has_local_branch(repo.path, "develop") or gitutil.rev_parse(
            repo.path, "origin/develop"
        ):
            gitutil.checkout_branch(repo.path, "develop")
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
        "Local feature branches deleted. Check out develop. "
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

    products = product_repos(workspace)
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
    repos = product_repos(workspace)
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
            if gitutil.rev_parse(repo.path, "refs/heads/develop") or gitutil.rev_parse(
                repo.path, "origin/develop"
            ):
                gitutil.checkout_branch(repo.path, "develop")
            switched.append(
                {
                    "id": repo.id,
                    "path": repo.rel,
                    "branch": gitutil.current_branch(repo.path),
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
        gitutil.checkout_branch(repo_path, feature.branch)
        gitutil.fetch(repo_path)
        merged = gitutil.merge(repo_path, "origin/develop")
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
            compare = (
                f"https://github.com/{slug}/compare/develop...{feature.branch}"
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
    return {
        "ok": True,
        "feature": feature.name,
        "merge_order": merge_sort(feature.repo_ids()),
        "note": (
            "Approve every sibling PR in the GitHub UI. Merge only when all "
            "are approved, in merge_order. git-convoy does not approve or merge."
        ),
        "repos": opened,
    }


def show(state: State, name: str | None = None) -> dict:
    feature = state.require_feature(name)
    return {
        "ok": True,
        "name": feature.name,
        "branch": feature.branch,
        "status": feature.status,
        "repo_count": len(feature.repos),
        "repos": [
            {"id": repo.id, "path": repo.path, "pr": repo.pr}
            for repo in feature.repos
        ],
        "merge_order": merge_sort(feature.repo_ids()),
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
    created = subprocess.run(
        [
            gh,
            "pr",
            "create",
            "--repo",
            slug,
            "--base",
            "develop",
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
