from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from gitconvoy import ghutil
from gitconvoy import gitutil, versions
from gitconvoy.sync import DevelopSyncEntry, format_develop_sync_text, sync_repos_develop
from gitconvoy.workflows import repo_publishes_on_tag, tag_push_workflows
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import Feature, State, Train, TrainRepo, save
from gitconvoy.workspace import (
    Repo,
    ops_repos,
    bom_repos,
    merge_sort,
    product_repos,
    require_repo,
)


def _has_version(repo: Path) -> bool:
    info = versions.read_version(repo)
    return bool(info.get("python") or info.get("npm"))


def _is_renglo_ops(repo_id: str, rel: str) -> bool:
    return repo_id == "renglo-ops" or Path(str(rel)).name == "renglo-ops"


def _platform_for_repo(repo_id: str, rel: str, platform: str) -> str | None:
    """renglo-ops is the platform. Other packages declare the platform they target."""
    if _is_renglo_ops(repo_id, rel):
        return None
    return platform or None


def _packages_platform(
    workspace: Path,
    repos: list,
    *,
    bump: str = "patch",
    choose_rc: bool = False,
) -> str:
    """Stable platform version the packages on this train should declare."""
    for repo in repos:
        ident = str(getattr(repo, "id", ""))
        rel = str(getattr(repo, "rel", "") or getattr(repo, "path", ""))
        if not _is_renglo_ops(ident, rel):
            continue
        path = getattr(repo, "path")
        directory = path if isinstance(path, Path) and path.is_absolute() else workspace / str(path)
        info = versions.read_version(directory)
        current = info.get("python") or info.get("npm")
        if not current:
            return ""
        if choose_rc:
            pep, _npm, _tag = _choose_rc(directory, current)
            return versions.drop_rc(pep)[0]
        return versions.drop_rc(versions.bump(current, bump))[0]
    return _bom_declared_platform(workspace)


def _bom_declared_platform(workspace: Path) -> str:
    from gitconvoy.adopt import find_bom_repo
    from gitconvoy.bom_layout import load_platform, load_staging_platform

    try:
        root = find_bom_repo(workspace)
    except GitConvoyError:
        return ""
    pin = load_staging_platform(root) or load_platform(root)
    if not pin:
        return ""
    try:
        return versions.drop_rc(pin)[0]
    except GitConvoyError:
        return ""


def cut(
    workspace: Path,
    state: State,
    name: str,
    bump: str = "patch",
    repo_ids: list[str] | None = None,
    no_bump: bool = False,
) -> dict:
    slug = _slug(name)
    branch = f"release/{slug}"
    repos = product_repos(workspace)
    skipped: list[dict] = []
    if repo_ids:
        chosen = [require_repo(repos, repo_id) for repo_id in repo_ids]
        for repo in chosen:
            if not _has_version(repo.path):
                raise GitConvoyError(
                    f"{repo.id}: no version file; cannot cut a release train for this repo"
                )
    else:
        chosen = []
        for repo in repos:
            if not gitutil.develop_ahead_of_stable(repo.path):
                continue
            if not _has_version(repo.path):
                skipped.append(
                    {
                        "id": repo.id,
                        "path": repo.rel,
                        "reason": "no-version-file",
                    }
                )
                continue
            chosen.append(repo)
    if not chosen:
        if skipped:
            ids = ", ".join(item["id"] for item in skipped)
            raise GitConvoyError(
                "no publishable repos are ahead of their last stable tag "
                f"(skipped without version files: {ids})"
            )
        raise GitConvoyError(
            "no repos are ahead of their last stable tag; pass --repos to force"
        )
    train = state.trains.get(slug) or Train(name=slug, branch=branch)
    train.status = "cut"
    platform = "" if no_bump else _packages_platform(workspace, chosen, bump=bump)
    added: list[dict] = []
    for repo in chosen:
        gitutil.fetch(repo.path)
        if gitutil.is_dirty(repo.path):
            raise GitConvoyError(f"{repo.id} is dirty; commit or stash before train cut")
        gitutil.checkout_integration(repo.path)
        gitutil.checkout_branch(repo.path, branch)
        info = versions.read_version(repo.path)
        current = info.get("python") or info.get("npm")
        to = None
        changed: list[str] = []
        if current and not no_bump:
            to = versions.bump(current, bump)
            pep, npm = versions.with_rc(to, 1)
            changed = versions.write_version(
                repo.path,
                pep,
                npm,
                platform=_platform_for_repo(repo.id, repo.rel, platform),
            )
            gitutil.run(repo.path, "add", "-A")
            gitutil.run(
                repo.path,
                "commit",
                "-m",
                f"Set {pep} for train {slug}",
            )
            to = pep
        row = TrainRepo(
            id=repo.id,
            path=repo.rel,
            from_version=current,
            to=to,
        )
        train.add_repo(row)
        added.append(
            {
                "id": repo.id,
                "path": repo.rel,
                "from": current,
                "to": to,
                "files": changed,
            }
        )
    state.trains[slug] = train
    state.current_train = slug
    save(workspace, state)
    return {
        "ok": True,
        "train": slug,
        "branch": branch,
        "repos": added,
        "skipped": skipped,
    }


def adopt(
    workspace: Path,
    state: State,
    repo_ids: list[str] | None = None,
) -> dict:
    """Add product repos to the current train without bumping versions.

    Default: dirty product repos on develop/main or ``release/<train>``.
    ``--repos`` force-includes those ids even when clean. Ops and BOM are
    ignored. Does not rewrite ``from``/``to`` for repos already on the sheet.
    """
    train = state.require_train()
    if train.status not in {"cut", "stabilizing"}:
        raise GitConvoyError(
            f"train {train.name} is {train.status}; "
            "adopt only runs while the train is cut or stabilizing"
        )
    products = product_repos(workspace)
    skipped: list[dict] = []
    if repo_ids:
        chosen = [_require_product(workspace, repo_id) for repo_id in repo_ids]
        for repo in chosen:
            if not _has_version(repo.path):
                raise GitConvoyError(
                    f"{repo.id}: no version file; cannot add this repo to a release train"
                )
    else:
        chosen = []
        for repo in products:
            if not gitutil.is_dirty(repo.path):
                continue
            if not _has_version(repo.path):
                skipped.append(
                    {
                        "id": repo.id,
                        "path": repo.rel,
                        "reason": "no-version-file",
                    }
                )
                continue
            chosen.append(repo)
    if not chosen:
        if skipped:
            ids = ", ".join(item["id"] for item in skipped)
            raise GitConvoyError(
                "no dirty publishable product repos "
                f"(skipped without version files: {ids}); pass --repos to force"
            )
        raise GitConvoyError(
            "no dirty product repos; pass --repos to add a clean product repo "
            "to the train"
        )

    adopted: list[dict] = []
    force = bool(repo_ids)
    for repo in chosen:
        result = _adopt_one(repo, train, force=force)
        if result.get("adopted"):
            _ensure_train_row(repo, train)
            adopted.append(result)
            continue
        skipped.append(result)
    save(workspace, state)
    return {
        "ok": True,
        "train": train.name,
        "branch": train.branch,
        "adopted": adopted,
        "skipped": skipped,
        "repo_count": len(train.repos),
        "note": (
            "No versions bumped. Commit with git convoy train commit, "
            "then git convoy train tag-rc."
        ),
    }


