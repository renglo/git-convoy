from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from gitconvoy import gitutil, versions
from gitconvoy.catalog import (
    PackageSlot,
    catalog_allowlist,
    load_package_catalog,
    load_registry_scopes,
    slot_for_npm,
    slot_for_python,
    slot_for_repo,
    tenant_config_path,
    unregistered_wl_slots,
)
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, Train, TrainRepo
from gitconvoy import ghutil
from gitconvoy import membership
from gitconvoy.bom_layout import (
    CONSOLE_NPM_HOST,
    apply_released_platform,
    copy_split_bom_draft,
    load_placement,
    load_platform,
    load_staging_platform,
    merge_union_bom,
    promote_staging_pins,
    required_master_pins,
    staging_release_pin,
    sync_deploy_target_versions,
    sync_staging_pins,
    write_bom_file,
    write_split_boms,
)
from gitconvoy.workflows import repo_registry_ready
from gitconvoy.workspace import SKIP_DIR_NAMES, discover_repos

# A new *-bom repo's renglo.yaml names this pin before any manifest exists.
FIRST_BOM_VERSION = "0.0.1"

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
        "no BOM repo found; list one under [bom] in .gitconvoy/ops.toml "
        "(git convoy init), use a *-bom directory, or pass --bom"
    )


def _discover_bom_repos(workspace: Path) -> list[Path]:
    """Prefer `.gitconvoy/ops.toml` [bom]; else legacy `*-bom` directory names."""
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
            "BOM repo(s) listed in .gitconvoy/ops.toml not found in workspace: "
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


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _uses_three_bom_layout(root: Path) -> bool:
    placement = load_placement(root)
    if placement.hub_python or placement.peers:
        return True
    return (root / "console_bom").is_dir()


def _has_any_bom_manifest(root: Path) -> bool:
    """True when this repo already has a versioned hub, console, or peer BOM."""
    bom = root / "bom"
    if bom.is_dir() and any(bom.glob("v*.json")):
        return True
    console = root / "console_bom"
    if console.is_dir() and any(console.glob("v*.json")):
        return True
    peers = root / "peers_bom"
    return peers.is_dir() and any(peers.glob("*/v*.json"))


def _is_first_bom(root: Path, from_version: str, to_version: str) -> bool:
    return (
        _strip_v(from_version) == FIRST_BOM_VERSION
        and _strip_v(to_version) == FIRST_BOM_VERSION
        and not _has_any_bom_manifest(root)
    )


