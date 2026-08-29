from __future__ import annotations

from pathlib import Path

from gitconvoy import gitutil
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
    return {
        "ok": True,
        "workspace": str(workspace),
        "current_feature": state.current_feature,
        "current_train": state.current_train,
        "feature": feature,
        "train": train,
        "dirty": dirty,
        "repos": repos,
    }