def _train_version_commit(subject: str, train_name: str) -> bool:
    return subject.startswith("Set ") and subject.endswith(f" for train {train_name}")


def _train_platform_restore_commit(subject: str, train_name: str) -> bool:
    return subject == f"Restore platform after renglo-ops left train {train_name}"


def unadopt(
    workspace: Path,
    state: State,
    repo_ids: list[str] | None = None,
) -> dict:
    """Remove repos from the current train without discarding their work.

    Commits on ``release/<train>`` other than the automatic version bump are
    merged into the integration branch. The version bump stays off that branch
    so the next train can cut it again. The local release branch is then deleted.

    Removing ``renglo-ops`` puts every other package's platform declaration
    back to the value on its integration branch. Cut stamps the bumped
    renglo-ops version into those files; once renglo-ops leaves, that stamp
    is no longer the platform this train ships.
    """
    ids = [item.strip() for item in (repo_ids or []) if item.strip()]
    if not ids:
        raise GitConvoyError("pass --repos")
    train = state.require_train()
    if train.status not in {"cut", "stabilizing"}:
        raise GitConvoyError(
            f"train {train.name} is {train.status}; "
            "unadopt only runs while the train is cut or stabilizing"
        )
    rows: list[TrainRepo] = []
    seen: set[str] = set()
    for repo_id in ids:
        if repo_id in seen:
            continue
        seen.add(repo_id)
        row = next((item for item in train.repos if item.id == repo_id), None)
        if row is None:
            raise GitConvoyError(f"{repo_id} is not on train {train.name}")
        if row.rc_tag or row.stable_tag:
            raise GitConvoyError(
                f"{repo_id} already has a train tag; unadopt only runs before tag-rc"
            )
        if gitutil.is_dirty(workspace / row.path):
            raise GitConvoyError(
                f"{repo_id} is dirty; commit or stash before train unadopt"
            )
        rows.append(row)

    removing_ops = any(_is_renglo_ops(row.id, row.path) for row in rows)
    platform_restored: list[dict] = []
    if removing_ops:
        leaving = {row.id for row in rows}
        for repo in train.repos:
            if repo.id in leaving:
                continue
            if gitutil.is_dirty(workspace / repo.path):
                raise GitConvoyError(
                    f"{repo.id} is dirty; commit or stash before removing renglo-ops"
                )
        for repo in list(train.repos):
            if repo.id in leaving:
                continue
            restored = _restore_platform_on_release(workspace / repo.path, train)
            if restored:
                platform_restored.append({"id": repo.id, **restored})

    removed: list[dict] = []
    for row in rows:
        removed.append(
            _unadopt_one(
                workspace / row.path,
                train,
                row,
                restore_platform=(
                    removing_ops and not _is_renglo_ops(row.id, row.path)
                ),
            )
        )
        train.drop_repo(row.id)
        save(workspace, state)
    return {
        "ok": True,
        "train": train.name,
        "branch": train.branch,
        "removed": removed,
        "platform_restored": platform_restored,
        "repo_count": len(train.repos),
    }


def _unadopt_one(
    repo_path: Path,
    train: Train,
    row: TrainRepo,
    *,
    restore_platform: bool = False,
) -> dict:
    branch = train.branch
    integration = gitutil.integration_branch(repo_path)
    merged_commits = 0
    restored = False
    platform_restore = ""
    if gitutil.has_local_branch(repo_path, branch):
        base = gitutil.rev_parse(repo_path, integration) or ""
        unique = gitutil.commits_not_in(repo_path, branch, integration)
        code = [
            sha
            for sha in unique
            if not _train_version_commit(
                gitutil.commit_oneline(repo_path, sha)["subject"], train.name
            )
            and not _train_platform_restore_commit(
                gitutil.commit_oneline(repo_path, sha)["subject"], train.name
            )
        ]
        gitutil.checkout_integration(repo_path)
        if code:
            merged = gitutil.merge(repo_path, branch)
            if merged.returncode != 0:
                gitutil.run(repo_path, "merge", "--abort", check=False)
                raise GitConvoyError(
                    f"{row.id}: merge {branch} into {integration} failed. "
                    f"{row.id} is still on the train."
                )
            merged_commits = len(code)
            restored = _restore_pre_train_version(repo_path, base, train.name)
            if restore_platform and base:
                restored_decl = _commit_platform_restore(
                    repo_path, base, train.name
                )
                if restored_decl:
                    platform_restore = restored_decl["platform"] or "cleared"
        if gitutil.has_local_branch(repo_path, branch):
            if merged_commits:
                gitutil.delete_merged_branch(repo_path, branch)
            else:
                gitutil.delete_branch(repo_path, branch)
    else:
        gitutil.checkout_integration(repo_path)
    result = {
        "id": row.id,
        "branch": gitutil.current_branch(repo_path),
        "merged_commits": merged_commits,
        "restored_version": restored,
        "deleted_local": not gitutil.has_local_branch(repo_path, branch),
        "on_origin": gitutil.has_remote_branch(repo_path, branch),
        "release_branch": branch,
    }
    if platform_restore:
        result["platform_restore"] = platform_restore
    return result


def _restore_platform_on_release(repo_path: Path, train: Train) -> dict | None:
    """Commit the pre-train platform back onto the release branch."""
    branch = train.branch
    if not gitutil.has_local_branch(repo_path, branch):
        return None
    integration = gitutil.integration_branch(repo_path)
    base = gitutil.rev_parse(repo_path, integration) or ""
    if not base:
        return None
    gitutil.checkout_branch(repo_path, branch)
    return _commit_platform_restore(repo_path, base, train.name)


