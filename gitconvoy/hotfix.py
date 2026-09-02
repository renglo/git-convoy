from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from gitconvoy import adopt as adopt_cmd
from gitconvoy import gitutil, versions
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import Hotfix, HotfixRepo, State, TrainRepo, save
from gitconvoy.workspace import product_repos, require_repo, merge_sort


def start(
    workspace: Path,
    state: State,
    name: str,
    repo_ids: list[str] | None = None,
) -> dict:
    slug = _slug(name)
    branch = f"hotfix/{slug}"
    hotfix = state.hotfixes.get(slug) or Hotfix(name=slug, branch=branch)
    state.hotfixes[slug] = hotfix
    state.current_hotfix = slug

    products = product_repos(workspace)
    if repo_ids:
        chosen = [require_repo(products, repo_id) for repo_id in repo_ids]
    else:
        chosen = [repo for repo in products if gitutil.is_dirty(repo.path)]
    if not chosen:
        raise GitConvoyError(
            "no dirty product repos; pass --repos or make the fix in at least one repo"
        )

    started: list[dict] = []
    for repo in chosen:
        started.append(_start_one(repo, hotfix))
    save(workspace, state)
    return {
        "ok": True,
        "hotfix": slug,
        "branch": branch,
        "repos": started,
        "repo_count": len(hotfix.repos),
        "note": (
            "PATCH bumped on hotfix/<name> from main. Commit next: "
            "git convoy hotfix commit. PRs target main, not develop."
        ),
    }


def _start_one(repo, hotfix: Hotfix) -> dict:
    gitutil.fetch(repo.path)
    if not _has_version(repo.path):
        raise GitConvoyError(
            f"{repo.id}: no version file; cannot hotfix a repo that does not publish"
        )
    current = gitutil.current_branch(repo.path)
    dirty = gitutil.is_dirty(repo.path)
    if current not in {"main", "develop", hotfix.branch}:
        raise GitConvoyError(
            f"{repo.id} has work on {current}, not main, develop, or {hotfix.branch}. "
            "commit/stash or checkout the right branch first"
        )

    origin_main = gitutil.rev_parse(repo.path, "origin/main")
    local_main = gitutil.rev_parse(repo.path, "refs/heads/main") or gitutil.rev_parse(
        repo.path, "main"
    )
    if not origin_main and not local_main:
        raise GitConvoyError(f"{repo.id}: no main branch; hotfix branches from main")

    existing = next((row for row in hotfix.repos if row.id == repo.id), None)
    if current != hotfix.branch:
        _checkout_main(
            repo.path, repo_id=repo.id, dirty=dirty, origin_main=origin_main
        )
        gitutil.checkout_branch(repo.path, hotfix.branch)

    if existing and existing.to and gitutil.current_branch(repo.path) == hotfix.branch:
        return {
            "id": repo.id,
            "path": repo.rel,
            "from": existing.from_version,
            "to": existing.to,
            "branch": hotfix.branch,
            "files": [],
            "dirty": gitutil.is_dirty(repo.path),
            "action": "already-on-hotfix",
        }

    info = versions.read_version(repo.path)
    current_version = info.get("python") or info.get("npm")
    if not current_version:
        raise GitConvoyError(f"{repo.id}: no version file")
    pep_now, _npm_now = _stable_pair(current_version)
    to = versions.bump(pep_now, "patch")
    pep, npm = versions.drop_rc(to)
    changed = versions.write_version(repo.path, pep, npm)
    row = hotfix.add_repo(
        HotfixRepo(
            id=repo.id,
            path=repo.rel,
            from_version=pep_now,
            to=pep,
            stable_tag=f"v{pep}",
        )
    )
    return {
        "id": repo.id,
        "path": repo.rel,
        "from": row.from_version,
        "to": row.to,
        "branch": hotfix.branch,
        "files": changed,
        "dirty": True,
    }


def _checkout_main(
    repo: Path, *, repo_id: str, dirty: bool, origin_main: str | None
) -> None:
    if gitutil.has_local_branch(repo, "main"):
        gitutil.checkout(repo, "main")
    elif origin_main:
        gitutil.run(repo, "checkout", "-B", "main", "origin/main")
    else:
        raise GitConvoyError(f"{repo_id}: cannot checkout main")
    head = gitutil.rev_parse(repo, "HEAD")
    if origin_main and head != origin_main:
        if dirty:
            raise GitConvoyError(
                f"{repo_id}: main is not at origin/main and the tree is dirty; "
                "stash, update main, then retry hotfix start"
            )
        pulled = gitutil.run(repo, "pull", "--ff-only", "origin", "main", check=False)
        if pulled.returncode != 0:
            raise GitConvoyError(
                f"{repo_id}: cannot fast-forward main from origin; "
                "fix main, then retry hotfix start"
            )


