from __future__ import annotations

import json
import re
from pathlib import Path

from gitconvoy.errors import GitConvoyError

_VERSION = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)(?:(?:rc|\-rc\.)(\d+))?$",
    re.IGNORECASE,
)


def parse(version: str) -> tuple[int, int, int, int | None]:
    match = _VERSION.match(version.strip())
    if not match:
        raise GitConvoyError(f"unsupported version string: {version}")
    major, minor, patch, rc = match.groups()
    return int(major), int(minor), int(patch), int(rc) if rc else None


def format_pep440(major: int, minor: int, patch: int, rc: int | None = None) -> str:
    base = f"{major}.{minor}.{patch}"
    return f"{base}rc{rc}" if rc else base


def format_npm(major: int, minor: int, patch: int, rc: int | None = None) -> str:
    base = f"{major}.{minor}.{patch}"
    return f"{base}-rc.{rc}" if rc else base


def bump(version: str, part: str) -> str:
    major, minor, patch, _rc = parse(version)
    if part == "major":
        return format_pep440(major + 1, 0, 0)
    if part == "minor":
        return format_pep440(major, minor + 1, 0)
    if part == "patch":
        return format_pep440(major, minor, patch + 1)
    raise GitConvoyError(f"unknown bump: {part}")


def with_rc(version: str, n: int = 1) -> tuple[str, str]:
    major, minor, patch, rc = parse(version)
    if rc is not None:
        n = rc
    return format_pep440(major, minor, patch, n), format_npm(major, minor, patch, n)


def next_rc(version: str) -> tuple[str, str]:
    major, minor, patch, rc = parse(version)
    n = 1 if rc is None else rc + 1
    return format_pep440(major, minor, patch, n), format_npm(major, minor, patch, n)


def drop_rc(version: str) -> tuple[str, str]:
    major, minor, patch, _rc = parse(version)
    return format_pep440(major, minor, patch), format_npm(major, minor, patch)


def _replace_quoted_version(text: str, new: str, key_pattern: str) -> tuple[str, bool]:
    pattern = re.compile(key_pattern)
    match = pattern.search(text)
    if not match:
        return text, False
    start, end = match.span(1)
    return text[:start] + new + text[end:], True


def read_version(repo: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    pyproject = repo / "pyproject.toml"
    if not pyproject.exists():
        pyproject = repo / "package" / "pyproject.toml"
    if pyproject.exists():
        match = re.search(
            r'(?m)^version\s*=\s*["\']([^"\']+)["\']', pyproject.read_text()
        )
        if match:
            found["python"] = match.group(1)
            found["python_file"] = str(pyproject.relative_to(repo))
    setup = repo / "setup.py"
    if not setup.exists():
        setup = repo / "package" / "setup.py"
    if "python" not in found and setup.exists():
        match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', setup.read_text())
        if match:
            found["python"] = match.group(1)
            found["python_file"] = str(setup.relative_to(repo))
    for candidate in (repo / "ui" / "package.json", repo / "package.json"):
        if candidate.exists():
            data = json.loads(candidate.read_text())
            if isinstance(data.get("version"), str):
                found["npm"] = data["version"]
                found["npm_file"] = str(candidate.relative_to(repo))
            break
    return found


def read_npm_package_name(repo: Path) -> str | None:
    """Name from ui/package.json, else root package.json. None if missing."""
    for candidate in (repo / "ui" / "package.json", repo / "package.json"):
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        name = data.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None
    return None


def read_python_package_name(repo: Path) -> str | None:
    """[project] name from pyproject.toml (root or package/). None if missing."""
    for candidate in (repo / "pyproject.toml", repo / "package" / "pyproject.toml"):
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text()
        except OSError:
            return None
        header = re.search(r"(?m)^\[project\]\s*$", text)
        if not header:
            return None
        rest = text[header.end() :]
        next_section = re.search(r"(?m)^\[", rest)
        section = rest[: next_section.start()] if next_section else rest
        match = re.search(r'(?m)^name\s*=\s*["\']([^"\']+)["\']', section)
        if match:
            name = match.group(1).strip()
            return name or None
        return None
    return None


def write_version(repo: Path, pep: str, npm: str) -> list[str]:
    changed: list[str] = []
    info = read_version(repo)
    if "python_file" in info:
        path = repo / info["python_file"]
        text = path.read_text()
        if path.name == "pyproject.toml":
            new, ok = _replace_quoted_version(
                text, pep, r'(?m)^version\s*=\s*["\']([^"\']+)["\']'
            )
        else:
            new, ok = _replace_quoted_version(
                text, pep, r'version\s*=\s*["\']([^"\']+)["\']'
            )
        if ok:
            path.write_text(new)
            changed.append(info["python_file"])
    if "npm_file" in info:
        path = repo / info["npm_file"]
        text = path.read_text()
        new, ok = _replace_quoted_version(
            text, npm, r'"version"\s*:\s*"([^"]+)"'
        )
        if ok:
            path.write_text(new)
            changed.append(info["npm_file"])
    if not changed:
        raise GitConvoyError(f"no version file found in {repo}")
    return changed