def _commit_platform_restore(repo_path: Path, ref: str, train_name: str) -> dict | None:
    restored = _rewrite_platforms_from_ref(repo_path, ref)
    if not restored:
        return None
    gitutil.run(repo_path, "add", *restored["files"])
    if not gitutil.has_tracked_changes(repo_path):
        return None
    gitutil.run(
        repo_path,
        "commit",
        "-m",
        f"Restore platform after renglo-ops left train {train_name}",
    )
    return restored


def _rewrite_platforms_from_ref(repo_path: Path, ref: str) -> dict | None:
    """Point platform declarations at the values in ``ref``. Empty means unset."""
    from gitconvoy.platform_check import (
        declared_platform_package_json,
        declared_platform_pyproject,
    )

    changed: list[str] = []
    targets: list[str] = []
    for rel in _platform_declaration_files(repo_path):
        path = repo_path / rel
        if not path.is_file():
            continue
        current_text = path.read_text()
        shown = gitutil.run(repo_path, "show", f"{ref}:{rel}", check=False)
        original_text = shown.stdout or "" if shown.returncode == 0 else ""
        current = _declared_platform(
            rel,
            current_text,
            declared_platform_pyproject,
            declared_platform_package_json,
        )
        original = _declared_platform(
            rel,
            original_text,
            declared_platform_pyproject,
            declared_platform_package_json,
        )
        if current == original:
            continue
        new_text = versions.apply_platform_declaration(current_text, rel, original)
        if new_text == current_text:
            shown_as = original or "unset"
            raise GitConvoyError(
                f"{repo_path.name}: could not restore platform in {rel} to {shown_as}"
            )
        path.write_text(new_text)
        changed.append(rel)
        targets.append(original)
    if not changed:
        return None
    nonempty = sorted({item for item in targets if item})
    platform = nonempty[0] if len(nonempty) == 1 else ""
    return {"files": changed, "platform": platform}


def _platform_declaration_files(repo: Path) -> list[str]:
    rels = list(versions.python_pyproject_rels(repo))
    npm = versions.read_version(repo).get("npm_file")
    if npm and npm not in rels:
        rels.append(npm)
    return rels


def _declared_platform(rel: str, text: str, pyproject, package_json) -> str:
    if not text.strip():
        return ""
    if rel.endswith(".json"):
        return package_json(text)
    return pyproject(text)


def _restore_pre_train_version(repo_path: Path, base: str, train_name: str) -> bool:
    if not base:
        return False
    previous = versions.read_version_at_ref(repo_path, base)
    current = versions.read_version(repo_path)
    pep = previous.get("python") or ""
    npm = previous.get("npm") or ""
    if not pep and not npm:
        return False
    if pep == (current.get("python") or "") and (not npm or npm == (current.get("npm") or "")):
        return False
    versions.write_version(repo_path, pep or (current.get("python") or ""), npm or pep)
    gitutil.run(repo_path, "add", "-A")
    if not gitutil.is_dirty(repo_path):
        return False
    gitutil.run(
        repo_path,
        "commit",
        "-m",
        f"Restore version after leaving train {train_name}",
    )
    return True


def _refuse_dirty_train(workspace: Path, train: Train) -> None:
    dirty = [
        row.id
        for row in train.repos
        if gitutil.is_dirty(workspace / row.path)
    ]
    if not dirty:
        return
    verb = "is" if len(dirty) == 1 else "are"
    raise GitConvoyError(
        f"{', '.join(dirty)} {verb} dirty on {train.branch}. "
        "run: git convoy train commit"
    )


def _ensure_train_row(repo: Repo, train: Train) -> None:
    for existing in train.repos:
        if existing.id == repo.id:
            return
    info = versions.read_version(repo.path)
    current = info.get("python") or info.get("npm")
    train.add_repo(
        TrainRepo(
            id=repo.id,
            path=repo.rel,
            from_version=current,
            to=None,
        )
    )


def _require_product(workspace: Path, repo_id: str) -> Repo:
    try:
        return require_repo(product_repos(workspace), repo_id)
    except GitConvoyError:
        if any(row.id == repo_id or row.rel == repo_id for row in ops_repos(workspace)):
            raise GitConvoyError(
                f"{repo_id} is an ops repo; train adopt only takes product repos"
            ) from None
        if any(row.id == repo_id or row.rel == repo_id for row in bom_repos(workspace)):
            raise GitConvoyError(
                f"{repo_id} is a BOM repo; do not put *-bom on a train"
            ) from None
        raise


def _adopt_one(repo: Repo, train: Train, *, force: bool = False) -> dict:
    branch = train.branch
    current = gitutil.current_branch(repo.path)
    dirty = gitutil.is_dirty(repo.path)
    gitutil.fetch(repo.path)
    integration = gitutil.integration_branch(repo.path)
    if current not in {integration, branch}:
        raise GitConvoyError(
            f"{repo.id} has work on {current}, not {integration} or {branch}. "
            "commit/stash or checkout the right branch first"
        )

    if current == branch:
        return {
            "id": repo.id,
            "path": repo.rel,
            "adopted": True,
            "action": "already-on-train",
            "dirty": dirty,
        }

    if not dirty and not force:
        return {
            "id": repo.id,
            "path": repo.rel,
            "adopted": False,
            "reason": "unchanged",
            "branch": current,
        }

    gitutil.checkout_branch(repo.path, branch)
    return {
        "id": repo.id,
        "path": repo.rel,
        "adopted": True,
        "action": "branched",
        "dirty": gitutil.is_dirty(repo.path),
        "integration_branch": integration,
    }