def commit_kind() -> str:
    return "hotfix"


def push(workspace: Path, state: State) -> dict:
    hotfix = state.require_hotfix()
    if not hotfix.repos:
        raise GitConvoyError("hotfix has no participant repos; run hotfix start")
    rows = _push_branches(workspace, hotfix)
    return {
        "ok": True,
        "hotfix": hotfix.name,
        "branch": hotfix.branch,
        "note": (
            "Pushed hotfix branches to origin. No PRs opened. "
            "Uncommitted files are not on the remote."
        ),
        "repos": rows,
    }


def prs(workspace: Path, state: State, use_gh: bool = True) -> dict:
    hotfix = state.require_hotfix()
    if not hotfix.repos:
        raise GitConvoyError("hotfix has no participant repos; run hotfix start")
    _push_branches(workspace, hotfix)
    opened: list[dict] = []
    order = merge_sort(hotfix.repo_ids())
    for repo_row in hotfix.repos:
        repo_path = workspace / repo_row.path
        url = repo_row.pr
        slug = gitutil.github_slug(repo_path)
        if use_gh and gitutil.gh_bin() and slug:
            created = _gh_create_pr(repo_path, hotfix, slug)
            if created:
                url = created
                repo_row.pr = created
        compare = None
        if slug:
            compare = (
                f"https://github.com/{slug}/compare/main...{hotfix.branch}"
            )
        opened.append(
            {
                "id": repo_row.id,
                "path": repo_row.path,
                "pr": url,
                "compare": compare,
                "merge_order": order.index(repo_row.id) if repo_row.id in order else None,
            }
        )
    hotfix.status = "in-review"
    save(workspace, state)
    return {
        "ok": True,
        "hotfix": hotfix.name,
        "branch": hotfix.branch,
        "merge_order": order,
        "note": (
            "Merge PRs into main (merge_order). git-convoy does not merge. "
            "Then: git convoy hotfix publish"
        ),
        "repos": opened,
    }


def publish(workspace: Path, state: State, push_remote: bool = True) -> dict:
    hotfix = state.require_hotfix()
    if not hotfix.repos:
        raise GitConvoyError("hotfix has no participant repos; run hotfix start")
    published: list[dict] = []
    for repo_row in _ordered(hotfix):
        repo_path = workspace / repo_row.path
        gitutil.fetch(repo_path)
        if gitutil.is_dirty(repo_path):
            raise GitConvoyError(f"{repo_row.id} is dirty; commit or stash before publish")
        _require_merged_to_main(
            repo_path, hotfix.branch, repo_row.id, expected=repo_row.to
        )
        gitutil.checkout(repo_path, "main")
        if gitutil.rev_parse(repo_path, "origin/main"):
            pulled = gitutil.run(
                repo_path, "pull", "--ff-only", "origin", "main", check=False
            )
            if pulled.returncode != 0:
                raise GitConvoyError(
                    f"{repo_row.id}: cannot fast-forward main; merge the PR, then retry"
                )
        info = versions.read_version(repo_path)
        current = info.get("python") or info.get("npm")
        if not current:
            raise GitConvoyError(f"{repo_row.id}: no version file on main")
        pep, _npm = _stable_pair(current)
        if repo_row.to and pep != _stable_pair(repo_row.to)[0]:
            raise GitConvoyError(
                f"{repo_row.id}: main is {pep}, expected hotfix version {repo_row.to}"
            )
        tag = f"v{pep}"
        if not gitutil.rev_parse(repo_path, f"refs/tags/{tag}"):
            gitutil.run(repo_path, "tag", tag)
        if push_remote and gitutil.origin_url(repo_path):
            gitutil.push(repo_path, "origin", "main")
            gitutil.push(repo_path, "origin", tag)
        repo_row.to = pep
        repo_row.stable_tag = tag
        develop = _merge_main_into_develop(repo_path, repo_row.id, push_remote)
        absorbed = _absorb_feature_branches(repo_path, repo_row.id)
        published.append(
            {
                "id": repo_row.id,
                "path": repo_row.path,
                "tag": tag,
                "version": pep,
                "develop": develop,
                "feature_branches": absorbed,
            }
        )
    hotfix.status = "published"
    save(workspace, state)
    failed_develop = [
        row["id"]
        for row in published
        if (row.get("develop") or {}).get("status") == "failed"
    ]
    failed_absorb = [
        f"{row['id']}:{item['branch']}"
        for row in published
        for item in row["feature_branches"]
        if not item.get("ok")
    ]
    note = (
        "Stable tags are on main; develop has the patch. "
        "In-progress feature/* branches were merged from develop where possible. "
        "Next: git convoy hotfix adopt --bom ops/<system>-bom"
    )
    if failed_develop:
        note += (
            " develop merge failed in: "
            + ", ".join(failed_develop)
            + ". resolve, then retry hotfix publish or merge main into develop by hand."
        )
    if failed_absorb:
        note += (
            " Feature-branch merge conflicts: "
            + ", ".join(failed_absorb)
            + ". resolve, then git convoy feature refresh."
        )
    return {
        "ok": not failed_absorb and not failed_develop,
        "hotfix": hotfix.name,
        "branch": hotfix.branch,
        "repos": published,
        "note": note,
    }


