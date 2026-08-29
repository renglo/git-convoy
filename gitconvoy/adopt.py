from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State


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
