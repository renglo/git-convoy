from __future__ import annotations

from pathlib import Path

from gitconvoy import gitutil, versions
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, Train, TrainRepo, save
from gitconvoy.workspace import merge_sort, product_repos, require_repo


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
    if repo_ids:
        chosen = [require_repo(repos, repo_id) for repo_id in repo_ids]
    else:
        chosen = [repo for repo in repos if gitutil.develop_ahead_of_stable(repo.path)]
    if not chosen:
        raise GitConvoyError(
            "no repos are ahead of their last stable tag; pass --repos to force"
        )
    train = state.trains.get(slug) or Train(name=slug, branch=branch)
    train.status = "cut"
    added: list[dict] = []
    for repo in chosen:
        gitutil.fetch(repo.path)
        if gitutil.is_dirty(repo.path):
            raise GitConvoyError(f"{repo.id} is dirty; commit or stash before train cut")
        if gitutil.rev_parse(repo.path, "origin/develop"):
            gitutil.checkout(repo.path, "develop")
            gitutil.run(repo.path, "pull", "--ff-only", "origin", "develop", check=False)
        else:
            gitutil.checkout_branch(repo.path, "develop")
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
    }


def tag_rc(workspace: Path, state: State, push: bool = True) -> dict:
    train = state.require_train()
    tagged: list[dict] = []
    for repo_row in _ordered(train):
        repo_path = workspace / repo_row.path
        gitutil.checkout_branch(repo_path, train.branch)
        info = versions.read_version(repo_path)
        current = info.get("python") or info.get("npm")
        if not current:
            raise GitConvoyError(f"{repo_row.id}: no version file")
        pep, npm = _ensure_rc(current)
        if pep != current or info.get("npm") not in {None, npm}:
            versions.write_version(repo_path, pep, npm)
            gitutil.run(repo_path, "add", "-A")
            gitutil.run(
                repo_path,
                "commit",
                "-m",
                f"Set {pep} for train {train.name}",
                check=False,
            )
        tag = f"v{_tag_body(pep)}"
        if not gitutil.rev_parse(repo_path, f"refs/tags/{tag}"):
            gitutil.run(repo_path, "tag", tag)
        if push:
            gitutil.push(repo_path, "-u", "origin", train.branch)
            gitutil.push(repo_path, "origin", tag)
        repo_row.to = pep
        repo_row.rc_tag = tag
        tagged.append({"id": repo_row.id, "tag": tag, "version": pep})
    train.status = "stabilizing"
    save(workspace, state)
    return {"ok": True, "train": train.name, "repos": tagged}


def publish(workspace: Path, state: State, push: bool = True) -> dict:
    train = state.require_train()
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
            gitutil.push(repo_path, "origin", "main")
            gitutil.push(repo_path, "origin", tag)
        repo_row.to = pep
        repo_row.stable_tag = tag
        published.append({"id": repo_row.id, "tag": tag, "version": pep})
    train.status = "published"
    save(workspace, state)
    return {
        "ok": True,
        "train": train.name,
        "merge_order": [row.id for row in _ordered(train)],
        "repos": published,
    }


def show(state: State, name: str | None = None) -> dict:
    train = state.require_train(name)
    return {
        "ok": True,
        "name": train.name,
        "branch": train.branch,
        "status": train.status,
        "features": train.features,
        "repo_count": len(train.repos),
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


def _ordered(train: Train) -> list[TrainRepo]:
    order = merge_sort([repo.id for repo in train.repos])
    by_id = {repo.id: repo for repo in train.repos}
    return [by_id[name] for name in order]


def _ensure_rc(version: str) -> tuple[str, str]:
    _major, _minor, _patch, rc = versions.parse(version)
    if rc is None:
        return versions.with_rc(version, 1)
    return versions.with_rc(version, rc)


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