def tag_rc(workspace: Path, state: State, push: bool = True) -> dict:
    train = state.require_train()
    _refuse_dirty_train(workspace, train)
    _refuse_unviable(workspace, state, train)
    develop_sync = _sync_train_develop(
        workspace,
        train,
        push=push,
        retry_hint="git convoy train tag-rc",
    )
    tagged: list[dict] = []
    platform = _packages_platform(workspace, list(train.repos), choose_rc=True)
    for repo_row in _ordered(train):
        repo_path = workspace / repo_row.path
        gitutil.checkout_branch(repo_path, train.branch)
        info = versions.read_version(repo_path)
        current = info.get("python") or info.get("npm")
        if not current:
            raise GitConvoyError(f"{repo_row.id}: no version file")
        pep, npm, tag = _choose_rc(repo_path, current)
        if pep != current or info.get("npm") not in {None, npm}:
            versions.write_version(
                repo_path,
                pep,
                npm,
                platform=_platform_for_repo(repo_row.id, repo_row.path, platform),
            )
            gitutil.run(repo_path, "add", "-A")
            gitutil.run(
                repo_path,
                "commit",
                "-m",
                f"Set {pep} for train {train.name}",
                check=False,
            )
        head = gitutil.rev_parse(repo_path, "HEAD")
        existing = _existing_tag_commit(repo_path, tag)
        if existing and head and existing != head:
            raise GitConvoyError(
                f"{repo_row.id}: {tag} already points at {existing[:7]}, not HEAD. "
                "re-run: git convoy train tag-rc"
            )
        if not existing:
            gitutil.run(repo_path, "tag", tag)
        if push:
            gitutil.push_branch_and_tag(
                repo_path, train.branch, tag, set_upstream=True
            )
        repo_row.to = pep
        repo_row.rc_tag = tag
        tagged.append({"id": repo_row.id, "tag": tag, "version": pep})
    train.status = "stabilizing"
    save(workspace, state)
    result = {
        "ok": develop_sync["ok"],
        "train": train.name,
        "repos": tagged,
        "develop_sync": develop_sync,
    }
    if not develop_sync["ok"]:
        result["note"] = develop_sync.get("note")
    return result


def mergeback(
    workspace: Path,
    state: State,
    name: str | None = None,
    push: bool = True,
) -> dict:
    """Merge tagged main into develop for every product repo.

    Train participants use the stable tag from the sheet; other repos use their
    latest stable tag (or main). Idempotent. Safe to re-run after a partial
    publish or a conflict. Continues past per-repo failures.
    """
    train = state.require_train(name)
    if train.status != "published":
        raise GitConvoyError(
            f"train {train.name} is {train.status}; "
            "mergeback runs after train publish"
        )
    data = _sync_all_product_develop(
        workspace,
        train,
        push=push,
        retry_hint="git convoy train mergeback",
    )
    data["train"] = train.name
    if data.get("failed"):
        data["note"] = (
            "stable tags are on main; "
            "fix the failed repos, then: git convoy train mergeback"
        )
    return data


def format_mergeback_text(data: dict) -> str:
    return format_develop_sync_text(data, label=f"mergeback {data['train']}")


def publish(workspace: Path, state: State, push: bool = True) -> dict:
    train = state.require_train()
    _refuse_unviable(workspace, state, train)
    published: list[dict] = []
    for repo_row in _ordered(train):
        repo_path = workspace / repo_row.path
        gitutil.checkout_branch(repo_path, train.branch)
        if gitutil.is_dirty(repo_path):
            raise GitConvoyError(f"{repo_row.id} is dirty")
        info = versions.read_version(repo_path)
        current = info.get("python") or info.get("npm")
        if not current:
            raise GitConvoyError(f"{repo_row.id}: no version file")
        pep, npm = versions.drop_rc(current)
        versions.write_version(repo_path, pep, npm)
        gitutil.run(repo_path, "add", "-A")
        gitutil.run(
            repo_path,
            "commit",
            "-m",
            f"Release {pep}",
            check=False,
        )
        gitutil.checkout_branch(repo_path, "main")
        gitutil.run(repo_path, "pull", "--ff-only", "origin", "main", check=False)
        merged = gitutil.merge(repo_path, train.branch)
        if merged.returncode != 0:
            raise GitConvoyError(
                f"{repo_row.id}: merge to main failed. stop; do not continue the set"
            )
        tag = f"v{pep}"
        if not gitutil.rev_parse(repo_path, f"refs/tags/{tag}"):
            gitutil.run(repo_path, "tag", tag)
        if push:
            gitutil.push_branch_and_tag(repo_path, "main", tag)
        repo_row.to = pep
        repo_row.stable_tag = tag
        published.append({"id": repo_row.id, "tag": tag, "version": pep})
    train.status = "published"
    save(workspace, state)
    mb = mergeback(workspace, state, train.name, push=push)
    by_id = {row["id"]: row for row in mb["repos"]}
    for row in published:
        extra = by_id.get(row["id"]) or {}
        row["synced_develop"] = bool(extra.get("synced"))
        row["develop_status"] = extra.get("status")
    result = {
        "ok": mb["ok"],
        "train": train.name,
        "merge_order": [row.id for row in _ordered(train)],
        "repos": published,
        "mergeback": mb,
    }
    if not mb["ok"]:
        result["note"] = mb.get("note") or (
            "stable tags are on main; re-run: git convoy train mergeback"
        )
    return result