def _seed_first_bom(
    root: Path,
    dest: Path,
    *,
    train: str | None,
    description: str | None,
) -> dict:
    """Write bom/v0.0.1.json when there is no manifest to copy forward."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    master: dict = {
        "version": _v(FIRST_BOM_VERSION),
        "created_at": _utc_now_iso(),
        "description": description
        or f"Draft. Taking {train or 'selected pins'}. Not production.",
        "python": {},
        "npm": {},
        "repos": {},
    }
    if train:
        master["train"] = train
    if _uses_three_bom_layout(root):
        write_split_boms(
            root,
            FIRST_BOM_VERSION,
            master,
            catalog=load_package_catalog(root),
        )
    else:
        write_bom_file(root, dest, master)
    return {
        "ok": True,
        "from": str(dest),
        "to": str(dest),
        "version": master["version"],
        "train": master.get("train"),
        "seeded": True,
        "note": "first BOM is 0.0.1; no previous manifest to copy",
    }


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
    if _is_first_bom(root, from_version, to_version):
        return _seed_first_bom(
            root,
            dest,
            train=train or state.current_train,
            description=description,
        )
    if not src.exists():
        raise GitConvoyError(f"missing {src}")
    if dest.exists():
        raise GitConvoyError(f"already exists: {dest}")
    if _uses_three_bom_layout(root):
        copy_split_bom_draft(root, from_version, to_version)
        master = merge_union_bom(root, to_version)
    else:
        shutil.copy(src, dest)
        master = json.loads(dest.read_text())
    master["version"] = _v(to_version)
    master["created_at"] = _utc_now_iso()
    if train or state.current_train:
        master["train"] = train or state.current_train
    master["description"] = description or (
        f"Draft. Taking {train or state.current_train or 'selected pins'}. Not production."
    )
    if _uses_three_bom_layout(root):
        write_split_boms(root, to_version, master, catalog=load_package_catalog(root))
    else:
        write_bom_file(root, dest, master)
    data = master
    return {
        "ok": True,
        "from": str(src),
        "to": str(dest),
        "version": data["version"],
        "train": data.get("train"),
        "note": "edit pins, then git convoy bom point",
    }


def pin(
    workspace: Path,
    version: str,
    package: str,
    pin_value: str,
    bom: str | None = None,
    ecosystem: str | None = None,
    *,
    split: bool = True,
) -> dict:
    root = find_bom_repo(workspace, bom)
    path = _bom_file(root, version)
    if _uses_three_bom_layout(root):
        master = merge_union_bom(root, version)
        if not master.get("python") and not master.get("npm") and not path.is_file():
            raise GitConvoyError(f"missing split BOM files for {version}")
    elif not path.exists():
        raise GitConvoyError(f"missing {path}")
    else:
        master = json.loads(path.read_text())
    section = ecosystem or _guess_section(package)
    master.setdefault(section, {})
    if not isinstance(master[section], dict):
        master[section] = {}
    master[section][package] = pin_value
    write_bom_file(root, path, master)
    if split and _uses_three_bom_layout(root):
        write_split_boms(root, version, master, catalog=load_package_catalog(root))
    return {"ok": True, "file": str(path), "section": section, "package": package, "pin": pin_value}


def point(
    workspace: Path,
    version: str,
    bom: str | None = None,
    production: bool = False,
    *,
    hotfix: bool = False,
) -> dict:
    root = find_bom_repo(workspace, bom)
    targets = tenant_config_path(root)
    if not targets.exists():
        raise GitConvoyError(f"missing {targets}")
    number = version.lstrip("v")
    if targets.name == "renglo.yaml" and hotfix:
        sync_deploy_target_versions(root, version)
        _set_production_enabled(root, False)
        return {
            "ok": True,
            "file": str(targets),
            "bom": number,
            "production_enabled": False,
            "note": (
                "updated production pins. staging block, if any, was left in place. "
                "production.enabled stays false until bom --production."
            ),
        }
    if targets.name == "renglo.yaml" and not production:
        sync_staging_pins(
            root,
            version,
            platform=load_staging_platform(root) or load_platform(root),
        )
        _set_production_enabled(root, False)
        return {
            "ok": True,
            "file": str(targets),
            "bom": number,
            "production_enabled": False,
            "note": (
                "staging pins updated. production pins were left in place. "
                "production.enabled stays false until bom --production."
            ),
        }
    if targets.name == "renglo.yaml" and production:
        if not promote_staging_pins(root):
            sync_deploy_target_versions(root, version)
    elif targets.name != "renglo.yaml":
        if _uses_three_bom_layout(root):
            sync_deploy_target_versions(root, version)
        else:
            text, n = re.subn(
                r"(?m)^bom:\s+\S+",
                f"bom: {number}",
                targets.read_text(),
                count=1,
            )
            if n != 1:
                raise GitConvoyError("could not update bom: in deploy_targets.yml")
            targets.write_text(text)
    _set_production_enabled(root, production)
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
    from gitconvoy.train import _refuse_unviable

    _refuse_unviable(workspace, state, train_obj)
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
    from gitconvoy.platform_check import report_for_take

    platform_report = report_for_take(
        workspace,
        train_obj,
        root,
        from_version=from_version,
    )
    released_platform = apply_released_platform(root, train_obj.repos)
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
    if _uses_three_bom_layout(root):
        bom_data = merge_union_bom(root, dest)
        write_bom_file(root, _bom_file(root, dest), bom_data)
    catalog = load_package_catalog(root)
    pinned: list[dict] = []
    for repo in train_obj.repos:
        use_registry, pin_kind = _resolve_pin_strategy(
            repo, workspace, verify_by_repo
        )
        if not use_registry:
            pinned.extend(
                _clear_package_pins(
                    root, dest, repo, workspace, bom_data, catalog
                )
            )
        repo_package_pins: list[tuple[str, str]] = []
        if use_registry:
            pep, npm = _pep_and_npm(repo.to)
            for section, package in _package_targets(
                repo, bom_data, workspace, catalog
            ):
                value = pep if section == "python" else npm
                pin(workspace, dest, package, value, bom=bom, ecosystem=section, split=False)
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
    placement = load_placement(root)
    pinned.extend(
        _ensure_placement_pins(
            workspace,
            root,
            dest,
            bom_data,
            train_obj,
            src,
            catalog,
            placement,
        )
    )
    pinned = _pin_unregistered_wl(workspace, root, dest, bom_data, catalog, pinned)
    if catalog is not None:
        pinned.extend(_prune_bom_to_catalog(root, dest, bom_data, catalog))
        _restore_adopt_pins(root, dest, bom_data, pinned)
    if _uses_three_bom_layout(root):
        master = json.loads(_bom_file(root, dest).read_text())
        master = _merge_master_from_bom_data(master, bom_data)
        write_split_boms(root, dest, master, catalog=catalog)
    # Plain bom always points staging and leaves production.enabled false.
    # Production pins move only in promote(), via bom --production.
    pointed = point(
        workspace,
        dest,
        bom=bom,
        production=False,
    )
    note = pointed["note"]
    seeded = bool(drafted.get("seeded"))
    if seeded:
        note = "Created the first BOM at 0.0.1. " + note
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
        "files": _written_bom_summaries(root, dest),
        "point": pointed,
        "platform": load_platform(root),
        "platform_source": "renglo-ops" if released_platform else "renglo.yaml",
        "platform_warnings": platform_report["platform_warnings"],
        "seeded": seeded,
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
            "run train publish before bom --production"
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
    note = (
        pointed["note"]
        + " CI deploys staging, verifies it, then production; "
        "production is blocked if staging fails."
    )
    if taken.get("seeded"):
        note = "Created the first BOM at 0.0.1. " + note
    payload = {
        "ok": True,
        "mode": taken["mode"],
        "train": train.name,
        "version": taken["version"],
        "description": description,
        "pins": taken["pins"],
        "files": _written_bom_summaries(root, version),
        "take": {"from": taken["from"], "to": taken["to"]},
        "point": pointed,
        "platform_warnings": taken.get("platform_warnings") or [],
        "seeded": bool(taken.get("seeded")),
        "note": note,
    }
    if taken.get("verify") is not None:
        payload["verify"] = taken["verify"]
    return payload


def _merge_master_from_bom_data(master: dict, bom_data: dict) -> dict:
    """Ensure split uses the full in-memory pin set from adopt."""
    merged = dict(master)
    for section in ("python", "npm"):
        block = bom_data.get(section)
        if isinstance(block, dict):
            merged[section] = {**merged.get(section, {}), **block}
    repos = bom_data.get("repos")
    if isinstance(repos, dict):
        merged["repos"] = {**merged.get("repos", {}), **repos}
    for key in ("version", "created_at", "description", "train"):
        if bom_data.get(key):
            merged[key] = bom_data[key]
    return merged


def _validate_production_promotion(root: Path, state: State, version: str) -> Train:
    if _uses_three_bom_layout(root):
        data = merge_union_bom(root, version)
    else:
        bom_path = _bom_file(root, version)
        if not bom_path.exists():
            raise GitConvoyError(f"missing {bom_path}")
        data = json.loads(bom_path.read_text())
    train_name = data.get("train")
    if not train_name:
        raise GitConvoyError(
            f"bom/{_strip_v(_v(version))}.json has no train; run git convoy bom first"
        )
    if train_name not in state.trains:
        raise GitConvoyError(
            f"bom train {train_name} is not in git-convoy state; run git convoy bom from that train"
        )
    train = state.trains[train_name]
    if train.status != "published":
        raise GitConvoyError(
            f"train {train_name} is {train.status}; run train publish before bom --production"
        )
    rc_pins = _rc_pins_in_bom(data)
    if rc_pins:
        raise GitConvoyError(
            "BOM still has release-candidate pins; run git convoy bom after train publish: "
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


def _pointed_version(root: Path, *, prefer_staging: bool = False) -> str:
    targets = tenant_config_path(root)
    if not targets.exists():
        raise GitConvoyError(f"missing {targets}")
    text = targets.read_text()
    if targets.name == "renglo.yaml":
        if prefer_staging:
            staged = staging_release_pin(root)
            if staged:
                return staged
        match = re.search(r"(?ms)^release:\n(.*?)(?=^\S|\Z)", text)
        body = match.group(1) if match else text
        match = re.search(r"(?m)^[ \t]+bom:\s+(\S+)", body)
    else:
        match = re.search(r"(?m)^bom:\s+(\S+)", text)
    if not match:
        raise GitConvoyError(f"could not read the release pin in {targets.name}")
    return match.group(1).strip().strip("'\"")


def _resolve_take_target(
    root: Path,
    train: Train,
    *,
    from_version: str | None,
    to_version: str | None,
) -> tuple[str, str, bool]:
    pointed = _pointed_version(root, prefer_staging=True)
    if to_version:
        src = from_version or pointed
        return src, _strip_v(to_version), False
    if from_version:
        return from_version, versions.bump(_strip_v(from_version), "patch"), False
    if not _has_any_bom_manifest(root):
        return FIRST_BOM_VERSION, FIRST_BOM_VERSION, False
    pointed_path = _bom_file(root, pointed)
    if pointed_path.exists():
        data = json.loads(pointed_path.read_text())
        if data.get("train") == train.name:
            return pointed, _strip_v(pointed), True
    nxt = versions.bump(_strip_v(pointed), "patch")
    nxt_path = _bom_file(root, nxt)
    if nxt_path.is_file():
        data = json.loads(nxt_path.read_text())
        if data.get("train") == train.name:
            if _bom_is_published(data):
                raise GitConvoyError(
                    f"bom/{_strip_v(nxt)}.json is the published release for "
                    f"train {train.name}; it is not changed after production"
                )
            # The draft is already on disk, but the staging/release pin still
            # names the previous version. Keep editing that file.
            return pointed, _strip_v(nxt), True
    return pointed, nxt, False


def _bom_is_published(data: dict) -> bool:
    return str(data.get("description") or "").strip().startswith("Production.")


def _set_production_enabled(root: Path, enabled: bool) -> None:
    """Turn production deploys on only for a final-tag promotion."""
    targets = tenant_config_path(root)
    flag = "true" if enabled else "false"
    text, n = re.subn(
        r"(?m)^(\s+production:\n(?:[ \t].*\n)*?[ \t]+enabled:\s+)\S+",
        rf"\g<1>{flag}",
        targets.read_text(),
        count=1,
    )
    if n != 1:
        raise GitConvoyError(f"could not update production.enabled in {targets.name}")
    targets.write_text(text)


def _production_description(train: str) -> str:
    return f"Production. Release {train}."


def _set_bom_description(root: Path, version: str, description: str) -> None:
    if _uses_three_bom_layout(root):
        master = merge_union_bom(root, version)
        master["description"] = description
        write_split_boms(root, version, master, catalog=load_package_catalog(root))
        return
    path = _bom_file(root, version)
    data = json.loads(path.read_text())
    data["description"] = description
    write_bom_file(root, path, data)


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
    )
    write_bom_file(root, path, data)


def _description_for_take(
    existing: str | None,
    train: Train,
    override: str | None,
    *,
    refresh: bool,
) -> str:
    if override:
        return override
    if refresh:
        # A published train's plain bom is the staging release. Production
        # wording is written only by bom --production.
        if train.status == "published":
            return f"Staging. Release {train.name}."
        if (existing or "").strip().startswith("Production."):
            return f"Draft. Taking {train.name}. Not production."
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
    catalog: list[PackageSlot] | None = None,
) -> list[tuple[str, str]]:
    repo_root = workspace / repo.path
    python_names = _python_package_names(repo, workspace, required=False)
    npm_names = _npm_package_names(repo, workspace, required=False)
    if catalog is not None:
        slot = slot_for_repo(
            catalog,
            repo.id,
            npm_name=npm_names[0] if npm_names else "",
            python_names=python_names,
        )
        if slot is None:
            return []
        targets: list[tuple[str, str]] = []
        if slot.python:
            targets.append(("python", slot.python))
        if slot.npm:
            targets.append(("npm", slot.npm))
        return targets
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


def _master_at_version(root: Path, version: str) -> dict:
    text = (version or "").strip()
    if not text:
        return {}
    if _uses_three_bom_layout(root):
        return merge_union_bom(root, text)
    path = _bom_file(root, text)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    return data if isinstance(data, dict) else {}


def _repo_id_for_python_dist(dist: str, catalog: list[PackageSlot] | None) -> str | None:
    if catalog:
        slot = slot_for_python(catalog, dist)
        if slot:
            return slot.id
    if dist in ("renglo-lib", "renglo-api"):
        return dist
    if dist.startswith("renglo-"):
        return dist.removeprefix("renglo-")
    return None


def _repo_path_by_id(workspace: Path, repo_id: str) -> Path | None:
    try:
        repos = discover_repos(workspace)
    except GitConvoyError:
        return None
    for repo in repos:
        if repo.id == repo_id:
            path = workspace / repo.path
            return path if path.is_dir() else None
    return None


def _train_owned_packages(
    workspace: Path,
    train: Train,
    bom_data: dict,
    catalog: list[PackageSlot] | None,
) -> set[tuple[str, str]]:
    """Packages whose pin this train already chose."""
    owned: set[tuple[str, str]] = set()
    for repo in train.repos:
        for section, package in _package_targets(repo, bom_data, workspace, catalog):
            owned.add((section, package))
    return owned


def _environment_version(
    workspace: Path,
    repo_id: str | None,
    section: str,
) -> str | None:
    """Latest stable version in the local clone. Rc tags are not stable."""
    if not repo_id:
        return None
    repo_path = _repo_path_by_id(workspace, repo_id)
    if repo_path is None:
        return None
    tag = gitutil.last_stable_tag(repo_path)
    if not tag:
        return None
    info = versions.read_version_at_ref(repo_path, tag)
    key = "python" if section == "python" else "npm"
    raw = str(info.get(key) or "").strip()
    if not raw:
        return None
    try:
        pep, npm = versions.drop_rc(raw)
    except GitConvoyError:
        return raw
    return pep if section == "python" else npm


def _off_train_placement_pin(
    *,
    workspace: Path,
    bom_data: dict,
    section: str,
    package: str,
    repo_id: str | None,
    previous_pin: str,
    train_owned: set[tuple[str, str]],
    from_version: str,
) -> dict | None:
    """Pin a package the train did not touch from the local stable tag.

    The previous BOM is only the fallback when this workspace has no stable tag
    for that repo. A copied pin is replaced when the local stable tag differs.
    """
    if (section, package) in train_owned:
        return None
    live = bom_data.get(section)
    live_pin = str(live.get(package) or "").strip() if isinstance(live, dict) else ""
    environment = _environment_version(workspace, repo_id, section)
    if environment:
        if live_pin == environment:
            return None
        chosen = environment
        kind = "stable"
    elif live_pin:
        return None
    else:
        chosen = previous_pin
        kind = "carried"
        if not chosen:
            where = f"bom {_strip_v(from_version)}" if from_version else "previous BOM"
            raise GitConvoyError(
                f"placement requires {section} package {package!r}, but it is not pinned "
                f"and could not be resolved from {where} or a stable tag"
                + (f" (repo {repo_id!r})" if repo_id else "")
            )
    bom_data.setdefault(section, {})[package] = chosen
    return {
        "section": section,
        "package": package,
        "pin": chosen,
        "kind": kind,
        "action": "placement",
        **({"id": repo_id} if repo_id else {}),
    }


def _ensure_placement_pins(
    workspace: Path,
    root: Path,
    version: str,
    bom_data: dict,
    train: Train,
    from_version: str,
    catalog: list[PackageSlot] | None,
    placement,
) -> list[dict]:
    """Fill pins the train did not set.

    Train repos keep the version from the train sheet. Every other package uses
    the latest stable tag in the local clone. The previous BOM pin is kept only
    when that clone has no stable tag. Placement still requires hub and peer
    packages even when the previous BOM omitted them.
    """
    del version  # bom_data is the working master; split happens later.
    if placement.hub_python or placement.peers:
        required_python, required_npm = required_master_pins(placement, catalog)
    else:
        required_python, required_npm = set(), set()
    live_py = bom_data.get("python") if isinstance(bom_data.get("python"), dict) else {}
    live_npm = bom_data.get("npm") if isinstance(bom_data.get("npm"), dict) else {}
    python_names = set(required_python) | set(live_py)
    npm_names = set(required_npm) | set(live_npm)
    # A white-label pack with no registry is pinned by commit later. A version
    # here would send deploy to CodeArtifact for a package that was never published.
    uncovered = {
        name
        for slot in unregistered_wl_slots(catalog, load_registry_scopes(root))
        for name in (slot.python, slot.npm)
        if name
    }
    python_names -= uncovered
    npm_names -= uncovered
    previous = _master_at_version(root, from_version)
    train_owned = _train_owned_packages(workspace, train, bom_data, catalog)
    pinned: list[dict] = []

    prev_py = previous.get("python") if isinstance(previous.get("python"), dict) else {}
    prev_npm = previous.get("npm") if isinstance(previous.get("npm"), dict) else {}

    for dist in sorted(python_names):
        row = _off_train_placement_pin(
            workspace=workspace,
            bom_data=bom_data,
            section="python",
            package=dist,
            repo_id=_repo_id_for_python_dist(dist, catalog),
            previous_pin=str(prev_py.get(dist) or "").strip(),
            train_owned=train_owned,
            from_version=from_version,
        )
        if row:
            pinned.append(row)

    for name in sorted(npm_names):
        slot = slot_for_npm(catalog, name) if catalog else None
        repo_id = slot.id if slot else None
        if name == CONSOLE_NPM_HOST and not repo_id:
            repo_id = "console"
        row = _off_train_placement_pin(
            workspace=workspace,
            bom_data=bom_data,
            section="npm",
            package=name,
            repo_id=repo_id,
            previous_pin=str(prev_npm.get(name) or "").strip(),
            train_owned=train_owned,
            from_version=from_version,
        )
        if row:
            pinned.append(row)
    return pinned


def _stable_commit(repo: Path) -> tuple[str, str]:
    """Latest stable tag's commit, or the tip of main when no stable tag exists."""
    tag = gitutil.last_stable_tag(repo)
    if tag:
        sha = gitutil.rev_parse(repo, tag)
        if sha:
            branch = "main" if gitutil.rev_parse(repo, "main") or gitutil.rev_parse(repo, "origin/main") else "develop"
            return sha, branch
    for ref, branch in (("origin/main", "main"), ("main", "main"), ("HEAD", "main")):
        sha = gitutil.rev_parse(repo, ref)
        if sha:
            return sha, branch
    return "", ""


