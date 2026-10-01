"""Ops cycle 2: one release sheet for every ops repo that is ahead of its last tag."""

from __future__ import annotations

import re
from pathlib import Path

from gitconvoy import adopt as adopt_cmd
from gitconvoy import gitutil
from gitconvoy import versions
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, Train, TrainRepo, save
from gitconvoy.train import _choose_rc, _has_version, _ordered, _slug
from gitconvoy.workspace import ops_repos, require_repo


def cut(
    workspace: Path,
    state: State,
    name: str,
    bump: str = "patch",
    repo_ids: list[str] | None = None,
    no_bump: bool = False,
) -> dict:
    """Freeze every unpublished ops repo onto ``release/<name>``.

    Same discovery as ``train cut``, limited to repos whose ``gitconvoy.toml``
    says ``role = ops``. One sheet, one command.
    """
    slug = _slug(name)
    branch = f"release/{slug}"
    repos = ops_repos(workspace)
    skipped: list[dict] = []
    if repo_ids:
        chosen = [require_repo(repos, repo_id) for repo_id in repo_ids]
        for repo in chosen:
            if not _has_version(repo.path):
                raise GitConvoyError(
                    f"{repo.id}: no version file; cannot cut an ops release for this repo"
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
                "no publishable ops repos are ahead of their last stable tag "
                f"(skipped without version files: {ids})"
            )
        raise GitConvoyError(
            "no ops repos are ahead of their last stable tag; pass --repos to force"
        )
    train = state.ops_trains.get(slug) or Train(name=slug, branch=branch)
    train.status = "cut"
    added: list[dict] = []
    for repo in chosen:
        gitutil.fetch(repo.path)
        if gitutil.is_dirty(repo.path):
            raise GitConvoyError(f"{repo.id} is dirty; commit or stash before ops cut")
        gitutil.checkout_integration(repo.path)
        gitutil.checkout_branch(repo.path, branch)
        info = versions.read_version(repo.path)
        current = info.get("python") or info.get("npm")
        to = None
        changed: list[str] = []
        if current and not no_bump:
            to = versions.bump(current, bump)
            pep, npm = versions.with_rc(to, 1)
            changed = versions.write_version(repo.path, pep, npm)
            gitutil.run(repo.path, "add", "-A")
            gitutil.run(
                repo.path,
                "commit",
                "-m",
                f"Set {pep} for ops release {slug}",
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
    state.ops_trains[slug] = train
    state.current_ops_release = slug
    save(workspace, state)
    return {
        "ok": True,
        "train": slug,
        "branch": branch,
        "repos": added,
        "skipped": skipped,
    }


def tag_rc(
    workspace: Path,
    state: State,
    push: bool = True,
    bom: str | None = None,
) -> dict:
    """Tag every repo on the current ops release and push those tags.

    When ``renglo-ops`` is on the sheet, ``platform`` in the tenant BOM is set
    to the package version just tagged. git-convoy does not push the BOM.
    """
    train = state.require_ops_release()
    dirty = [
        row.id
        for row in train.repos
        if gitutil.is_dirty(workspace / row.path)
    ]
    if dirty:
        verb = "is" if len(dirty) == 1 else "are"
        raise GitConvoyError(
            f"{', '.join(dirty)} {verb} dirty on {train.branch}. "
            "Commit on that branch, then re-run: git convoy ops tag-rc"
        )
    tagged: list[dict] = []
    for repo_row in _ordered(train):
        repo_path = workspace / repo_row.path
        gitutil.checkout_branch(repo_path, train.branch)
        info = versions.read_version(repo_path)
        current = info.get("python") or info.get("npm")
        if not current:
            raise GitConvoyError(f"{repo_row.id}: no version file")
        pep, npm, tag = _choose_rc(repo_path, current)
        if pep != current or info.get("npm") not in {None, npm}:
            versions.write_version(repo_path, pep, npm)
            gitutil.run(repo_path, "add", "-A")
            gitutil.run(
                repo_path,
                "commit",
                "-m",
                f"Set {pep} for ops release {train.name}",
                check=False,
            )
        head = gitutil.rev_parse(repo_path, "HEAD")
        existing = gitutil.rev_parse(repo_path, f"{tag}^{{}}") or gitutil.rev_parse(
            repo_path, f"refs/tags/{tag}"
        )
        if existing and head and existing != head:
            raise GitConvoyError(
                f"{repo_row.id}: {tag} already points at {existing[:7]}, not HEAD. "
                "re-run: git convoy ops tag-rc"
            )
        if not existing:
            gitutil.run(repo_path, "tag", tag)
        if push:
            gitutil.push(repo_path, "-u", "origin", train.branch)
            gitutil.push(repo_path, "origin", tag)
        repo_row.to = pep
        repo_row.rc_tag = tag
        tagged.append({"id": repo_row.id, "tag": tag, "version": pep})
    train.status = "stabilizing"
    pin = _pin_renglo_ops(workspace, tagged, bom)
    save(workspace, state)
    result = {
        "ok": True,
        "train": train.name,
        "repos": tagged,
        "pin": pin,
    }
    return result


def _pin_renglo_ops(workspace: Path, tagged: list[dict], bom: str | None) -> dict | None:
    row = next((item for item in tagged if item["id"] == "renglo-ops"), None)
    if row is None:
        return None
    try:
        root = adopt_cmd.find_bom_repo(workspace, bom)
    except GitConvoyError as exc:
        return {"status": "skipped", "reason": exc.message, "version": row["version"]}
    path = root / "renglo.yaml"
    if not path.is_file():
        return {
            "status": "skipped",
            "reason": f"{path} is missing",
            "version": row["version"],
        }
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"(?m)^platform:\s+\S+",
        f"platform: {row['version']}",
        text,
        count=1,
    )
    if count != 1:
        raise GitConvoyError(f"{path}: no platform: field")
    if updated != text:
        path.write_text(updated, encoding="utf-8")
    return {
        "status": "updated",
        "version": row["version"],
        "file": str(path.relative_to(workspace)),
        "note": "commit and push the BOM repo; git-convoy does not push *-bom",
    }
