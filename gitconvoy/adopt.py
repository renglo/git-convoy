from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from gitconvoy import gitutil, versions
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, Train, TrainRepo
from gitconvoy import ghutil
from gitconvoy import membership
from gitconvoy.workflows import repo_registry_ready
from gitconvoy.workspace import SKIP_DIR_NAMES, discover_repos

_BOM_SKIP = SKIP_DIR_NAMES | {"gitconvoy", "git-convoy"}


def find_bom_repo(workspace: Path, explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = workspace / path
        if not path.is_dir():
            raise GitConvoyError(f"BOM repo not found: {path}")
        return path
    matches = _discover_bom_repos(workspace)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(_bom_label(workspace, path) for path in matches)
        raise GitConvoyError(f"multiple BOM repos ({names}); pass --bom")
    raise GitConvoyError(
        "no BOM repo found; list one under [bom] in .gitconvoy/aux.toml "
        "(git convoy init), use a *-bom directory, or pass --bom"
    )


def _discover_bom_repos(workspace: Path) -> list[Path]:
    """Prefer `.gitconvoy/aux.toml` [bom]; else legacy `*-bom` directory names."""
    listed = membership.load_membership(workspace)["bom"]
    if listed:
        return _resolve_membership_bom(workspace, listed)
    return _discover_bom_repos_by_suffix(workspace)


def _resolve_membership_bom(workspace: Path, listed: list[str]) -> list[Path]:
    by_id = {repo.id: repo.path for repo in discover_repos(workspace)}
    found: list[Path] = []
    missing: list[str] = []
    for repo_id in listed:
        path = by_id.get(repo_id)
        if path is None:
            matches = _find_dirs_named(workspace, repo_id)
            if len(matches) == 1:
                path = matches[0]
            elif len(matches) > 1:
                labels = ", ".join(_bom_label(workspace, item) for item in matches)
                raise GitConvoyError(
                    f"BOM id {repo_id!r} matches multiple directories ({labels}); "
                    "pass --bom"
                )
        if path is None:
            missing.append(repo_id)
            continue
        found.append(path)
    if missing:
        raise GitConvoyError(
            "BOM repo(s) listed in .gitconvoy/aux.toml not found in workspace: "
            + ", ".join(missing)
        )
    return found


def _find_dirs_named(workspace: Path, name: str) -> list[Path]:
    found: list[Path] = []

    def walk(root: Path) -> None:
        try:
            children = sorted(root.iterdir(), key=lambda item: item.name)
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name in _BOM_SKIP:
                continue
            if child.name == name:
                found.append(child)
                continue
            walk(child)

    walk(workspace)
    return found


def _discover_bom_repos_by_suffix(workspace: Path) -> list[Path]:
    found: list[Path] = []

    def walk(root: Path) -> None:
        try:
            children = sorted(root.iterdir(), key=lambda item: item.name)
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name in _BOM_SKIP:
                continue
            if child.name.endswith("-bom"):
                found.append(child)
                continue
            walk(child)

    walk(workspace)
    return found


def _bom_label(workspace: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


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
    require_verify: bool = False,
    no_verify: bool = False,
) -> dict:
    train_obj = state.require_train(train)
    verify_by_repo, verify_summary = _adopt_verify_context(
        workspace,
        state,
        train_obj.name,
        require_verify=require_verify,
        no_verify=no_verify,
    )
    if not train_obj.repos:
        raise GitConvoyError(f"train {train_obj.name} has no repos")
    missing = [repo.id for repo in train_obj.repos if not repo.to]
    if missing:
        raise GitConvoyError(
            f"train {train_obj.name} has no versions to pin for: {', '.join(missing)}; "
            "run train tag-rc or train publish first"
        )
    root = find_bom_repo(workspace, bom)
    src, dest, refresh = _resolve_take_target(
        root,
        train_obj,
        from_version=from_version,
        to_version=to_version,
    )
    if refresh:
        bom_path = _bom_file(root, dest)
        existing = json.loads(bom_path.read_text())
        _update_draft_metadata(
            root,
            dest,
            train_obj,
            description,
            existing=existing,
            refresh=True,
        )
        drafted = {
            "from": str(bom_path),
            "to": str(bom_path),
            "version": existing.get("version") or _v(dest),
        }
        mode = "refresh"
    else:
        drafted = draft(
            workspace,
            state,
            src,
            dest,
            bom=bom,
            train=train_obj.name,
            description=description
            or f"Draft. Taking {train_obj.name}. Not production.",
        )
        mode = "draft"
    bom_data = json.loads(_bom_file(root, dest).read_text())
    pinned: list[dict] = []
    for repo in train_obj.repos:
        use_registry, pin_kind = _resolve_pin_strategy(
            repo, workspace, verify_by_repo
        )
        if not use_registry:
            pinned.extend(
                _clear_package_pins(root, dest, repo, workspace, bom_data)
            )
        repo_package_pins: list[tuple[str, str]] = []
        if use_registry:
            pep, npm = _pep_and_npm(repo.to)
            for section, package in _package_targets(repo, bom_data, workspace):
                value = pep if section == "python" else npm
                pin(workspace, dest, package, value, bom=bom, ecosystem=section)
                bom_data.setdefault(section, {})[package] = value
                repo_package_pins.append((section, package))
                pinned.append(
                    {
                        "id": repo.id,
                        "section": section,
                        "package": package,
                        "pin": value,
                        "kind": pin_kind,
                    }
                )
        git_kind = "fallback" if pin_kind == "fallback" else "git"
        if not use_registry or _needs_repo_sha(repo, repo_package_pins):
            for row in _pin_repo_shas(
                workspace,
                dest,
                bom_data,
                repo,
                train_obj,
                bom=bom,
                root=root,
                create=not use_registry,
            ):
                row["kind"] = git_kind
                pinned.append(row)
        elif repo_package_pins:
            pinned.extend(
                _clear_repo_shas(root, dest, repo, workspace, bom_data)
            )
    staging_only = not refresh
    pointed = point(
        workspace,
        dest,
        bom=bom,
        production=False if staging_only else _production_enabled(root),
    )
    note = pointed["note"]
    if mode == "refresh":
        note = (
            f"Updated bom/{_v(dest).lstrip('v')}.json in place for train {train_obj.name}. "
            + note
        )
    payload = {
        "ok": True,
        "mode": mode,
        "train": train_obj.name,
        "from": drafted["from"],
        "to": drafted["to"],
        "version": drafted["version"],
        "pins": pinned,
        "point": pointed,
        "note": note,
    }
    if verify_summary is not None:
        payload["verify"] = verify_summary
    return payload


def promote(
    workspace: Path,
    state: State,
    bom: str | None = None,
    *,
    require_verify: bool = False,
    no_verify: bool = False,
) -> dict:
    train_obj = state.require_train()
    if train_obj.status != "published":
        raise GitConvoyError(
            f"train {train_obj.name} is {train_obj.status}; "
            "run train publish before adopt --production"
        )
    taken = take(
        workspace,
        state,
        bom=bom,
        train=train_obj.name,
        require_verify=require_verify,
        no_verify=no_verify,
    )
    root = find_bom_repo(workspace, bom)
    version = _strip_v(taken["version"])
    train = _validate_production_promotion(root, state, version)
    pointed = point(workspace, version, bom=bom, production=True)
    description = _production_description(train.name)
    _set_bom_description(root, version, description)
    return {
        "ok": True,
        "mode": taken["mode"],
        "train": train.name,
        "version": taken["version"],
        "description": description,
        "pins": taken["pins"],
        "take": {"from": taken["from"], "to": taken["to"]},
        "point": pointed,
        "note": (
            pointed["note"]
            + " CI deploys staging, verifies it, then production; "
            "production is blocked if staging fails."
        ),
    }


def _validate_production_promotion(root: Path, state: State, version: str) -> Train:
    bom_path = _bom_file(root, version)
    if not bom_path.exists():
        raise GitConvoyError(f"missing {bom_path}")
    data = json.loads(bom_path.read_text())
    train_name = data.get("train")
    if not train_name:
        raise GitConvoyError(
            f"bom/{_strip_v(_v(version))}.json has no train; run adopt first"
        )
    if train_name not in state.trains:
        raise GitConvoyError(
            f"bom train {train_name} is not in git-convoy state; run adopt from that train"
        )
    train = state.trains[train_name]
    if train.status != "published":
        raise GitConvoyError(
            f"train {train_name} is {train.status}; run train publish before adopt --production"
        )
    rc_pins = _rc_pins_in_bom(data)
    if rc_pins:
        raise GitConvoyError(
            "BOM still has release-candidate pins; run adopt after train publish: "
            + ", ".join(rc_pins)
        )
    return train


def _rc_pins_in_bom(data: dict) -> list[str]:
    found: list[str] = []
    for section in ("python", "npm"):
        packages = data.get(section)
        if not isinstance(packages, dict):
            continue
        for name, pin in packages.items():
            if _pin_is_rc(str(pin)):
                found.append(f"{section}/{name}={pin}")
    return found


def _pin_is_rc(pin: str) -> bool:
    try:
        _major, _minor, _patch, rc = versions.parse(pin)
        return rc is not None
    except GitConvoyError:
        return bool(re.search(r"(?:rc\d|-rc\.)", pin, re.I))


def _pointed_version(root: Path) -> str:
    targets = root / "deploy_targets.yml"
    if not targets.exists():
        raise GitConvoyError(f"missing {targets}")
    match = re.search(r"(?m)^bom:\s+(\S+)", targets.read_text())
    if not match:
        raise GitConvoyError("could not read bom: in deploy_targets.yml")
    return match.group(1).strip().strip("'\"")


def _resolve_take_target(
    root: Path,
    train: Train,
    *,
    from_version: str | None,
    to_version: str | None,
) -> tuple[str, str, bool]:
    pointed = _pointed_version(root)
    if to_version:
        src = from_version or pointed
        return src, _strip_v(to_version), False
    if from_version:
        return from_version, versions.bump(_strip_v(from_version), "patch"), False
    pointed_path = _bom_file(root, pointed)
    if pointed_path.exists():
        data = json.loads(pointed_path.read_text())
        if data.get("train") == train.name:
            return pointed, _strip_v(pointed), True
    return pointed, versions.bump(_strip_v(pointed), "patch"), False


def _production_enabled(root: Path) -> bool:
    targets = root / "deploy_targets.yml"
    if not targets.exists():
        return False
    match = re.search(
        r"(?m)^(\s+)production:\n\s+enabled:\s+(\S+)",
        targets.read_text(),
    )
    return bool(match and match.group(2).lower() == "true")


def _production_description(train: str) -> str:
    return f"Production. Release {train}."


def _set_bom_description(root: Path, version: str, description: str) -> None:
    path = _bom_file(root, version)
    data = json.loads(path.read_text())
    data["description"] = description
    path.write_text(json.dumps(data, indent=2) + "\n")


def _update_draft_metadata(
    root: Path,
    version: str,
    train: Train,
    description: str | None,
    *,
    existing: dict,
    refresh: bool,
) -> None:
    path = _bom_file(root, version)
    data = dict(existing)
    data["train"] = train.name
    data["description"] = _description_for_take(
        existing.get("description"),
        train,
        description,
        refresh=refresh,
        production_enabled=_production_enabled(root),
    )
    path.write_text(json.dumps(data, indent=2) + "\n")


def _description_for_take(
    existing: str | None,
    train: Train,
    override: str | None,
    *,
    refresh: bool,
    production_enabled: bool,
) -> str:
    if override:
        return override
    if refresh:
        if production_enabled or (existing or "").strip().startswith("Production."):
            return existing or _production_description(train.name)
        if train.status == "published":
            return f"Staging. Release {train.name}."
        return _increment_release_description(existing or "", train.name)
    return f"Draft. Taking {train.name}. Not production."


def _increment_release_description(description: str, train: str) -> str:
    match = re.search(r"Release ([A-Z])", description, re.I)
    if match:
        next_ord = min(ord(match.group(1).upper()) + 1, ord("Z"))
        letter = chr(next_ord)
        return re.sub(
            r"Release [A-Z]",
            f"Release {letter}",
            description,
            count=1,
            flags=re.I,
        )
    if description.strip():
        return description.rstrip().removesuffix(".") + ". Release B."
    return f"Draft. Taking {train}. Release B. Not production."


def _strip_v(version: str) -> str:
    return version[1:] if version.startswith("v") else version


def _pep_and_npm(version: str) -> tuple[str, str]:
    _major, _minor, _patch, rc = versions.parse(version)
    if rc is None:
        return versions.drop_rc(version)
    return versions.with_rc(version, rc)


def _python_package_names(
    repo: TrainRepo,
    workspace: Path,
    *,
    required: bool = True,
) -> list[str]:
    """Python distribution names from pyproject only (no invented fallbacks)."""
    if repo.id == "console":
        return []
    actual = versions.read_python_package_name(workspace / repo.path)
    if actual:
        return [actual]
    if not required:
        return []
    info = versions.read_version(workspace / repo.path)
    if info.get("python"):
        raise GitConvoyError(
            f"{repo.id}: missing [project] name in pyproject.toml "
            "(package/ or root); cannot pin python package"
        )
    return []


def _npm_package_names(
    repo: TrainRepo,
    workspace: Path,
    *,
    required: bool = True,
) -> list[str]:
    """npm package names from package.json only (no invented fallbacks)."""
    actual = versions.read_npm_package_name(workspace / repo.path)
    if actual:
        return [actual]
    info = versions.read_version(workspace / repo.path)
    if not info.get("npm"):
        return []
    if not required:
        return []
    raise GitConvoyError(
        f"{repo.id}: missing name in ui/package.json or package.json; "
        "cannot pin npm package"
    )


def _package_targets(
    repo: TrainRepo,
    bom: dict,
    workspace: Path,
) -> list[tuple[str, str]]:
    repo_root = workspace / repo.path
    registry = repo_registry_ready(repo_root, repo.id)
    if registry is not True:
        return []
    python_names = _python_package_names(repo, workspace)
    npm_names = _npm_package_names(repo, workspace)
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
    info = versions.read_version(repo_root) if repo_root.is_dir() else {}
    if repo.id == "console":
        return [("npm", npm_names[0])]
    targets: list[tuple[str, str]] = []
    if info.get("python") or not info.get("npm"):
        targets.append(("python", python_names[0]))
    if info.get("npm"):
        targets.append(("npm", npm_names[0]))
    return targets


def _candidate_package_pins(
    repo: TrainRepo,
    workspace: Path,
) -> list[tuple[str, str]]:
    pins: list[tuple[str, str]] = []
    for name in _python_package_names(repo, workspace, required=False):
        pins.append(("python", name))
    for name in _npm_package_names(repo, workspace, required=False):
        pins.append(("npm", name))
    return pins


def _clear_package_pins(
    root: Path,
    version: str,
    repo: TrainRepo,
    workspace: Path,
    bom_data: dict,
) -> list[dict]:
    path = _bom_file(root, version)
    data = json.loads(path.read_text())
    cleared: list[dict] = []
    for section, package in _candidate_package_pins(repo, workspace):
        section_data = data.get(section)
        if not isinstance(section_data, dict) or package not in section_data:
            continue
        del section_data[package]
        if not section_data:
            data.pop(section, None)
        bom_section = bom_data.get(section)
        if isinstance(bom_section, dict):
            bom_section.pop(package, None)
            if not bom_section:
                bom_data.pop(section, None)
        cleared.append(
            {
                "id": repo.id,
                "section": section,
                "package": package,
                "pin": "(removed)",
                "action": "cleared",
            }
        )
    if cleared:
        path.write_text(json.dumps(data, indent=2) + "\n")
    return cleared


def _adopt_verify_context(
    workspace: Path,
    state: State,
    train_name: str,
    *,
    require_verify: bool,
    no_verify: bool,
) -> tuple[dict[str, str] | None, dict | None]:
    if no_verify or not ghutil.gh_available():
        return None, None
    from gitconvoy import train as train_cmd

    result = train_cmd.verify(workspace, state, train_name)
    if require_verify and not result["ok"]:
        raise GitConvoyError(train_cmd.format_verify_text(result))
    by_repo = {
        row["id"]: row.get("status") or "unknown"
        for row in result.get("repos") or []
    }
    summary = {
        "ran": True,
        "verified_count": result.get("verified_count", 0),
        "skipped_count": result.get("skipped_count", 0),
        "pending_count": result.get("pending_count", 0),
        "failed_count": result.get("failed_count", 0),
        "repo_count": result.get("repo_count", 0),
    }
    return by_repo, summary


def _resolve_pin_strategy(
    repo: TrainRepo,
    workspace: Path,
    verify_by_repo: dict[str, str] | None,
) -> tuple[bool, str]:
    """Return (use_registry_pins, kind label for registry rows)."""
    if verify_by_repo is None:
        return _heuristic_pin_strategy(repo, workspace)
    status = verify_by_repo.get(repo.id, "unknown")
    if status == "success":
        return True, "registry"
    if status == "skip":
        return _heuristic_pin_strategy(repo, workspace)
    if status in {"pending", "missing"}:
        return _heuristic_pin_strategy(repo, workspace)
    return False, "fallback"


def _heuristic_pin_strategy(
    repo: TrainRepo,
    workspace: Path,
) -> tuple[bool, str]:
    registry = repo_registry_ready(workspace / repo.path, repo.id)
    if registry is not True:
        return False, "git"
    return True, "registry"


def _needs_repo_sha(
    repo: TrainRepo,
    package_pins: list[tuple[str, str]],
) -> bool:
    """Git commit pins are the fallback when registry pins do not cover deploy."""
    sections = {section for section, _ in package_pins}
    if "npm" in sections:
        return False
    if not package_pins:
        return True
    if "python" in sections:
        return repo.path.startswith("extensions/") or repo.id == "console"
    return True


def _clear_repo_shas(
    root: Path,
    version: str,
    repo: TrainRepo,
    workspace: Path,
    bom_data: dict,
) -> list[dict]:
    keys = _bom_repo_keys(workspace, repo, bom_data)
    if not keys:
        return []
    path = _bom_file(root, version)
    data = json.loads(path.read_text())
    repos_section = data.get("repos")
    if not isinstance(repos_section, dict):
        return []
    cleared: list[dict] = []
    for key in keys:
        if key not in repos_section:
            continue
        del repos_section[key]
        bom_repos = bom_data.get("repos")
        if isinstance(bom_repos, dict):
            bom_repos.pop(key, None)
        cleared.append(
            {
                "id": repo.id,
                "section": "repos",
                "package": key,
                "pin": "(removed)",
                "action": "cleared",
                "kind": "git",
            }
        )
    if not repos_section:
        data.pop("repos", None)
        if isinstance(bom_data.get("repos"), dict) and not bom_data["repos"]:
            bom_data.pop("repos", None)
    if cleared:
        path.write_text(json.dumps(data, indent=2) + "\n")
    return cleared


def _bom_repo_keys(workspace: Path, repo: TrainRepo, bom: dict) -> list[str]:
    repos_section = bom.get("repos")
    if not isinstance(repos_section, dict):
        return []
    repo_path = workspace / repo.path
    slug = gitutil.github_slug(repo_path)
    matches: list[str] = []
    if slug and slug in repos_section:
        matches.append(slug)
    suffix = f"/{repo.id}"
    for key in repos_section:
        if key.endswith(suffix) and key not in matches:
            matches.append(key)
    return matches


def _train_repo_commit(workspace: Path, repo: TrainRepo, train: Train) -> str | None:
    repo_path = workspace / repo.path
    if not repo_path.is_dir():
        return None
    for ref in (repo.stable_tag, repo.rc_tag, train.branch, "HEAD"):
        if not ref:
            continue
        sha = gitutil.rev_parse(repo_path, ref)
        if sha:
            return sha
    return None


def _pin_repo_shas(
    workspace: Path,
    version: str,
    bom_data: dict,
    repo: TrainRepo,
    train: Train,
    *,
    bom: str | None,
    root: Path,
    create: bool = False,
) -> list[dict]:
    keys = _bom_repo_keys(workspace, repo, bom_data)
    repo_path = workspace / repo.path
    if not keys and create:
        slug = gitutil.github_slug(repo_path)
        if slug:
            keys = [slug]
    if not keys:
        return []
    commit = _train_repo_commit(workspace, repo, train)
    if not commit:
        return []
    path = _bom_file(root, version)
    data = json.loads(path.read_text())
    repos_section = data.setdefault("repos", {})
    pinned: list[dict] = []
    for key in keys:
        entry = repos_section.get(key)
        if not isinstance(entry, dict):
            if not create:
                continue
            url = gitutil.origin_url(repo_path)
            if not url:
                continue
            entry = {"url": url, "branch": "main"}
        updated = dict(entry)
        updated["commit"] = commit
        repos_section[key] = updated
        bom_data.setdefault("repos", {})[key] = updated
        pinned.append(
            {
                "id": repo.id,
                "section": "repos",
                "package": key,
                "pin": commit,
            }
        )
    path.write_text(json.dumps(data, indent=2) + "\n")
    return pinned


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