def _wl_checkout(workspace: Path, slot: PackageSlot) -> Path | None:
    for repo_id in (slot.id, slot.python):
        if not repo_id:
            continue
        found = _repo_path_by_id(workspace, repo_id)
        if found is not None:
            return found
    for name in (slot.id, slot.python):
        if not name:
            continue
        candidate = workspace / "dev" / name
        if candidate.is_dir() and gitutil.is_git_repo(candidate):
            return candidate
    return None


def _drop_package_pin(data: dict, section: str, package: str) -> bool:
    block = data.get(section)
    if not isinstance(block, dict) or package not in block:
        return False
    del block[package]
    if not block:
        data.pop(section, None)
    return True


def _pin_unregistered_wl(
    workspace: Path,
    root: Path,
    version: str,
    bom_data: dict,
    catalog: list[PackageSlot] | None,
    pinned: list[dict],
) -> list[dict]:
    """Pin a white-label pack by commit when no registry can serve it.

    ``packages`` names the pack. ``registries`` says which npm scopes exist.
    A scope that is not listed was never published, so a version pin would
    miss at deploy. The latest stable commit is written under ``repos`` and
    the version pins for that pack are removed.
    """
    slots = unregistered_wl_slots(catalog, load_registry_scopes(root))
    if not slots:
        return pinned
    plans: list[dict] = []
    for slot in slots:
        repo_path = _wl_checkout(workspace, slot)
        label = slot.npm or slot.python or slot.id
        if repo_path is None:
            raise GitConvoyError(
                f"{slot.id} ({label}) is listed in packages, and no registry serves it. "
                f"Clone the repo at dev/{slot.id} so bom can pin its latest stable commit."
            )
        sha, branch = _stable_commit(repo_path)
        if not sha:
            raise GitConvoyError(
                f"{slot.id} ({label}) has no commit to pin. "
                "Tag a stable release or commit on main."
            )
        slug = gitutil.github_slug(repo_path)
        if not slug:
            raise GitConvoyError(
                f"{slot.id} has no GitHub origin, so bom cannot name the repo to clone."
            )
        try:
            rel = repo_path.resolve().relative_to(workspace.resolve()).as_posix()
        except ValueError:
            rel = f"dev/{slot.id}"
        url = gitutil.origin_url(repo_path) or f"https://github.com/{slug}.git"
        entry = {
            "url": url,
            "commit": sha,
            "branch": branch,
            "path": rel,
        }
        # One file is checked out by both jobs. Split files set this per pipeline.
        if not _uses_three_bom_layout(root):
            entry["pipelines"] = ["backend", "console"]
        plans.append({"slot": slot, "slug": slug, "entry": entry})

    path = _bom_file(root, version)
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    drop: set[tuple[str, str]] = set()
    rows: list[dict] = []
    for plan in plans:
        slot = plan["slot"]
        for section, package in (("python", slot.python), ("npm", slot.npm)):
            if not package:
                continue
            drop.add((section, package))
            removed = _drop_package_pin(data, section, package)
            _drop_package_pin(bom_data, section, package)
            if removed:
                rows.append(
                    {
                        "id": slot.id,
                        "section": section,
                        "package": package,
                        "pin": "(removed)",
                        "action": "cleared",
                        "kind": "git",
                    }
                )
        entry = plan["entry"]
        data.setdefault("repos", {})[plan["slug"]] = entry
        bom_data.setdefault("repos", {})[plan["slug"]] = dict(entry)
        rows.append(
            {
                "id": slot.id,
                "section": "repos",
                "package": plan["slug"],
                "pin": entry["commit"],
                "kind": "git",
                "action": "placement",
            }
        )
    write_bom_file(root, path, data)
    kept = [
        row
        for row in pinned
        if (row.get("section"), row.get("package")) not in drop
        or row.get("action") in {"pruned", "cleared"}
    ]
    kept.extend(rows)
    return kept