def adopt(
    workspace: Path,
    state: State,
    *,
    bom: str | None = None,
    from_version: str | None = None,
    to_version: str | None = None,
    description: str | None = None,
) -> dict:
    hotfix = state.require_hotfix()
    if hotfix.status != "published":
        raise GitConvoyError(
            f"hotfix {hotfix.name} is {hotfix.status}; run hotfix publish before adopt"
        )
    if not hotfix.repos:
        raise GitConvoyError("hotfix has no participant repos")
    missing = [repo.id for repo in hotfix.repos if not repo.to]
    if missing:
        raise GitConvoyError(
            "hotfix has no versions to pin for: " + ", ".join(missing)
        )
    root = adopt_cmd.find_bom_repo(workspace, bom)
    pointed = adopt_cmd._pointed_version(root)
    src = from_version or pointed
    dest = to_version or versions.bump(adopt_cmd._strip_v(src), "patch")
    dest = adopt_cmd._strip_v(dest)
    dest_path = adopt_cmd._bom_file(root, dest)
    if dest_path.exists() and dest != adopt_cmd._strip_v(src):
        # already drafted this patch; reuse
        pass
    elif dest_path.exists() and dest == adopt_cmd._strip_v(src):
        dest = versions.bump(dest, "patch")
        dest_path = adopt_cmd._bom_file(root, dest)
    if not dest_path.exists():
        ids = ", ".join(hotfix.repo_ids())
        adopt_cmd.draft(
            workspace,
            state,
            src,
            dest,
            bom=bom,
            description=description
            or f"Draft. Hotfix {hotfix.name} ({ids}). Not production.",
        )
    pins: list[dict] = []
    for repo_row in hotfix.repos:
        pep, npm = _stable_pair(repo_row.to or "")
        fake = TrainRepo(id=repo_row.id, path=repo_row.path, to=pep)
        for section, package in _hotfix_package_targets(fake, workspace):
            pin_value = npm if section == "npm" else pep
            adopt_cmd.pin(
                workspace,
                dest,
                package,
                pin_value,
                bom=bom,
                ecosystem=section,
            )
            pins.append(
                {
                    "id": repo_row.id,
                    "section": section,
                    "package": package,
                    "pin": pin_value,
                }
            )
    pointed_out = adopt_cmd.point(workspace, dest, bom=bom, production=False)
    return {
        "ok": True,
        "hotfix": hotfix.name,
        "version": adopt_cmd._v(dest),
        "from": str(adopt_cmd._bom_file(root, src)),
        "to": str(dest_path),
        "pins": pins,
        "point": pointed_out,
        "note": pointed_out["note"],
    }


