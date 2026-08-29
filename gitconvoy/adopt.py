from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from gitconvoy import versions
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, TrainRepo


def find_bom_repo(workspace: Path, explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = workspace / path
        if not path.is_dir():
            raise GitConvoyError(f"BOM repo not found: {path}")
        return path
    ops = workspace / "ops"
    if ops.is_dir():
        matches = sorted(
            child
            for child in ops.iterdir()
            if child.is_dir() and child.name.endswith("-bom")
        )
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(child.name for child in matches)
            raise GitConvoyError(
                f"multiple *-bom repos ({names}); pass --bom"
            )
    raise GitConvoyError("no *-bom repo found; pass --bom")


def draft(
    workspace: Path,
    state: State,
    from_version: str,
    to_version: str,
    bom: str | None = None,
    train: str | None = None,
    description: str | None = None,
) -> dict:
    root = find_bom_repo(workspace, bom)
    src = _bom_file(root, from_version)
    dest = _bom_file(root, to_version)
    if not src.exists():
        raise GitConvoyError(f"missing {src}")
    if dest.exists():
        raise GitConvoyError(f"already exists: {dest}")
    shutil.copy(src, dest)
    data = json.loads(dest.read_text())
    data["version"] = _v(to_version)
    if train or state.current_train:
        data["train"] = train or state.current_train
    data["description"] = description or (
        f"Draft. Taking {train or state.current_train or 'selected pins'}. Not production."
    )
    dest.write_text(json.dumps(data, indent=2) + "\n")
    return {
        "ok": True,
        "from": str(src),
        "to": str(dest),
        "version": data["version"],
        "train": data.get("train"),
        "note": "edit pins, then git convoy adopt point --staging-only",
    }


def pin(
    workspace: Path,
    version: str,
    package: str,
    pin_value: str,
    bom: str | None = None,
    ecosystem: str | None = None,
) -> dict:
    root = find_bom_repo(workspace, bom)
    path = _bom_file(root, version)
    if not path.exists():
        raise GitConvoyError(f"missing {path}")
    data = json.loads(path.read_text())
    section = ecosystem or _guess_section(package)
    if section not in data or not isinstance(data[section], dict):
        data[section] = {}
    data[section][package] = pin_value
    path.write_text(json.dumps(data, indent=2) + "\n")
    return {"ok": True, "file": str(path), "section": section, "package": package, "pin": pin_value}


def point(
    workspace: Path,
    version: str,
    bom: str | None = None,
    production: bool = False,
) -> dict:
    root = find_bom_repo(workspace, bom)
    targets = root / "deploy_targets.yml"
    if not targets.exists():
        raise GitConvoyError(f"missing {targets}")
    number = version.lstrip("v")
    text = targets.read_text()
    text, n = re.subn(
        r"(?m)^bom:\s+\S+",
        f"bom: {number}",
        text,
        count=1,
    )
    if n != 1:
        raise GitConvoyError("could not update bom: in deploy_targets.yml")
    enabled = "true" if production else "false"
    text, n = re.subn(
        r"(?m)^(\s+)production:\n(\s+)enabled:\s+\S+",
        rf"\1production:\n\2enabled: {enabled}",
        text,
        count=1,
    )
    if n != 1:
        raise GitConvoyError("could not update production.enabled in deploy_targets.yml")
    targets.write_text(text)
    return {
        "ok": True,
        "file": str(targets),
        "bom": number,
        "production_enabled": production,
        "note": "commit and push this repo to deploy. git-convoy does not push *-bom.",
    }


def take(
    workspace: Path,
    state: State,
    bom: str | None = None,
    train: str | None = None,
    from_version: str | None = None,
    to_version: str | None = None,
    description: str | None = None,
) -> dict:
    train_obj = state.require_train(train)
    if not train_obj.repos:
        raise GitConvoyError(f"train {train_obj.name} has no repos")
    missing = [repo.id for repo in train_obj.repos if not repo.to]
    if missing:
        raise GitConvoyError(
            f"train {train_obj.name} has no versions to pin for: {', '.join(missing)}; "
            "run train tag-rc or train publish first"
        )
    root = find_bom_repo(workspace, bom)
    src = from_version or _pointed_version(root)
    dest = to_version or versions.bump(_strip_v(src), "patch")
    drafted = draft(
        workspace,
        state,
        src,
        dest,
        bom=bom,
        train=train_obj.name,
        description=description,
    )
    bom_data = json.loads(_bom_file(root, dest).read_text())
    pinned: list[dict] = []
    for repo in train_obj.repos:
        pep, npm = _pep_and_npm(repo.to)
        for section, package in _package_targets(repo, bom_data, workspace):
            value = pep if section == "python" else npm
            pin(workspace, dest, package, value, bom=bom, ecosystem=section)
            bom_data.setdefault(section, {})[package] = value
            pinned.append(
                {
                    "id": repo.id,
                    "section": section,
                    "package": package,
                    "pin": value,
                }
            )
    pointed = point(workspace, dest, bom=bom, production=False)
    return {
        "ok": True,
        "train": train_obj.name,
        "from": drafted["from"],
        "to": drafted["to"],
        "version": drafted["version"],
        "pins": pinned,
        "point": pointed,
        "note": pointed["note"],
    }


def promote(workspace: Path, bom: str | None = None) -> dict:
    root = find_bom_repo(workspace, bom)
    version = _pointed_version(root)
    pointed = point(workspace, version, bom=bom, production=True)
    return {
        "ok": True,
        "version": _v(version),
        "point": pointed,
        "note": pointed["note"],
    }


def _pointed_version(root: Path) -> str:
    targets = root / "deploy_targets.yml"
    if not targets.exists():
        raise GitConvoyError(f"missing {targets}")
    match = re.search(r"(?m)^bom:\s+(\S+)", targets.read_text())
    if not match:
        raise GitConvoyError("could not read bom: in deploy_targets.yml")
    return match.group(1).strip().strip("'\"")


def _strip_v(version: str) -> str:
    return version[1:] if version.startswith("v") else version


def _pep_and_npm(version: str) -> tuple[str, str]:
    _major, _minor, _patch, rc = versions.parse(version)
    if rc is None:
        return versions.drop_rc(version)
    return versions.with_rc(version, rc)


def _package_targets(
    repo: TrainRepo,
    bom: dict,
    workspace: Path,
) -> list[tuple[str, str]]:
    short = repo.id.removeprefix("renglo-")
    python_names = (
        []
        if repo.id == "console"
        else [repo.id if repo.id.startswith("renglo-") else f"renglo-{short}"]
    )
    npm_names = (
        ["@renglo/console"] if repo.id == "console" else [f"@renglo/{short}"]
    )
    existing: list[tuple[str, str]] = []
    for name in python_names:
        if name in (bom.get("python") or {}):
            existing.append(("python", name))
    for name in npm_names:
        if name in (bom.get("npm") or {}):
            existing.append(("npm", name))
    for section in ("python", "npm"):
        if repo.id in (bom.get(section) or {}) and (section, repo.id) not in existing:
            existing.append((section, repo.id))
    if existing:
        return existing
    repo_root = workspace / repo.path
    info = versions.read_version(repo_root) if repo_root.is_dir() else {}
    if repo.id == "console":
        return [("npm", "@renglo/console")]
    targets: list[tuple[str, str]] = []
    if info.get("python") or not info.get("npm"):
        targets.append(("python", python_names[0]))
    if info.get("npm"):
        targets.append(("npm", npm_names[0]))
    return targets


def _bom_file(root: Path, version: str) -> Path:
    name = version if version.startswith("v") else f"v{version}"
    if not name.endswith(".json"):
        name = f"{name}.json"
    return root / "bom" / name


def _v(version: str) -> str:
    return version if version.startswith("v") else f"v{version}"


def _guess_section(package: str) -> str:
    if package.startswith("@") or "/" in package:
        return "npm"
    return "python"