def _unregistered_wl_repo_keys(
    repos: dict,
    catalog: list[PackageSlot],
    scopes: set[str],
) -> set[str]:
    """Repo keys for white-label packs that are pinned by commit, not by version."""
    slots = unregistered_wl_slots(catalog, scopes)
    if not slots:
        return set()
    keys: set[str] = set()
    for key in repos:
        short = str(key).split("/")[-1]
        for slot in slots:
            if key == slot.repo or short == slot.id or short == slot.python:
                keys.add(str(key))
    return keys


def _prune_bom_to_catalog(
    root: Path,
    version: str,
    bom_data: dict,
    catalog: list[PackageSlot],
) -> list[dict]:
    allowed = catalog_allowlist(catalog)
    path = _bom_file(root, version)
    data = json.loads(path.read_text())
    dropped: list[dict] = []
    section_keys = (("python", "python"), ("npm", "npm"), ("repos", "repos"))
    keep_repos = _unregistered_wl_repo_keys(
        data.get("repos") if isinstance(data.get("repos"), dict) else {},
        catalog,
        load_registry_scopes(root),
    )
    for section, allow_key in section_keys:
        block = data.get(section)
        if not isinstance(block, dict):
            continue
        for name in list(block):
            if name in allowed[allow_key] or (section == "repos" and name in keep_repos):
                continue
            del block[name]
            live = bom_data.get(section)
            if isinstance(live, dict):
                live.pop(name, None)
                if not live:
                    bom_data.pop(section, None)
            dropped.append(
                {
                    "section": section,
                    "package": name,
                    "pin": "(removed)",
                    "action": "pruned",
                }
            )
        if not block:
            data.pop(section, None)
    if dropped:
        write_bom_file(root, path, data)
    return dropped