def verify(
    workspace: Path,
    state: State,
    name: str | None = None,
    *,
    wait: bool = False,
    timeout_sec: int = 1800,
    poll_sec: int = 30,
    stable: bool | None = None,
) -> dict:
    train = state.require_train(name)
    ghutil.require_gh()
    use_stable = stable if stable is not None else train.status == "published"

    def _verify_repo(repo_row: TrainRepo) -> dict:
        repo_path = workspace / repo_row.path
        tag = (
            (repo_row.stable_tag if use_stable else repo_row.rc_tag)
            or repo_row.stable_tag
            or repo_row.rc_tag
        )
        slug = gitutil.github_slug(repo_path)
        row: dict = {
            "id": repo_row.id,
            "path": repo_row.path,
            "tag": tag,
            "slug": slug,
        }
        publish_wfs = tag_push_workflows(repo_path) if repo_path.is_dir() else []
        row["workflows"] = publish_wfs
        if not publish_wfs:
            row["status"] = "skip"
            row["detail"] = "no workflow triggers on v* tag push (git-clone participant)"
            return row
        if not tag:
            row["status"] = "no-tag"
            row["detail"] = "no tag on train sheet"
            return row
        if not slug:
            row["status"] = "no-remote"
            row["detail"] = "no github.com origin remote"
            return row
        commit = ghutil.tag_sha(repo_path, tag)
        if not commit:
            row["status"] = "no-tag-on-remote"
            row["detail"] = f"tag {tag} not found on origin"
            return row
        wf_rows = ghutil.publish_runs_for_commit(
            slug, commit, publish_wfs, cwd=repo_path
        )
        row["commit"] = commit[:7]
        row["workflow_runs"] = wf_rows
        row["status"] = ghutil.aggregate_workflow_status(wf_rows)
        row["detail"] = _verify_detail(tag, publish_wfs, wf_rows, row["status"])
        success_run = next(
            (w for w in wf_rows if w.get("status") == "success" and w.get("run_url")),
            None,
        )
        if success_run:
            row["run_url"] = success_run["run_url"]
        elif row["status"] == "failure":
            failed = next(
                (w for w in wf_rows if w.get("status") == "failure" and w.get("run_url")),
                None,
            )
            if failed:
                row["run_url"] = failed["run_url"]
        return row

    def _check_once() -> list[dict]:
        return [_verify_repo(repo_row) for repo_row in _ordered(train)]

    def _waiting(rows: list[dict]) -> bool:
        return any(row.get("status") in {"pending", "missing"} for row in rows)

    rows = _check_once()
    deadline = time.monotonic() + timeout_sec if wait else None
    while wait and _waiting(rows) and deadline is not None:
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_sec)
        rows = _check_once()

    verified = [row for row in rows if row.get("status") == "success"]
    skipped = [row for row in rows if row.get("status") == "skip"]
    pending = [
        row for row in rows if row.get("status") in {"pending", "missing"}
    ]
    failed = [
        row
        for row in rows
        if row.get("status") not in {"success", "skip", "pending", "missing"}
    ]
    incomplete = pending + failed
    payload = {
        "ok": not incomplete,
        "train": train.name,
        "status": train.status,
        "tag_kind": "stable" if use_stable else "rc",
        "verified_count": len(verified),
        "skipped_count": len(skipped),
        "pending_count": len(pending),
        "failed_count": len(failed),
        "repo_count": len(rows),
        "repos": rows,
    }
    notes: list[str] = []
    if pending and not wait:
        notes.append("Re-run with --wait to poll for in-progress workflows.")
    if failed:
        notes.append("Fix failed publish workflows, then re-run train verify.")
    if notes:
        payload["note"] = " ".join(notes)
    return payload


def format_verify_text(data: dict) -> str:
    lines = [
        f"{data['train']}  verified {data['verified_count']}/{data['repo_count']} "
        f"({data['tag_kind']} tags; {data.get('skipped_count', 0)} skipped)",
    ]
    groups = [
        ("succeeded", "success"),
        ("skipped", "skip"),
        ("pending", "pending"),
        ("waiting", "missing"),
        ("failed", "failure"),
    ]
    shown: set[str] = set()
    for label, status in groups:
        bucket = [
            row for row in data.get("repos") or [] if row.get("status") == status
        ]
        for row in bucket:
            shown.add(row["id"])
        if not bucket:
            continue
        lines.append(f"{label} ({len(bucket)}):")
        for repo in bucket:
            wf = ", ".join(repo.get("workflows") or []) or "-"
            tag = repo.get("tag") or "-"
            url = f"  {repo['run_url']}" if repo.get("run_url") else ""
            lines.append(
                f"  {repo['id']:20} {tag:16} [{wf}]{url}"
            )
            detail = repo.get("detail")
            if detail and repo.get("status") != "success":
                lines.append(f"    {detail}")
            elif detail and repo.get("status") == "success" and url == "":
                lines.append(f"    {detail}")
    other = [
        row
        for row in data.get("repos") or []
        if row.get("id") not in shown
        and row.get("status") not in {"success", "skip"}
    ]
    if other:
        lines.append(f"unknown ({len(other)}):")
        for repo in other:
            wf = ", ".join(repo.get("workflows") or []) or "-"
            tag = repo.get("tag") or "-"
            lines.append(f"  {repo['id']:20} {tag:16} [{wf}]")
            detail = repo.get("detail")
            if detail:
                lines.append(f"    {detail}")
    note = (data.get("note") or "").strip()
    if note:
        lines.append(note)
    return "\n".join(lines)


def _verify_detail(
    tag: str,
    workflow_files: list[str],
    wf_rows: list[dict],
    status: str,
) -> str:
    wf_list = ", ".join(workflow_files)
    if status == "success":
        return f"{tag} — {wf_list} succeeded"
    if status == "pending":
        return f"{tag} — {wf_list} still running"
    if status == "failure":
        parts = []
        for row in wf_rows:
            if row.get("status") == "failure":
                url = row.get("run_url") or row.get("file")
                parts.append(f"{row['file']} failed ({url})")
        return f"{tag} — " + "; ".join(parts or [f"{wf_list} failed"])
    if status == "missing":
        return (
            f"{tag} @ commit — no Actions run yet for workflows [{wf_list}] "
            "(tag push should trigger these)"
        )
    return status


def close(
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
    train = state.require_train(name)
    branch = train.branch
    targets = _delete_targets(workspace, train)
    if not yes:
        if as_json or not (sys.stdin.isatty() if is_tty is None else is_tty):
            raise GitConvoyError(
                "train close removes release branches; pass --yes to confirm"
            )
        ids = ", ".join(repo.id for repo in targets) or "(none)"
        prompt = (
            f"This will delete local {branch} in {len(targets)} repos ({ids})"
            + (" and on origin" if remote else "")
            + " only where every commit is already on develop or main, "
            "remove the train sheet, and check out the integration branch. "
            "Uncommitted files are never discarded. Continue? : "
        )
        answer = _confirm_yes(input_fn or input, prompt)
        if not answer:
            return {
                "ok": True,
                "deleted": False,
                "closed": False,
                "train": train.name,
                "branch": branch,
                "repos": [],
            }

    removed: list[dict] = []
    blocked: list[str] = []
    for repo in targets:
        gitutil.fetch(repo.path)
        current = gitutil.current_branch(repo.path)
        dirty = gitutil.is_dirty(repo.path)
        if dirty and current == branch:
            blocked.append(f"{repo.id}: uncommitted changes on {branch}")
        if gitutil.has_local_branch(repo.path, branch) and not gitutil.ref_merged_into_integration(
            repo.path, f"refs/heads/{branch}"
        ):
            blocked.append(
                f"{repo.id}: {branch} has commits not on develop or main"
            )
        if remote and gitutil.has_remote_branch(repo.path, branch) and not (
            gitutil.ref_merged_into_integration(
                repo.path, f"refs/remotes/origin/{branch}"
            )
        ):
            blocked.append(
                f"{repo.id}: origin/{branch} has commits not on develop or main"
            )
    if blocked:
        raise GitConvoyError(
            "train close refused (would lose work):\n  "
            + "\n  ".join(blocked)
            + "\nmerge, commit, or stash first"
        )

    for repo in targets:
        current = gitutil.current_branch(repo.path)
        integration = current
        if current == branch:
            integration = gitutil.checkout_integration(repo.path)
        on_origin = gitutil.has_remote_branch(repo.path, branch)
        deleted_local = False
        if gitutil.has_local_branch(repo.path, branch):
            # -D is safe here: the refuse loop already required every
            # commit on develop/main (local or origin). ``branch -d`` also
            # compares the branch's upstream, which is often a stale
            # origin/release/<train> that never received the publish commit.
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
                "branch": gitutil.current_branch(repo.path),
                "integration_branch": integration,
                "deleted_local": deleted_local,
                "deleted_remote": deleted_remote,
                "on_origin": on_origin and not deleted_remote,
            }
        )

    if state.current_train == train.name:
        state.current_train = None
    state.trains.pop(train.name, None)
    save(workspace, state)
    still_on_origin = [row["id"] for row in removed if row["on_origin"]]
    note = (
        f"Removed train {train.name}. Local {branch} deleted only where already "
        "merged. Uncommitted files were not discarded."
    )
    if still_on_origin and not remote:
        note += (
            f" {branch} still on origin in: "
            + ", ".join(still_on_origin)
            + ". Re-run with --remote to delete there."
        )
    return {
        "ok": True,
        "deleted": True,
        "closed": True,
        "train": train.name,
        "branch": branch,
        "note": note,
        "repos": removed,
    }