def show(workspace: Path, state: State, name: str | None = None) -> dict:
    hotfix = state.require_hotfix(name)
    rows = []
    for repo_row in hotfix.repos:
        repo_path = workspace / repo_row.path
        main_tip = gitutil.rev_parse(repo_path, "origin/main") or gitutil.rev_parse(
            repo_path, "main"
        )
        merged = False
        if main_tip:
            merged = gitutil.branch_merged_into(
                repo_path, hotfix.branch, base=main_tip
            )
        rows.append(
            {
                "id": repo_row.id,
                "path": repo_row.path,
                "from": repo_row.from_version,
                "to": repo_row.to,
                "stable_tag": repo_row.stable_tag,
                "pr": repo_row.pr,
                "merge_status": "merged" if merged else "pending",
            }
        )
    return {
        "ok": True,
        "name": hotfix.name,
        "branch": hotfix.branch,
        "status": hotfix.status,
        "repo_count": len(hotfix.repos),
        "merge_order": merge_sort(hotfix.repo_ids()),
        "repos": rows,
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
    hotfix = state.require_hotfix(name)
    branch = hotfix.branch
    if not yes:
        if as_json or not (sys.stdin.isatty() if is_tty is None else is_tty):
            raise GitConvoyError(
                "abandon discards the hotfix branch; pass --yes to confirm"
            )
        ids = ", ".join(hotfix.repo_ids()) or "(none)"
        prompt = (
            f"This will delete local branch {branch} in {len(hotfix.repos)} repos "
            f"({ids}) and discard uncommitted work on that branch. Continue? : "
        )
        answer = (input_fn or input)(prompt).strip().lower()
        if answer not in {"yes", "y"}:
            return {
                "ok": True,
                "abandoned": False,
                "hotfix": hotfix.name,
                "branch": branch,
                "repos": [],
            }

    removed: list[dict] = []
    products = {repo.id: repo for repo in product_repos(workspace)}
    for repo_row in hotfix.repos:
        product = products.get(repo_row.id)
        repo_path = product.path if product else workspace / repo_row.path
        gitutil.fetch(repo_path)
        on_origin = gitutil.has_remote_branch(repo_path, branch)
        dirty = gitutil.is_dirty(repo_path)
        current = gitutil.current_branch(repo_path)
        if current == branch:
            gitutil.reset_hard(repo_path, "HEAD")
            gitutil.clean_untracked(repo_path)
        gitutil.checkout_integration(repo_path)
        deleted_local = False
        if gitutil.has_local_branch(repo_path, branch):
            gitutil.delete_branch(repo_path, branch)
            deleted_local = True
        deleted_remote = False
        if remote and on_origin:
            gitutil.delete_remote_branch(repo_path, branch)
            deleted_remote = True
        removed.append(
            {
                "id": repo_row.id,
                "path": repo_row.path,
                "deleted_local": deleted_local,
                "deleted_remote": deleted_remote,
                "on_origin": on_origin and not deleted_remote,
                "discarded_dirty": dirty and current == branch,
                "branch": gitutil.current_branch(repo_path),
            }
        )
    if state.current_hotfix == hotfix.name:
        state.current_hotfix = None
    state.hotfixes.pop(hotfix.name, None)
    save(workspace, state)
    return {
        "ok": True,
        "abandoned": True,
        "hotfix": hotfix.name,
        "branch": branch,
        "repos": removed,
        "note": "Local hotfix branches deleted. Checked out the integration branch.",
    }


def _push_branches(workspace: Path, hotfix: Hotfix) -> list[dict]:
    rows: list[dict] = []
    failed: list[str] = []
    for repo_row in hotfix.repos:
        repo_path = workspace / repo_row.path
        gitutil.checkout_branch(repo_path, hotfix.branch)
        dirty = gitutil.is_dirty(repo_path)
        item: dict = {
            "id": repo_row.id,
            "path": repo_row.path,
            "branch": hotfix.branch,
            "dirty": dirty,
            "ok": True,
        }
        try:
            gitutil.push(repo_path, "-u", "origin", hotfix.branch)
        except GitConvoyError as exc:
            item["ok"] = False
            item["error"] = exc.message
            failed.append(repo_row.id)
        rows.append(item)
    if failed:
        raise GitConvoyError("push failed in: " + ", ".join(failed))
    return rows


def _gh_create_pr(repo: Path, hotfix: Hotfix, slug: str) -> str | None:
    gh = gitutil.gh_bin()
    if not gh:
        return None
    existing = subprocess.run(
        [gh, "pr", "list", "--repo", slug, "--head", hotfix.branch, "--json", "url"],
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
    ids = ", ".join(hotfix.repo_ids()) or "(this repo)"
    body = (
        f"Production hotfix `{hotfix.name}`.\n\n"
        f"Participants: {ids}\n\n"
        "Merge into **main**. git-convoy does not merge. "
        "After merge: `git convoy hotfix publish`."
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
            hotfix.branch,
            "--title",
            hotfix.branch,
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


def _require_merged_to_main(
    repo: Path, branch: str, repo_id: str, expected: str | None = None
) -> None:
    main_tip = gitutil.rev_parse(repo, "origin/main") or gitutil.rev_parse(repo, "main")
    if not main_tip:
        raise GitConvoyError(f"{repo_id}: no main branch")
    if gitutil.branch_merged_into(repo, branch, base=main_tip):
        return
    if expected:
        gitutil.checkout(repo, "main")
        info = versions.read_version(repo)
        current = info.get("python") or info.get("npm")
        if current and _stable_pair(current)[0] == _stable_pair(expected)[0]:
            return
    raise GitConvoyError(
        f"{repo_id}: {branch} is not on main. Merge the PR, then git convoy hotfix publish"
    )


def _merge_main_into_develop(repo: Path, repo_id: str, push_remote: bool) -> dict:
    has_develop = gitutil.has_local_branch(repo, "develop") or gitutil.has_remote_branch(
        repo, "develop"
    )
    if not has_develop:
        return {"status": "skipped", "synced": False}
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
    if push_remote and gitutil.origin_url(repo) and gitutil.rev_parse(repo, "origin/develop"):
        gitutil.push(repo, "origin", "develop")
    return {"status": "merged", "synced": True}


def _absorb_feature_branches(repo: Path, repo_id: str) -> list[dict]:
    """Merge updated develop into local feature/* so in-progress work gets the patch."""
    results: list[dict] = []
    previous = gitutil.current_branch(repo)
    dirty = gitutil.is_dirty(repo)
    develop_ref = (
        "origin/develop" if gitutil.rev_parse(repo, "origin/develop") else "develop"
    )
    if not gitutil.rev_parse(repo, develop_ref):
        return results
    for branch in gitutil.local_branches(repo, "feature/"):
        if dirty and gitutil.current_branch(repo) == branch:
            results.append(
                {
                    "branch": branch,
                    "ok": False,
                    "status": "dirty",
                    "error": f"{repo_id} {branch} is dirty; stash, then feature refresh",
                }
            )
            continue
        gitutil.checkout(repo, branch)
        if gitutil.is_ancestor(repo, develop_ref, branch):
            results.append({"branch": branch, "ok": True, "status": "already"})
            continue
        merged = gitutil.merge(repo, develop_ref)
        if merged.returncode != 0:
            gitutil.run(repo, "merge", "--abort", check=False)
            results.append(
                {
                    "branch": branch,
                    "ok": False,
                    "status": "conflict",
                    "error": (merged.stderr or merged.stdout or "").strip(),
                }
            )
            continue
        results.append({"branch": branch, "ok": True, "status": "merged"})
    if gitutil.has_local_branch(repo, previous):
        gitutil.checkout(repo, previous)
    elif gitutil.has_local_branch(repo, "develop"):
        gitutil.checkout(repo, "develop")
    return results


def _hotfix_package_targets(repo: TrainRepo, workspace: Path) -> list[tuple[str, str]]:
    from gitconvoy.adopt import _npm_package_names, _python_package_names

    info = versions.read_version(workspace / repo.path)
    targets: list[tuple[str, str]] = []
    if info.get("python"):
        names = _python_package_names(repo.id)
        if names:
            targets.append(("python", names[0]))
    if info.get("npm"):
        names = _npm_package_names(repo, workspace)
        if names:
            targets.append(("npm", names[0]))
    return targets


def _ordered(hotfix: Hotfix) -> list[HotfixRepo]:
    order = {name: index for index, name in enumerate(merge_sort(hotfix.repo_ids()))}
    return sorted(hotfix.repos, key=lambda row: order.get(row.id, 99))


def _has_version(repo: Path) -> bool:
    info = versions.read_version(repo)
    return bool(info.get("python") or info.get("npm"))


def _stable_pair(version: str) -> tuple[str, str]:
    return versions.drop_rc(version)


def _slug(name: str) -> str:
    slug = name.strip().replace(" ", "-")
    if slug.startswith("hotfix/"):
        slug = slug[len("hotfix/") :]
    if not slug:
        raise GitConvoyError("hotfix name is empty")
    return slug
