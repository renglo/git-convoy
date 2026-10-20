"""Compare a BOM platform pin with the platform each package declares.

A declaration of ``0.1.4`` runs on platforms ``>=0.1.4`` and ``<0.2.0``.
The check warns and does not refuse to write a BOM.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from gitconvoy import gitutil, versions
from gitconvoy.adopt import (
    _bom_file,
    _pep_and_npm,
    _resolve_take_target,
    _uses_three_bom_layout,
    find_bom_repo,
)
from gitconvoy.bom_layout import (
    _normalize_platform,
    load_platform,
    load_staging_platform,
    merge_union_bom,
    released_platform,
)
from gitconvoy.catalog import catalog_allowlist, load_package_catalog, slot_for_repo
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, Train, TrainRepo

_TOOL_RENGLO = re.compile(r"(?ms)^\[tool\.renglo\][^\n]*\n(.*?)(?=^\[|\Z)")
_PLATFORM_ASSIGN = re.compile(r"""^platform\s*=\s*(['"])([^'"]+)\1\s*$""")


# Statuses that still run on this platform. Everything else is a warning.
_PASSING = frozenset({"match", "compatible"})

# Printed in this order when several statuses appear in one check.
_STATUS_ORDER = (
    "match",
    "compatible",
    "ahead",
    "stale",
    "missing",
    "unread",
    "invalid",
    "unpinned",
)


def compatibility(required: str, current: str) -> str:
    """One-word status of a package declaration against the BOM platform.

    ``match``       declared version equals the platform.
    ``compatible``  same minor, platform is a newer patch (backward compatible).
    ``ahead``       package requires a newer platform than this BOM.
    ``stale``       platform is on a newer minor.

    An rc suffix is ignored. Both sides are ``x.y.z``.
    """
    req = _triple(required)
    cur = _triple(current)
    if cur < req:
        return "ahead"
    if (cur[0], cur[1]) != (req[0], req[1]):
        return "stale"
    if cur == req:
        return "match"
    return "compatible"


def check(
    workspace: Path,
    state: State,
    *,
    bom: str | None = None,
    train: str | None = None,
    from_version: str | None = None,
) -> dict[str, Any]:
    """Report warnings for the BOM ``take`` would write. Writes nothing."""
    train_obj = state.require_train(train)
    _require_versions(train_obj)
    root = find_bom_repo(workspace, bom)
    return report_for_take(
        workspace,
        train_obj,
        root,
        from_version=from_version,
    )


def report_for_take(
    workspace: Path,
    train: Train,
    root: Path,
    *,
    from_version: str | None = None,
) -> dict[str, Any]:
    src, _dest, _refresh = _resolve_take_target(
        root,
        train,
        from_version=from_version,
        to_version=None,
    )
    source = _load_source_bom(root, src)
    platform = (
        released_platform(train.repos)
        or load_staging_platform(root)
        or load_platform(root)
    )
    rows = _comparisons(workspace, train, source, platform, root)
    warnings = [row for row in rows if row["status"] not in _PASSING]
    return {
        "ok": True,
        "train": train.name,
        "platform": platform,
        "packages": rows,
        "platform_warnings": warnings,
        "warning_count": len(warnings),
    }


def format_check_text(report: dict[str, Any]) -> str:
    platform = report.get("platform") or "(none)"
    train = report.get("train") or "?"
    rows = report.get("packages") or []
    lines = [f"platform check (train {train}, platform {platform})"]
    if not rows:
        lines.append("  nothing to compare")
        return "\n".join(lines)
    shown = [_shown_status(row) for row in rows]
    width = max(len(name) for name in shown)
    aspirational = False
    for row, status in zip(rows, shown):
        if row.get("aspirational"):
            aspirational = True
        requires = row.get("requires") or "-"
        pin = row.get("pin") or "-"
        ecosystem = row.get("ecosystem") or "-"
        package = row.get("package") or "-"
        lines.append(
            f"  {status:<{width}}  {ecosystem:<7} {package} {pin}  requires {requires}"
        )
        base = str(row.get("status") or "")
        if base not in _PASSING and row.get("message"):
            lines.append(f"    {row['message']}")
    counts: dict[str, int] = {}
    for name in shown:
        counts[name] = counts.get(name, 0) + 1
    ordered = _order_shown(counts)
    lines.append(", ".join(f"{counts[name]} {name}" for name in ordered))
    if aspirational:
        lines.append("* release candidate; status is provisional until the pin is stable")
    return "\n".join(lines)


def _shown_status(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "")
    if row.get("aspirational"):
        return status + "*"
    return status


def _order_shown(counts: dict[str, int]) -> list[str]:
    ordered: list[str] = []
    for name in _STATUS_ORDER:
        if name in counts:
            ordered.append(name)
        starred = name + "*"
        if starred in counts:
            ordered.append(starred)
    ordered.extend(name for name in counts if name not in ordered)
    return ordered


def format_warning_lines(warnings: list[dict[str, Any]]) -> list[str]:
    if not warnings:
        return []
    lines = ["platform check:"]
    for row in warnings:
        lines.append(f"  {row['message']}")
    return lines


def declared_platform_pyproject(text: str) -> str:
    match = _TOOL_RENGLO.search(text)
    if not match:
        return ""
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        found = _PLATFORM_ASSIGN.match(stripped)
        if found:
            return _normalize_platform(found.group(2))
    return ""


def declared_platform_package_json(text: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ""
    renglo = data.get("renglo") if isinstance(data, dict) else None
    if not isinstance(renglo, dict):
        return ""
    value = renglo.get("platform")
    if not isinstance(value, str):
        return ""
    return _normalize_platform(value.strip())


def _require_versions(train: Train) -> None:
    if not train.repos:
        raise GitConvoyError(f"train {train.name} has no repos")
    missing = [repo.id for repo in train.repos if not repo.to]
    if missing:
        raise GitConvoyError(
            f"train {train.name} has no versions to pin for: {', '.join(missing)}; "
            "run train tag-rc or train publish first"
        )


def _load_source_bom(root: Path, version: str) -> dict[str, Any]:
    if _uses_three_bom_layout(root):
        data = merge_union_bom(root, version)
        return data if isinstance(data, dict) else {}
    path = _bom_file(root, version)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _comparisons(
    workspace: Path,
    train: Train,
    source: dict[str, Any],
    platform: str,
    root: Path,
) -> list[dict[str, Any]]:
    if platform:
        try:
            _triple(platform)
        except GitConvoyError:
            return [
                _row(
                    package="",
                    ecosystem="",
                    pin="",
                    requires="",
                    platform=platform,
                    repo="",
                    status="invalid",
                    message=f"platform pin {platform} is not an x.y.z version.",
                )
            ]
    catalog = load_package_catalog(root)
    allowed = catalog_allowlist(catalog) if catalog is not None else None
    subjects: list[dict[str, Any]] = []
    owned: set[tuple[str, str]] = set()

    for repo in train.repos:
        if _is_platform_repo(repo):
            continue
        repo_path = workspace / repo.path
        python_name = versions.read_python_package_name(repo_path) or ""
        npm_name = versions.read_npm_package_name(repo_path) or ""
        if catalog is not None:
            slot = slot_for_repo(
                catalog,
                repo.id,
                npm_name=npm_name,
                python_names=[python_name] if python_name else [],
            )
            if slot is None:
                continue
            pairs = []
            if slot.python:
                pairs.append(("python", slot.python))
            if slot.npm:
                pairs.append(("npm", slot.npm))
        else:
            pairs = []
            if python_name:
                pairs.append(("python", python_name))
            if npm_name:
                pairs.append(("npm", npm_name))
        pep, npm = _pep_and_npm(repo.to or "")
        for section, package in pairs:
            pin = npm if section == "npm" else pep
            owned.add((section, package))
            subjects.append(
                {
                    "section": section,
                    "package": package,
                    "pin": pin,
                    "repo": repo,
                    "path": repo_path,
                }
            )

    for section in ("python", "npm"):
        pins = source.get(section)
        if not isinstance(pins, dict):
            continue
        for package, pin in pins.items():
            key = (section, str(package))
            if key in owned:
                continue
            if allowed is not None and str(package) not in allowed[section]:
                continue
            located = _locate_package(workspace, section, str(package))
            subjects.append(
                {
                    "section": section,
                    "package": str(package),
                    "pin": str(pin),
                    "repo": None,
                    "path": located,
                }
            )

    rows: list[dict[str, Any]] = []
    for subject in subjects:
        row = _subject_row(subject, platform)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda row: (row["package"], row["ecosystem"], row["status"]))
    return rows


def _subject_row(subject: dict[str, Any], platform: str) -> dict[str, Any] | None:
    section = subject["section"]
    package = subject["package"]
    pin = subject["pin"]
    repo: TrainRepo | None = subject["repo"]
    path: Path | None = subject["path"]
    ref = _pin_ref(repo, pin)
    if path is None:
        if not platform:
            return None
        return _row(
            package=package,
            ecosystem=section,
            pin=pin,
            requires="",
            platform=platform,
            repo=repo.path if repo else "",
            status="unread",
            message=f"{package} {pin}: could not read a platform declaration at {ref}.",
        )
    declared, read_status = _read_declaration(path, section, pin, ref)
    if read_status == "unread":
        if not platform:
            return None
        return _row(
            package=package,
            ecosystem=section,
            pin=pin,
            requires="",
            platform=platform,
            repo=str(path),
            status="unread",
            message=f"{package} {pin}: could not read a platform declaration at {ref}.",
        )
    if read_status == "missing":
        if not platform:
            return None
        return _row(
            package=package,
            ecosystem=section,
            pin=pin,
            requires="",
            platform=platform,
            repo=str(path),
            status="missing",
            message=f"{package} {pin} has no platform declaration.",
        )
    if not declared:
        return None
    try:
        _triple(declared)
    except GitConvoyError:
        return _row(
            package=package,
            ecosystem=section,
            pin=pin,
            requires=declared,
            platform=platform,
            repo=str(path),
            status="invalid",
            message=(
                f"{package} {pin} declares platform {declared}, "
                "which is not an x.y.z version."
            ),
        )
    if not platform:
        return _row(
            package=package,
            ecosystem=section,
            pin=pin,
            requires=declared,
            platform="",
            repo=str(path),
            status="unpinned",
            message=(
                f"{package} {pin} requires platform {declared}; "
                "renglo.yaml has no platform pin."
            ),
        )
    status = compatibility(declared, platform)
    compared = (
        f"{package} {pin} requires platform {declared}; "
        f"this BOM's platform is {platform}."
    )
    if status == "ahead":
        message = (
            f"{package} {pin} is ahead of platform {platform}; it requires {declared}. "
            f"Upgrade the platform to {declared} or later on the {_line(declared)} line."
        )
    elif status == "stale":
        message = (
            f"{compared} "
            f"Upgrade {package} to a release that declares the {_line(platform)} line."
        )
    else:
        message = compared
    return _row(
        package=package,
        ecosystem=section,
        pin=pin,
        requires=declared,
        platform=platform,
        repo=str(path),
        status=status,
        message=message,
    )


def _row(
    *,
    package: str,
    ecosystem: str,
    pin: str,
    requires: str,
    platform: str,
    repo: str,
    status: str,
    message: str,
) -> dict[str, Any]:
    return {
        "package": package,
        "ecosystem": ecosystem,
        "pin": pin,
        "requires": requires,
        "platform": platform,
        "repo": repo,
        "status": status,
        "aspirational": _is_rc(pin),
        "message": message,
    }


def _is_rc(version: str) -> bool:
    try:
        return versions.parse(version)[3] is not None
    except GitConvoyError:
        return False


def _read_declaration(
    repo: Path,
    ecosystem: str,
    version: str,
    ref: str,
) -> tuple[str, str]:
    """Return ``(declared, status)`` where status is declared, missing, or unread."""
    rels = _rels(ecosystem)
    for rel in rels:
        text = _text_at_ref(repo, rel, ref)
        if text is None:
            continue
        declared = _declared_in(text, ecosystem)
        return declared, "declared" if declared else "missing"
    text = _worktree_text(repo, ecosystem, version)
    if text is None:
        return "", "unread"
    declared = _declared_in(text, ecosystem)
    return declared, "declared" if declared else "missing"


def _rels(ecosystem: str) -> tuple[str, ...]:
    if ecosystem == "npm":
        return ("ui/package.json", "package.json")
    return versions.PYTHON_PYPROJECT_RELS


def _declared_in(text: str, ecosystem: str) -> str:
    if ecosystem == "npm":
        return declared_platform_package_json(text)
    return declared_platform_pyproject(text)


def _text_at_ref(repo: Path, rel: str, ref: str) -> str | None:
    if not gitutil.is_git_repo(repo):
        return None
    result = gitutil.run(repo, "show", f"{ref}:{rel}", check=False)
    if result.returncode != 0:
        return None
    text = result.stdout or ""
    if not text.strip():
        return None
    return text


def _worktree_text(repo: Path, ecosystem: str, version: str) -> str | None:
    info = versions.read_version(repo)
    key = "npm" if ecosystem == "npm" else "python"
    found = info.get(key) or ""
    if not found or not _same_version(found, version):
        return None
    file_key = "npm_file" if ecosystem == "npm" else "python_file"
    rel = info.get(file_key) or ""
    if not rel:
        return None
    path = repo / rel
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _locate_package(workspace: Path, ecosystem: str, package: str) -> Path | None:
    roots: list[Path] = []
    for folder in (workspace / "dev", workspace / "extensions"):
        if folder.is_dir():
            roots.extend(path for path in sorted(folder.iterdir()) if path.is_dir())
    console = workspace / "console"
    if console.is_dir():
        roots.append(console)
    for path in roots:
        if ecosystem == "python" and versions.read_python_package_name(path) == package:
            return path
        if ecosystem == "npm" and versions.read_npm_package_name(path) == package:
            return path
    return None


def _pin_ref(repo: TrainRepo | None, version: str) -> str:
    try:
        rc = versions.parse(version)[3]
    except GitConvoyError:
        return version
    if repo is not None:
        if rc is not None and repo.rc_tag:
            return repo.rc_tag
        if rc is None and repo.stable_tag:
            return repo.stable_tag
        if repo.rc_tag:
            return repo.rc_tag
        if repo.stable_tag:
            return repo.stable_tag
    return f"v{_tag_body(version)}"


def _tag_body(version: str) -> str:
    major, minor, patch, rc = versions.parse(version)
    if rc is None:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{patch}-rc.{rc}"


def _is_platform_repo(repo: TrainRepo) -> bool:
    name = Path(repo.path).name if repo.path else ""
    return repo.id == "renglo-ops" or name == "renglo-ops"


def _triple(version: str) -> tuple[int, int, int]:
    major, minor, patch, _rc = versions.parse(versions.drop_rc(version)[0])
    return major, minor, patch


def _line(version: str) -> str:
    major, minor, _patch = _triple(version)
    return f"{major}.{minor}"


def _same_version(left: str, right: str) -> bool:
    try:
        return versions.parse(left) == versions.parse(right)
    except GitConvoyError:
        return left.lstrip("v") == right.lstrip("v")