delete = close


def show(workspace: Path, state: State, name: str | None = None) -> dict:
    train = state.require_train(name)
    report = viability(workspace, state, train.name)
    return {
        "ok": True,
        "name": train.name,
        "branch": train.branch,
        "status": train.status,
        "features": train.features,
        "repo_count": len(train.repos),
        "viable": report["viable"],
        "viability": {
            "note": report.get("note") or "",
            "repos": report.get("repos") or [],
        },
        "repos": [
            {
                "id": repo.id,
                "path": repo.path,
                "from": repo.from_version,
                "to": repo.to,
                "rc_tag": repo.rc_tag,
                "stable_tag": repo.stable_tag,
            }
            for repo in train.repos
        ],
    }


_TRAIN_IN_SUBJECT = re.compile(r"for train (\S+)")
_VIABILITY_KINDS = ("stable-taken", "rc-contest", "main-diverged", "missing-release")
_UNFOLD_RECOMMENDATION = (
    "Run: git convoy train unfold, that will save your release patches back to develop. "
    "Solve any conflicts and then try the release train again."
)


def viability(workspace: Path, state: State, name: str | None = None) -> dict:
    """Say whether this train can still be published without regressing another line.

    A release manager does not need to know which other project moved. The
    check is local to each participant:

    * the stable tag this train would publish already points somewhere else
    * ``main`` has commits this release branch does not contain
    * an rc tag for the same version points at a commit this release does not contain
    """
    train = state.require_train(name)
    if train.status == "unfolded":
        return {
            "ok": True,
            "viable": True,
            "train": train.name,
            "status": train.status,
            "repos": [],
            "note": (
                f"Unfolded into feature/{train.name}. "
                "Next: git convoy feature refresh"
            ),
        }
    if train.status not in {"cut", "stabilizing"}:
        return {
            "ok": True,
            "viable": True,
            "train": train.name,
            "status": train.status,
            "repos": [],
            "note": "",
        }
    repos: list[dict] = []
    for row in train.repos:
        repo_path = workspace / row.path
        if not gitutil.is_git_repo(repo_path):
            continue
        gitutil.fetch(repo_path)
        findings = _repo_viability(repo_path, train, row)
        if findings:
            repos.append({"id": row.id, "path": row.path, "findings": findings})
    viable = not repos
    note = ""
    if not viable:
        note = _UNFOLD_RECOMMENDATION
    return {
        "ok": True,
        "viable": viable,
        "train": train.name,
        "status": train.status,
        "repos": repos,
        "note": note,
    }


def unfold(workspace: Path, state: State) -> dict:
    """Turn the current train into feature/<train> and retire the sheet.

    The feature branch starts at the release tip, with version numbers put
    back to ``develop``. It does not merge ``develop``. Next is
    ``feature refresh``, then ``feature prs``.
    """
    train = state.require_train()
    if train.status not in {"cut", "stabilizing"}:
        raise GitConvoyError(
            f"train {train.name} is {train.status}; "
            "unfold only runs while the train is cut or stabilizing"
        )
    if state.current_feature and state.current_feature != train.name:
        raise GitConvoyError(
            f"feature {state.current_feature} is current; "
            "close or switch it before train unfold"
        )
    dirty = [
        row.id
        for row in train.repos
        if (workspace / row.path).is_dir() and gitutil.is_dirty(workspace / row.path)
    ]
    if dirty:
        verb = "is" if len(dirty) == 1 else "are"
        raise GitConvoyError(
            f"{', '.join(dirty)} {verb} dirty; commit or stash before train unfold"
        )
    feature_branch = f"feature/{train.name}"
    feature = state.features.get(train.name) or Feature(
        name=train.name,
        branch=feature_branch,
    )
    feature.branch = feature_branch
    feature.unfolded_from = train.name
    feature.status = "in-progress"
    restored: list[dict] = []
    for row in train.repos:
        repo_path = workspace / row.path
        if not gitutil.has_local_branch(repo_path, train.branch):
            raise GitConvoyError(f"{row.id}: missing {train.branch}")
        if gitutil.has_local_branch(repo_path, feature_branch):
            gitutil.checkout_branch(repo_path, feature_branch)
        else:
            gitutil.checkout_branch(repo_path, train.branch)
            gitutil.checkout(repo_path, feature_branch, create=True)
        version_restored = _restore_develop_version(repo_path, train.name)
        feature.add_repo(row.id, row.path)
        restored.append(
            {
                "id": row.id,
                "path": row.path,
                "branch": feature_branch,
                "version_restored": version_restored,
            }
        )
    state.features[train.name] = feature
    state.current_feature = train.name
    if train.name not in train.features:
        train.features.append(train.name)
    train.status = "unfolded"
    state.current_train = None
    save(workspace, state)
    return {
        "ok": True,
        "train": train.name,
        "feature": feature.name,
        "branch": feature.branch,
        "status": train.status,
        "repos": restored,
        "note": (
            f"Train {train.name} is now feature/{train.name}. "
            "Next: git convoy feature refresh  "
            "Then resolve conflicts and re-run refresh. "
            "Then: git convoy feature prs"
        ),
    }


