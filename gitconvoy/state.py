from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from gitconvoy.errors import GitConvoyError

STATE_DIRNAME = ".gitconvoy"
STATE_FILENAME = "state.json"


@dataclass
class FeatureRepo:
    id: str
    path: str
    pr: str | None = None


@dataclass
class Feature:
    name: str
    branch: str
    status: str = "in-progress"
    repos: list[FeatureRepo] = field(default_factory=list)

    def repo_ids(self) -> list[str]:
        return [repo.id for repo in self.repos]

    def add_repo(self, repo_id: str, path: str) -> FeatureRepo:
        for repo in self.repos:
            if repo.id == repo_id:
                return repo
        row = FeatureRepo(id=repo_id, path=path)
        self.repos.append(row)
        return row

    def drop_repo(self, repo_id: str) -> bool:
        before = len(self.repos)
        self.repos = [repo for repo in self.repos if repo.id != repo_id]
        return len(self.repos) < before


@dataclass
class TrainRepo:
    id: str
    path: str
    from_version: str | None = None
    to: str | None = None
    rc_tag: str | None = None
    stable_tag: str | None = None


@dataclass
class Train:
    name: str
    branch: str
    status: str = "cut"
    features: list[str] = field(default_factory=list)
    repos: list[TrainRepo] = field(default_factory=list)

    def add_repo(self, row: TrainRepo) -> None:
        for existing in self.repos:
            if existing.id == row.id:
                return
        self.repos.append(row)


@dataclass
class HotfixRepo:
    id: str
    path: str
    from_version: str | None = None
    to: str | None = None
    stable_tag: str | None = None
    pr: str | None = None


@dataclass
class Hotfix:
    name: str
    branch: str
    status: str = "in-progress"
    repos: list[HotfixRepo] = field(default_factory=list)

    def repo_ids(self) -> list[str]:
        return [repo.id for repo in self.repos]

    def add_repo(self, row: HotfixRepo) -> HotfixRepo:
        for existing in self.repos:
            if existing.id == row.id:
                if row.from_version and not existing.from_version:
                    existing.from_version = row.from_version
                if row.to and not existing.to:
                    existing.to = row.to
                return existing
        self.repos.append(row)
        return row


@dataclass
class State:
    current_feature: str | None = None
    current_train: str | None = None
    current_hotfix: str | None = None
    features: dict[str, Feature] = field(default_factory=dict)
    trains: dict[str, Train] = field(default_factory=dict)
    hotfixes: dict[str, Hotfix] = field(default_factory=dict)

    def require_feature(self, name: str | None = None) -> Feature:
        key = name or self.current_feature
        if not key:
            raise GitConvoyError("no current feature; run: git convoy feature start <name>")
        if key not in self.features:
            raise GitConvoyError(f"unknown feature: {key}")
        return self.features[key]

    def require_train(self, name: str | None = None) -> Train:
        key = name or self.current_train
        if not key:
            raise GitConvoyError("no current train; run: git convoy train cut <name>")
        if key not in self.trains:
            raise GitConvoyError(f"unknown train: {key}")
        return self.trains[key]

    def require_hotfix(self, name: str | None = None) -> Hotfix:
        key = name or self.current_hotfix
        if not key:
            raise GitConvoyError("no current hotfix; run: git convoy hotfix start <name>")
        if key not in self.hotfixes:
            raise GitConvoyError(f"unknown hotfix: {key}")
        return self.hotfixes[key]


def state_path(workspace: Path) -> Path:
    return workspace / STATE_DIRNAME / STATE_FILENAME


def load(workspace: Path) -> State:
    path = state_path(workspace)
    if not path.exists():
        return State()
    raw = json.loads(path.read_text())
    return _from_dict(raw)


def save(workspace: Path, state: State) -> Path:
    path = state_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_to_dict(state), indent=2, sort_keys=True) + "\n")
    return path


def _to_dict(state: State) -> dict[str, Any]:
    return {
        "current_feature": state.current_feature,
        "current_train": state.current_train,
        "current_hotfix": state.current_hotfix,
        "features": {
            name: {
                "name": feat.name,
                "branch": feat.branch,
                "status": feat.status,
                "repos": [asdict(repo) for repo in feat.repos],
            }
            for name, feat in state.features.items()
        },
        "trains": {
            name: {
                "name": train.name,
                "branch": train.branch,
                "status": train.status,
                "features": train.features,
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
            for name, train in state.trains.items()
        },
        "hotfixes": {
            name: {
                "name": item.name,
                "branch": item.branch,
                "status": item.status,
                "repos": [
                    {
                        "id": repo.id,
                        "path": repo.path,
                        "from": repo.from_version,
                        "to": repo.to,
                        "stable_tag": repo.stable_tag,
                        "pr": repo.pr,
                    }
                    for repo in item.repos
                ],
            }
            for name, item in state.hotfixes.items()
        },
    }


def _from_dict(raw: dict[str, Any]) -> State:
    features: dict[str, Feature] = {}
    for name, item in (raw.get("features") or {}).items():
        features[name] = Feature(
            name=item.get("name", name),
            branch=item.get("branch", f"feature/{name}"),
            status=item.get("status", "in-progress"),
            repos=[
                FeatureRepo(
                    id=row["id"],
                    path=row["path"],
                    pr=row.get("pr"),
                )
                for row in item.get("repos") or []
            ],
        )
    trains: dict[str, Train] = {}
    for name, item in (raw.get("trains") or {}).items():
        trains[name] = Train(
            name=item.get("name", name),
            branch=item.get("branch", f"release/{name}"),
            status=item.get("status", "cut"),
            features=list(item.get("features") or []),
            repos=[
                TrainRepo(
                    id=row["id"],
                    path=row["path"],
                    from_version=row.get("from") or row.get("from_version"),
                    to=row.get("to"),
                    rc_tag=row.get("rc_tag"),
                    stable_tag=row.get("stable_tag"),
                )
                for row in item.get("repos") or []
            ],
        )
    hotfixes: dict[str, Hotfix] = {}
    for name, item in (raw.get("hotfixes") or {}).items():
        hotfixes[name] = Hotfix(
            name=item.get("name", name),
            branch=item.get("branch", f"hotfix/{name}"),
            status=item.get("status", "in-progress"),
            repos=[
                HotfixRepo(
                    id=row["id"],
                    path=row["path"],
                    from_version=row.get("from") or row.get("from_version"),
                    to=row.get("to"),
                    stable_tag=row.get("stable_tag"),
                    pr=row.get("pr"),
                )
                for row in item.get("repos") or []
            ],
        )
    return State(
        current_feature=raw.get("current_feature"),
        current_train=raw.get("current_train"),
        current_hotfix=raw.get("current_hotfix"),
        features=features,
        trains=trains,
        hotfixes=hotfixes,
    )