def _restore_adopt_pins(
    root: Path,
    version: str,
    bom_data: dict,
    pinned: list[dict],
) -> None:
    """Re-apply registry pins from this adopt if prune or a later write dropped them."""
    path = _bom_file(root, version)
    data = json.loads(path.read_text())
    changed = False
    for row in pinned:
        if row.get("action") in {"pruned", "cleared"}:
            continue
        section = row.get("section")
        package = row.get("package")
        value = row.get("pin")
        if section not in {"python", "npm"} or not package or not value or value == "(removed)":
            continue
        block = data.setdefault(section, {})
        if not isinstance(block, dict):
            continue
        if block.get(package) == value:
            continue
        block[package] = value
        bom_data.setdefault(section, {})[package] = value
        changed = True
    if changed:
        write_bom_file(root, path, data)


def _clear_package_pins(
    root: Path,
    version: str,
    repo: TrainRepo,
    workspace: Path,
    bom_data: dict,
    catalog: list[PackageSlot] | None = None,
) -> list[dict]:
    path = _bom_file(root, version)
    data = json.loads(path.read_text())
    cleared: list[dict] = []
    allowed = catalog_allowlist(catalog) if catalog is not None else None
    for section, package in _candidate_package_pins(repo, workspace):
        if allowed and package in allowed.get(section, ()):
            continue
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
        write_bom_file(root, path, data)
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

    def _ids(*statuses: str) -> list[str]:
        return [
            row["id"]
            for row in result.get("repos") or []
            if row.get("status") in statuses
        ]

    failed = [
        row["id"]
        for row in result.get("repos") or []
        if row.get("status") not in {"success", "skip", "pending", "missing"}
    ]
    summary = {
        "ran": True,
        "verified_count": result.get("verified_count", 0),
        "skipped_count": result.get("skipped_count", 0),
        "pending_count": result.get("pending_count", 0),
        "failed_count": result.get("failed_count", 0),
        "repo_count": result.get("repo_count", 0),
        "succeeded": _ids("success"),
        "skipped": _ids("skip"),
        "pending": _ids("pending", "missing"),
        "failed": failed,
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
        write_bom_file(root, path, data)
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
    write_bom_file(root, path, data)
    return pinned


def _written_bom_summaries(root: Path, version: str) -> list[dict]:
    """Relative BOM files on disk for this version, with pin maps."""
    name = f"{_v(version)}.json"
    candidates: list[tuple[str, Path, str | None]] = [
        ("hub", root / "bom" / name, None),
    ]
    console = root / "console_bom" / name
    if console.is_file():
        candidates.append(("console", console, None))
    peers_root = root / "peers_bom"
    if peers_root.is_dir():
        for peer_dir in sorted(
            path for path in peers_root.iterdir() if path.is_dir()
        ):
            path = peer_dir / name
            if path.is_file():
                candidates.append(("peer", path, peer_dir.name))
    rows: list[dict] = []
    for kind, path, peer in candidates:
        if not path.is_file():
            continue
        rows.append(_summarize_bom_path(root, path, kind=kind, peer=peer))
    return rows


def _summarize_bom_path(
    root: Path, path: Path, *, kind: str, peer: str | None
) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    python = data.get("python") if isinstance(data.get("python"), dict) else {}
    npm = data.get("npm") if isinstance(data.get("npm"), dict) else {}
    repos_in = data.get("repos") if isinstance(data.get("repos"), dict) else {}
    repos: dict[str, str] = {}
    for key, value in repos_in.items():
        if isinstance(value, dict):
            commit = str(value.get("commit") or "").strip()
            repos[key] = commit[:12] if commit else ""
        elif value is not None:
            repos[key] = str(value)
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = str(path)
    row = {
        "kind": kind,
        "path": rel,
        "python": dict(python),
        "npm": dict(npm),
        "repos": repos,
    }
    if peer:
        row["peer"] = peer
    return row


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
