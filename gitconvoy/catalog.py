"""BOM membership catalog from deploy_targets.yml ``packages:``.

Absent ``packages:`` means legacy copy-forward (no prune).
When present, adopt keeps only listed python / npm / repo pins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PackageSlot:
    id: str
    python: str = ""
    npm: str = ""
    repo: str = ""


_SLOT_LINE = re.compile(r"^(\s*)([^:#\s][^:]*)\s*:\s*(?:#.*)?$")
_FIELD_LINE = re.compile(
    r"^(\s*)(python|npm|repo)\s*:\s*(?:(?P<q>['\"])(?P<quoted>.*)(?P=q)|(?P<bare>\S+))\s*(?:#.*)?$"
)


def tenant_config_path(root: Path) -> Path:
    """Tenant desired state. ``renglo.yaml`` when the repo has moved off deploy_targets.yml."""
    renglo = root / "renglo.yaml"
    if renglo.is_file():
        return renglo
    return root / "deploy_targets.yml"


def load_package_catalog(root: Path) -> list[PackageSlot] | None:
    path = tenant_config_path(root)
    if not path.is_file():
        return None
    return parse_package_catalog(path.read_text(encoding="utf-8"))


def parse_package_catalog(text: str) -> list[PackageSlot] | None:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^packages:\s*(?:#.*)?$", line):
            start = index + 1
            break
        if re.match(r"^packages:\s*\{\s*\}\s*(?:#.*)?$", line):
            return []
    if start is None:
        return None

    slots: list[PackageSlot] = []
    current_id = ""
    fields: dict[str, str] = {}
    slot_indent: int | None = None

    def flush() -> None:
        nonlocal current_id, fields
        if current_id:
            slots.append(
                PackageSlot(
                    id=current_id,
                    python=fields.get("python", ""),
                    npm=fields.get("npm", ""),
                    repo=fields.get("repo", ""),
                )
            )
        current_id = ""
        fields = {}

    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            break
        field = _FIELD_LINE.match(line)
        if field and current_id:
            value = field.group("quoted")
            if value is None:
                value = field.group("bare") or ""
            fields[field.group(2)] = value
            continue
        slot = _SLOT_LINE.match(line)
        if not slot:
            continue
        this_indent = len(slot.group(1))
        if slot_indent is None:
            slot_indent = this_indent
        if this_indent != slot_indent:
            continue
        flush()
        current_id = slot.group(2).strip().strip("'\"")
    flush()
    return slots


_WL_NPM = re.compile(r"^@[^/]+/wl$")
_SCOPE_ITEM = re.compile(
    r"^\s*-\s*(?:(?P<q>['\"])(?P<quoted>@[^'\"]+)(?P=q)|(?P<bare>@\S+))\s*(?:#.*)?$"
)


def parse_registry_scopes(text: str) -> set[str]:
    """npm scopes listed under top-level ``registries:``.

    A scope is ``@owner``. Packages under a scope that no row lists are not
    in any registry this environment can install from.
    """
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^registries:\s*\[\s*\]\s*(?:#.*)?$", line):
            return set()
        if re.match(r"^registries:\s*(?:#.*)?$", line):
            start = index + 1
            break
    if start is None:
        return set()
    scopes: set[str] = set()
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # The next top-level key ends the block. List items sit at column 0
        # (`- domain:`) and stay inside it.
        if re.match(r"^[A-Za-z_][^:]*:", line):
            break
        match = _SCOPE_ITEM.match(line)
        if not match:
            continue
        value = (match.group("quoted") or match.group("bare") or "").strip()
        if value.startswith("@"):
            scopes.add(value)
    return scopes


def load_registry_scopes(root: Path) -> set[str]:
    path = tenant_config_path(root)
    if not path.is_file():
        return set()
    return parse_registry_scopes(path.read_text(encoding="utf-8"))


def wl_slots(catalog: list[PackageSlot] | None) -> list[PackageSlot]:
    """Package slots that are a white-label pack (``*-wl`` or ``@scope/wl``)."""
    found: list[PackageSlot] = []
    if not catalog:
        return found
    for slot in catalog:
        python_name = slot.python or ""
        npm_name = slot.npm or ""
        if (
            slot.id == "wl"
            or slot.id.endswith("-wl")
            or python_name == "wl"
            or python_name.endswith("-wl")
            or bool(_WL_NPM.match(npm_name))
        ):
            found.append(slot)
    return found


def npm_scope(name: str) -> str:
    if name.startswith("@") and "/" in name:
        return "@" + name[1:].split("/", 1)[0]
    return ""


def slot_served_by_registry(slot: PackageSlot, scopes: set[str]) -> bool:
    """True when some ``registries`` row can hold this slot's package.

    An npm pack is served only when its scope is listed. A python-only pack
    has no scope; any configured registry can hold the wheel.
    """
    scope = npm_scope(slot.npm)
    if scope:
        return scope in scopes
    return bool(scopes)


def unregistered_wl_slots(
    catalog: list[PackageSlot] | None,
    scopes: set[str],
) -> list[PackageSlot]:
    return [slot for slot in wl_slots(catalog) if not slot_served_by_registry(slot, scopes)]


def catalog_allowlist(catalog: list[PackageSlot]) -> dict[str, set[str]]:
    allowed: dict[str, set[str]] = {"python": set(), "npm": set(), "repos": set()}
    for slot in catalog:
        if slot.python:
            allowed["python"].add(slot.python)
        if slot.npm:
            allowed["npm"].add(slot.npm)
        if slot.repo:
            allowed["repos"].add(slot.repo)
    return allowed


def slot_for_python(catalog: list[PackageSlot], dist: str) -> PackageSlot | None:
    for slot in catalog:
        if slot.python == dist:
            return slot
    return None


def slot_for_npm(catalog: list[PackageSlot], name: str) -> PackageSlot | None:
    for slot in catalog:
        if slot.npm == name:
            return slot
    return None


def slot_for_repo(
    catalog: list[PackageSlot],
    repo_id: str,
    *,
    npm_name: str = "",
    python_names: list[str] | None = None,
) -> PackageSlot | None:
    for slot in catalog:
        if slot.id == repo_id:
            return slot
    if npm_name:
        for slot in catalog:
            if slot.npm == npm_name:
                return slot
    names = set(python_names or [])
    if names:
        for slot in catalog:
            if slot.python and slot.python in names:
                return slot
    return None
