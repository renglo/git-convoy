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


def cmp_stable(left: str, right: str) -> int:
    """Compare PEP/npm versions by major.minor.patch only (rc ignored)."""
    left_t = parse(drop_rc(left)[0])[:3]
    right_t = parse(drop_rc(right)[0])[:3]
    if left_t > right_t:
        return 1
    if left_t < right_t:
        return -1
    return 0


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


# First match is canonical (tag, pin, platform). lib/ is the CI wheel when a
# repo ships a CLI and a library as siblings; package/ is the extension layout.
PYTHON_PYPROJECT_RELS = (
    "lib/pyproject.toml",
    "package/pyproject.toml",
    "cli/pyproject.toml",
    "pyproject.toml",
)

_SETUP_RELS = ("package/setup.py", "setup.py")
_PYPROJECT_VERSION = re.compile(r'(?m)^version\s*=\s*["\']([^"\']+)["\']')


def _quoted_pyproject_version(text: str) -> str | None:
    match = _PYPROJECT_VERSION.search(text)
    return match.group(1) if match else None


def python_pyproject_rels(repo: Path) -> list[str]:
    """Relative pyproject.toml files that declare a version, canonical first."""
    found: list[str] = []
    for rel in PYTHON_PYPROJECT_RELS:
        path = repo / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        if _quoted_pyproject_version(text):
            found.append(rel)
    return found


def read_version_at_ref(repo: Path, ref: str) -> dict[str, str]:
    """Read package versions from ``ref`` without checking out (for stable carry-forward)."""
    from gitconvoy import gitutil

    found: dict[str, str] = {}
    for rel in PYTHON_PYPROJECT_RELS:
        text = gitutil.run(repo, "show", f"{ref}:{rel}", check=False).stdout or ""
        if not text.strip():
            continue
        version = _quoted_pyproject_version(text)
        if version:
            found["python"] = version
            break
    for rel in ("ui/package.json", "package.json"):
        text = gitutil.run(repo, "show", f"{ref}:{rel}", check=False).stdout or ""
        if not text.strip():
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data.get("version"), str):
            found["npm"] = data["version"]
            break
    return found


def read_version(repo: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    rels = python_pyproject_rels(repo)
    if rels:
        found["python"] = _quoted_pyproject_version((repo / rels[0]).read_text()) or ""
        found["python_file"] = rels[0]
    if "python" not in found:
        for rel in _SETUP_RELS:
            setup = repo / rel
            if not setup.exists():
                continue
            match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', setup.read_text())
            if match:
                found["python"] = match.group(1)
                found["python_file"] = rel
                break
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
    """[project] name from the canonical pyproject.toml. None if missing."""
    for rel in PYTHON_PYPROJECT_RELS:
        candidate = repo / rel
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text()
        except OSError:
            return None
        header = re.search(r"(?m)^\[project\]\s*$", text)
        if not header:
            continue
        rest = text[header.end() :]
        next_section = re.search(r"(?m)^\[", rest)
        section = rest[: next_section.start()] if next_section else rest
        match = re.search(r'(?m)^name\s*=\s*["\']([^"\']+)["\']', section)
        if match:
            name = match.group(1).strip()
            return name or None
        return None
    return None


def write_version(
    repo: Path,
    pep: str,
    npm: str,
    *,
    platform: str | None = None,
) -> list[str]:
    """Write package versions.

    ``platform`` is the stable renglo-ops version this package version targets.
    An rc suffix is dropped, so a train on ``0.1.5rc1`` declares ``0.1.5``.
    The previous file stays in git.
    """
    declared = _stable_platform(platform) if platform else ""
    changed: list[str] = []
    info = read_version(repo)
    rels = python_pyproject_rels(repo)
    if not rels and "python_file" in info:
        rels = [info["python_file"]]
    for rel in rels:
        path = repo / rel
        text = path.read_text()
        if path.name == "pyproject.toml":
            new, ok = _replace_quoted_version(
                text, pep, r'(?m)^version\s*=\s*["\']([^"\']+)["\']'
            )
        else:
            new, ok = _replace_quoted_version(
                text, pep, r'version\s*=\s*["\']([^"\']+)["\']'
            )
        if not ok:
            continue
        if declared and path.name == "pyproject.toml":
            new = set_pyproject_platform(new, declared)
        if new != text:
            path.write_text(new)
        changed.append(rel)
    if "npm_file" in info:
        path = repo / info["npm_file"]
        text = path.read_text()
        new, ok = _replace_quoted_version(
            text, npm, r'"version"\s*:\s*"([^"]+)"'
        )
        if ok:
            if declared:
                new = set_package_json_platform(new, declared)
            path.write_text(new)
            changed.append(info["npm_file"])
    if not changed:
        raise GitConvoyError(f"no version file found in {repo}")
    return changed


def set_pyproject_platform(text: str, platform: str) -> str:
    """Set ``[tool.renglo] platform`` without touching the package version."""
    section = re.search(r"(?ms)^\[tool\.renglo\][^\n]*\n(.*?)(?=^\[|\Z)", text)
    assignment = f'platform = "{platform}"'
    if section:
        body = section.group(1)
        new_body, count = re.subn(
            r"""(?m)^platform\s*=\s*(['"])[^'"]+\1""",
            assignment,
            body,
            count=1,
        )
        if count:
            return text[: section.start(1)] + new_body + text[section.end(1) :]
        return text[: section.start(1)] + assignment + "\n" + body + text[section.end(1) :]
    if text and not text.endswith("\n"):
        text += "\n"
    return text + f"\n[tool.renglo]\n{assignment}\n"


def set_package_json_platform(text: str, platform: str) -> str:
    """Set ``renglo.platform`` without rewriting the rest of the file."""
    block = re.search(r'("renglo"\s*:\s*\{)(.*?)(\})', text, re.S)
    if block:
        body = block.group(2)
        if re.search(r'"platform"\s*:', body):
            new_body = re.sub(
                r'("platform"\s*:\s*")[^"]*"',
                lambda match: f'{match.group(1)}{platform}"',
                body,
                count=1,
            )
        else:
            new_body = body + f'\n    "platform": "{platform}"'
        return text[: block.start(2)] + new_body + text[block.end(2) :]
    version_line = re.search(r'^[ \t]*"version"\s*:\s*"[^"]*",\n', text, re.M)
    if not version_line:
        return text
    inserted = f'  "renglo": {{\n    "platform": "{platform}"\n  }},\n'
    return text[: version_line.end()] + inserted + text[version_line.end() :]


def _stable_platform(version: str) -> str:
    return drop_rc(version)[0]