def _refuse_unviable(workspace: Path, state: State, train: Train) -> None:
    blocked = _viability_error(
        viability(workspace, state, train.name),
        kinds=_VIABILITY_KINDS,
    )
    if blocked:
        raise GitConvoyError(blocked)


def _viability_error(report: dict, *, kinds: tuple[str, ...]) -> str | None:
    if report.get("viable", True) and not report.get("repos"):
        return None
    lines: list[str] = []
    for repo in report.get("repos") or []:
        for finding in repo.get("findings") or []:
            if finding.get("kind") not in kinds:
                continue
            lines.append(f"{repo['id']}: {_finding_sentence(finding)}")
    if not lines:
        return None
    return (
        f"train {report.get('train') or '?'} is not viable.\n  "
        + "\n  ".join(lines)
        + "\n"
        + _UNFOLD_RECOMMENDATION
    )


def _repo_viability(repo_path: Path, train: Train, row: TrainRepo) -> list[dict]:
    tip = _release_tip(repo_path, train.branch)
    if not tip:
        return [
            {
                "kind": "missing-release",
                "tag": "",
                "sha": "",
                "subject": "",
                "on": [],
                "train": None,
                "ref": train.branch,
                "ahead": 0,
                "commits": [],
            }
        ]
    findings: list[dict] = []
    version = (row.to or "").strip()
    if not version:
        info = versions.read_version_at_ref(repo_path, tip)
        version = (info.get("python") or info.get("npm") or "").strip()
    body = ""
    if version:
        try:
            pep, _npm = versions.drop_rc(version)
        except GitConvoyError:
            pep = ""
        if pep:
            body = _tag_body(pep)
            stable = f"v{body}"
            taken = _existing_tag_commit(repo_path, stable)
            if taken and not gitutil.is_ancestor(repo_path, taken, tip):
                findings.append(
                    _tag_finding(repo_path, "stable-taken", stable, taken, train.name)
                )
            for tag_name, sha in _rc_tags(repo_path, body):
                if gitutil.is_ancestor(repo_path, sha, tip):
                    continue
                findings.append(
                    _tag_finding(repo_path, "rc-contest", tag_name, sha, train.name)
                )
    main_ref = _main_ref(repo_path)
    if main_ref and not gitutil.is_ancestor(repo_path, main_ref, tip):
        findings.append(_main_finding(repo_path, tip, main_ref))
    return findings


def _release_tip(repo_path: Path, branch: str) -> str | None:
    local = gitutil.rev_parse(repo_path, branch)
    if local:
        return local
    return gitutil.rev_parse(repo_path, f"origin/{branch}")


def _main_ref(repo_path: Path) -> str | None:
    if gitutil.rev_parse(repo_path, "origin/main"):
        return "origin/main"
    if gitutil.rev_parse(repo_path, "main"):
        return "main"
    return None


def _rc_tags(repo_path: Path, body: str) -> list[tuple[str, str]]:
    pattern = f"v{body}-rc.*"
    names = [
        line.strip()
        for line in gitutil.capture(repo_path, "tag", "-l", pattern).splitlines()
        if line.strip()
    ]
    found: list[tuple[str, str]] = []
    for name in names:
        sha = _existing_tag_commit(repo_path, name)
        if sha:
            found.append((name, sha))
    return found


def _tag_finding(
    repo_path: Path,
    kind: str,
    tag: str,
    sha: str,
    our_train: str,
) -> dict:
    info = gitutil.commit_oneline(repo_path, sha)
    places, branch_train = _containers(repo_path, sha, our_train)
    subject_train = _train_from_subject(info["subject"])
    return {
        "kind": kind,
        "tag": tag,
        "sha": info["sha"],
        "subject": info["subject"],
        "on": places,
        "train": subject_train or branch_train,
        "ref": "",
        "ahead": 0,
        "commits": [],
    }


def _main_finding(repo_path: Path, tip: str, main_ref: str) -> dict:
    count_text = gitutil.capture(
        repo_path, "rev-list", "--count", f"{tip}..{main_ref}"
    )
    try:
        ahead = int(count_text or "0")
    except ValueError:
        ahead = 0
    log = gitutil.capture(repo_path, "log", "--format=%h", f"{tip}..{main_ref}")
    commits = [{"sha": line.strip(), "subject": ""} for line in log.splitlines() if line.strip()]
    return {
        "kind": "main-diverged",
        "tag": "",
        "sha": "",
        "subject": "",
        "on": [main_ref],
        "train": None,
        "ref": main_ref,
        "ahead": ahead,
        "commits": commits,
    }


def _containers(
    repo_path: Path, sha: str, our_train: str
) -> tuple[list[str], str | None]:
    result = gitutil.run(
        repo_path, "branch", "-a", "--contains", sha, check=False
    )
    places: list[str] = []
    foreign: str | None = None
    for line in (result.stdout or "").splitlines():
        name = line.strip().lstrip("*").strip()
        if not name or name.startswith("(") or "->" in name:
            continue
        name = name.removeprefix("remotes/")
        if name in {"origin/HEAD", "HEAD"} or name.endswith("/HEAD"):
            continue
        short = name.removeprefix("origin/")
        if short in {f"release/{our_train}", our_train}:
            continue
        if name not in places:
            places.append(name)
        marker = "release/"
        if marker in short:
            train_name = short.split(marker, 1)[1]
            if train_name and train_name != our_train and foreign is None:
                foreign = train_name
    preferred = [
        item
        for item in (
            "origin/main",
            "main",
            "origin/develop",
            "develop",
        )
        if item in places
    ]
    releases = [item for item in places if "release/" in item]
    return preferred + releases, foreign


def _train_from_subject(subject: str) -> str | None:
    match = _TRAIN_IN_SUBJECT.search(subject or "")
    if not match:
        return None
    return match.group(1)


