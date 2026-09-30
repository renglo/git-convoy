from __future__ import annotations

from pathlib import Path

from gitconvoy import gitutil
from gitconvoy import hotfix as hotfix_cmd
from gitconvoy.state import State
from gitconvoy.workspace import discover_repos


def status(workspace: Path, state: State) -> dict:
    repos = []
    dirty = []
    for repo in discover_repos(workspace):
        row = {
            "id": repo.id,
            "path": repo.rel,
            "kind": repo.kind,
            "branch": gitutil.current_branch(repo.path),
            "dirty": gitutil.is_dirty(repo.path),
        }
        repos.append(row)
        if row["dirty"]:
            dirty.append(repo.id)
    feature = None
    if state.current_feature and state.current_feature in state.features:
        feat = state.features[state.current_feature]
        feature = {
            "name": feat.name,
            "branch": feat.branch,
            "status": feat.status,
            "repo_count": len(feat.repos),
            "repos": feat.repo_ids(),
        }
    hotfix = None
    if state.current_hotfix and state.current_hotfix in state.hotfixes:
        item = state.hotfixes[state.current_hotfix]
        landed = hotfix_cmd.landed_in_develop(workspace, item)
        tags = sorted({row["stable_tag"] for row in landed if row.get("stable_tag")})
        missing = [row["id"] for row in landed if not row["in_develop"]]
        hotfix = {
            "name": item.name,
            "branch": item.branch,
            "status": item.status,
            "repo_count": len(item.repos),
            "repos": item.repo_ids(),
            "stable_tags": tags,
            "in_develop": item.status == "published" and not missing,
            "develop_missing": missing,
        }
    train = None
    if state.current_train and state.current_train in state.trains:
        item = state.trains[state.current_train]
        train = {
            "name": item.name,
            "branch": item.branch,
            "status": item.status,
            "repo_count": len(item.repos),
            "repos": [repo.id for repo in item.repos],
        }
    ops = None
    if state.current_ops and state.current_ops in state.ops_sheets:
        item = state.ops_sheets[state.current_ops]
        ops = {
            "name": item.name,
            "branch": item.branch,
            "status": item.status,
            "repo_count": len(item.repos),
            "repos": item.repo_ids(),
        }
    return {
        "ok": True,
        "workspace": str(workspace),
        "current_feature": state.current_feature,
        "current_train": state.current_train,
        "current_hotfix": state.current_hotfix,
        "current_ops": state.current_ops,
        "feature": feature,
        "hotfix": hotfix,
        "train": train,
        "ops": ops,
        "dirty": dirty,
        "repos": repos,
    }