def _finding_sentence(finding: dict) -> str:
    kind = finding.get("kind")
    if kind == "missing-release":
        return (
            f"missing {finding.get('ref') or 'release branch'}. "
            "There is no release branch to publish."
        )
    if kind == "main-diverged":
        ref = finding.get("ref") or "main"
        ahead = finding.get("ahead") or 0
        noun = "commit" if ahead == 1 else "commits"
        ids = " ".join(
            row.get("sha") or "" for row in finding.get("commits") or [] if row.get("sha")
        )
        sentence = (
            f"{ref} has {ahead} {noun} this release does not contain. "
            "Publishing would cause a regression."
        )
        return f"{sentence}\n{ids}" if ids else sentence
    if kind == "stable-taken":
        tag = finding.get("tag") or "tag"
        sha = finding.get("sha") or "?"
        return (
            f"Aspirational tag {tag} already points at {sha}. "
            "Another train already took this tag, you can't re-use it."
        )
    tag = finding.get("tag") or "tag"
    train_name = finding.get("train")
    owner = f" train {train_name}" if train_name else ""
    return (
        f"rc tag {tag} is an rc contest{owner}. "
        "Another train is releasing the same repo and it is using the same release tags."
    )


def _restore_develop_version(repo_path: Path, train_name: str) -> bool:
    integration = gitutil.integration_branch(repo_path)
    remote = f"origin/{integration}"
    base = remote if gitutil.rev_parse(repo_path, remote) else integration
    if not gitutil.rev_parse(repo_path, base):
        return False
    previous = versions.read_version_at_ref(repo_path, base)
    current = versions.read_version(repo_path)
    pep = previous.get("python") or ""
    npm = previous.get("npm") or ""
    if not pep and not npm:
        return False
    same_version = pep == (current.get("python") or "") and (
        not npm or npm == (current.get("npm") or "")
    )
    if same_version:
        return False
    versions.write_version(
        repo_path,
        pep or (current.get("python") or ""),
        npm or pep,
    )
    gitutil.run(repo_path, "add", "-A")
    if not gitutil.is_dirty(repo_path):
        return False
    gitutil.run(
        repo_path,
        "commit",
        "-m",
        f"Restore version from develop before unfolding train {train_name}",
    )
    return True


def _ordered(train: Train) -> list[TrainRepo]:
    order = merge_sort([repo.id for repo in train.repos])
    by_id = {repo.id: repo for repo in train.repos}
    return [by_id[name] for name in order]


def _sync_train_develop(
    workspace: Path,
    train: Train,
    *,
    push: bool,
    retry_hint: str,
) -> dict:
    entries = [
        DevelopSyncEntry(
            id=repo_row.id,
            rel=repo_row.path,
            ref=repo_row.stable_tag,
        )
        for repo_row in _ordered(train)
    ]
    return sync_repos_develop(
        workspace, entries, push=push, retry_hint=retry_hint
    )


def _sync_all_product_develop(
    workspace: Path,
    train: Train,
    *,
    push: bool,
    retry_hint: str,
) -> dict:
    participant_refs = {
        repo_row.id: repo_row.stable_tag for repo_row in train.repos
    }
    entries: list[DevelopSyncEntry] = []
    seen: set[str] = set()
    for repo_row in _ordered(train):
        entries.append(
            DevelopSyncEntry(
                id=repo_row.id,
                rel=repo_row.path,
                ref=participant_refs.get(repo_row.id),
            )
        )
        seen.add(repo_row.id)
    for repo in sorted(product_repos(workspace), key=lambda row: row.id):
        if repo.id in seen:
            continue
        entries.append(DevelopSyncEntry(id=repo.id, rel=repo.rel))
    return sync_repos_develop(
        workspace, entries, push=push, retry_hint=retry_hint
    )


def _delete_targets(workspace: Path, train: Train) -> list[Repo]:
    products = product_repos(workspace)
    by_id = {repo.id: repo for repo in products}
    seen: set[str] = set()
    targets: list[Repo] = []
    for row in train.repos:
        repo = by_id.get(row.id)
        if repo and repo.id not in seen:
            seen.add(repo.id)
            targets.append(repo)
    for repo in products:
        if repo.id in seen:
            continue
        if gitutil.has_local_branch(repo.path, train.branch):
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


def _ensure_rc(version: str) -> tuple[str, str]:
    _major, _minor, _patch, rc = versions.parse(version)
    if rc is None:
        return versions.with_rc(version, 1)
    return versions.with_rc(version, rc)


def _choose_rc(repo: Path, current: str) -> tuple[str, str, str]:
    """Pick the next unused rc version and ``v*`` tag for this repo.

    Skips tags that already exist locally or on origin (unless they already
    point at HEAD — idempotent re-run). If this X.Y.Z was already released
    (``vX.Y.Z`` exists), start at the next patch ``rc.1``.
    """
    gitutil.fetch(repo)
    major, minor, patch, _rc = versions.parse(current)
    if _existing_tag_commit(repo, f"v{major}.{minor}.{patch}"):
        pep, npm = versions.with_rc(versions.bump(current, "patch"), 1)
    else:
        pep, npm = _ensure_rc(current)
    head = gitutil.rev_parse(repo, "HEAD")
    for _ in range(100):
        tag = f"v{_tag_body(pep)}"
        taken = _existing_tag_commit(repo, tag)
        if not taken or taken == head:
            return pep, npm, tag
        pep, npm = versions.next_rc(pep)
    raise GitConvoyError(
        f"{repo.name}: could not find a free rc tag after {current}"
    )


def _existing_tag_commit(repo: Path, tag: str) -> str | None:
    """Commit SHA for ``tag`` locally or on origin. None if unused."""
    local = gitutil.rev_parse(repo, f"{tag}^{{}}") or gitutil.rev_parse(
        repo, f"refs/tags/{tag}"
    )
    if local:
        return local
    result = gitutil.run(repo, "ls-remote", "--tags", "origin", tag, check=False)
    peeled: str | None = None
    lightweight: str | None = None
    suffix = f"refs/tags/{tag}"
    for line in (result.stdout or "").splitlines():
        sha, _, ref = line.partition("\t")
        sha = sha.strip()
        ref = ref.strip()
        if not sha:
            continue
        if ref == f"{suffix}^{{}}":
            peeled = sha
        elif ref == suffix:
            lightweight = sha
    return peeled or lightweight


def _tag_body(pep: str) -> str:
    major, minor, patch, rc = versions.parse(pep)
    if rc is None:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{patch}-rc.{rc}"


def _slug(name: str) -> str:
    slug = name.strip().replace(" ", "-")
    if slug.startswith("release/"):
        slug = slug[len("release/") :]
    if not slug:
        raise GitConvoyError("train name is empty")
    return slug
