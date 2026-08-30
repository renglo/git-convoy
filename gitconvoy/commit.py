from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gitconvoy import gitutil
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import Feature, State
from gitconvoy.workspace import feature_repos, merge_sort

InputFn = Callable[[str], str]
WriteFn = Callable[[str], None]

_RESET = "\033[0m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


@dataclass
class DirtyRepo:
    id: str
    path: str
    repo_path: Path
    branch: str
    porcelain: str
    stat: str
    files: list[str]
    diff: str | None = None


def commit(
    workspace: Path,
    state: State,
    *,
    plan: bool = False,
    from_file: str | None = None,
    header: str | None = None,
    header_only: bool = False,
    include_diff: bool = False,
    as_json: bool = False,
    input_fn: InputFn | None = None,
    write_fn: WriteFn | None = None,
    is_tty: bool | None = None,
) -> dict:
    if plan and from_file:
        raise GitConvoyError("pass either --plan or --from, not both")
    if plan and header_only:
        raise GitConvoyError("pass either --plan or --header-only, not both")

    applying = bool(from_file) or header_only
    if applying:
        return _apply(
            workspace,
            state,
            from_file=from_file,
            header=header,
            header_only=header_only,
        )

    want_plan = plan or as_json
    if want_plan:
        return _plan(workspace, state, header=header, include_diff=include_diff)

    if is_tty is None:
        is_tty = sys.stdin.isatty()
    if not is_tty:
        raise GitConvoyError(
            "not a tty; pass --plan, --from FILE, or --header-only"
        )
    return _interactive(
        workspace,
        state,
        header=header,
        input_fn=input_fn or input,
        write_fn=write_fn or _stdout,
    )


def _plan(
    workspace: Path,
    state: State,
    *,
    header: str | None,
    include_diff: bool,
) -> dict:
    feature, dirty = _targets(workspace, state, include_diff=include_diff)
    return {
        "ok": True,
        "mode": "plan",
        "feature": feature.name,
        "branch": feature.branch,
        "header": (header or "").strip(),
        "repos": [_plan_row(item) for item in dirty],
    }


def _apply(
    workspace: Path,
    state: State,
    *,
    from_file: str | None,
    header: str | None,
    header_only: bool,
) -> dict:
    feature, dirty = _targets(workspace, state, include_diff=False)
    payload_header, bodies = _payload(
        dirty,
        from_file=from_file,
        header=header,
        header_only=header_only,
    )
    if not dirty:
        return {
            "ok": True,
            "mode": "commit",
            "feature": feature.name,
            "branch": feature.branch,
            "header": (payload_header or "").strip(),
            "repos": [],
        }
    message_header = format_commit_message(payload_header, "")
    committed = []
    for item in dirty:
        message = format_commit_message(payload_header, bodies.get(item.id, ""))
        sha = gitutil.commit_all(item.repo_path, message)
        committed.append(
            {
                "id": item.id,
                "path": item.path,
                "sha": sha,
                "message": message,
            }
        )
    return {
        "ok": True,
        "mode": "commit",
        "feature": feature.name,
        "branch": feature.branch,
        "header": message_header,
        "repos": committed,
    }


def _interactive(
    workspace: Path,
    state: State,
    *,
    header: str | None,
    input_fn: InputFn,
    write_fn: WriteFn,
) -> dict:
    feature, dirty = _targets(workspace, state, include_diff=True)
    if not dirty:
        write_fn("nothing to commit")
        return {
            "ok": True,
            "mode": "commit",
            "feature": feature.name,
            "branch": feature.branch,
            "header": (header or "").strip(),
            "printed": True,
            "repos": [],
        }

    color = _want_color()
    write_fn(_rule("═"))
    write_fn(
        _paint(
            f"{feature.name}  {feature.branch}  {len(dirty)} dirty repos",
            _BOLD,
            color,
        )
    )
    write_fn("merge order: " + " → ".join(item.id for item in dirty))
    write_fn(_rule("═"))
    write_fn("Shared commit header (reused for every repo).")
    write_fn(_rule("═"))
    header_text = (header or "").strip()
    committed: list[dict] = []
    previous_body = ""
    try:
        while not header_text:
            header_text = input_fn("Header: ").strip()
        for index, item in enumerate(dirty, start=1):
            write_fn("")
            write_fn(_rule("═"))
            write_fn(
                _paint(
                    f"{item.id}  ({item.path})  {index}/{len(dirty)}",
                    _BOLD,
                    color,
                )
            )
            write_fn(_rule("─"))
            if item.stat:
                write_fn(_paint(item.stat, _DIM, color))
            if item.porcelain:
                write_fn(_paint(item.porcelain, _DIM, color))
            if item.diff:
                write_fn(color_diff(item.diff, enabled=color))
            write_fn(_rule("═"))
            write_fn(f"Describe what changed in this repo ({item.id}).")
            write_fn(
                "Enter = header only.  . = reuse previous.  e = edit header."
            )
            write_fn(_rule("═"))
            body = input_fn(f"{item.id}> ").rstrip("\n")
            if body.strip() == "e":
                nxt = input_fn(f"Header [{header_text}]: ").strip()
                if nxt:
                    header_text = nxt
                write_fn(_rule("═"))
                write_fn(f"Describe what changed in this repo ({item.id}).")
                write_fn(_rule("═"))
                body = input_fn(f"{item.id}> ").rstrip("\n")
            if body.strip() == ".":
                body = previous_body
            if not _confirm_commit(input_fn):
                write_fn(f"skipped {item.id}")
                continue
            message = format_commit_message(header_text, body)
            sha = gitutil.commit_all(item.repo_path, message)
            previous_body = body.strip()
            committed.append(
                {
                    "id": item.id,
                    "path": item.path,
                    "sha": sha,
                    "message": message,
                }
            )
            write_fn(_paint(f"committed {item.id}  {sha}", _GREEN, color))
    except (KeyboardInterrupt, EOFError) as exc:
        done = ", ".join(row["id"] for row in committed) or "none"
        raise GitConvoyError(f"aborted; already committed: {done}") from exc

    return {
        "ok": True,
        "mode": "commit",
        "feature": feature.name,
        "branch": feature.branch,
        "header": header_text,
        "printed": True,
        "repos": committed,
    }


def _confirm_commit(input_fn: InputFn) -> bool:
    while True:
        answer = input_fn(
            "This is going to commit to the repo. Continue? : "
        ).strip().lower()
        if answer in {"yes", "y"}:
            return True
        if answer in {"no", "n"}:
            return False


def _targets(
    workspace: Path,
    state: State,
    *,
    include_diff: bool,
) -> tuple[Feature, list[DirtyRepo]]:
    feature = state.require_feature()
    products = {repo.id: repo for repo in feature_repos(workspace)}
    participant_ids = set(feature.repo_ids())
    unadopted: list[str] = []
    for repo in products.values():
        if repo.id in participant_ids:
            continue
        if gitutil.is_dirty(repo.path):
            unadopted.append(repo.id)
    if unadopted:
        raise GitConvoyError(
            "dirty product repos are not on the feature sheet: "
            + ", ".join(unadopted)
            + ". run: git convoy feature adopt"
        )

    dirty: list[DirtyRepo] = []
    wrong_branch: list[str] = []
    for row in feature.repos:
        product = products.get(row.id)
        repo_path = workspace / row.path
        if product:
            repo_path = product.path
        if not gitutil.is_dirty(repo_path):
            continue
        branch = gitutil.current_branch(repo_path)
        if branch != feature.branch:
            wrong_branch.append(f"{row.id} is on {branch}, not {feature.branch}")
            continue
        dirty.append(_snapshot(row.id, row.path, repo_path, branch, include_diff))
    if wrong_branch:
        raise GitConvoyError(
            "; ".join(wrong_branch) + ". run: git convoy feature adopt"
        )
    order = {name: index for index, name in enumerate(merge_sort([item.id for item in dirty]))}
    dirty.sort(key=lambda item: order.get(item.id, 99))
    return feature, dirty


def _snapshot(
    repo_id: str,
    rel: str,
    repo_path: Path,
    branch: str,
    include_diff: bool,
) -> DirtyRepo:
    porcelain = gitutil.status_porcelain(repo_path)
    files = gitutil.porcelain_paths(porcelain)
    stat = gitutil.diff_stat(repo_path)
    if not stat:
        if files:
            stat = "untracked: " + ", ".join(files)
        else:
            stat = "(no diff vs HEAD)"
    diff = None
    if include_diff:
        diff = _full_diff(repo_path, porcelain)
    return DirtyRepo(
        id=repo_id,
        path=rel,
        repo_path=repo_path,
        branch=branch,
        porcelain=porcelain,
        stat=stat.strip(),
        files=files,
        diff=diff,
    )


def _full_diff(repo_path: Path, porcelain: str) -> str:
    parts: list[str] = []
    patch = gitutil.diff_patch(repo_path)
    if patch:
        parts.append(patch)
    for line in porcelain.splitlines():
        if not line.startswith("?? "):
            continue
        rel = line[3:].strip().strip('"')
        path = repo_path / rel
        if not path.is_file():
            parts.append(f"diff --git a/{rel} b/{rel}\nnew file\n--- /dev/null\n+++ b/{rel}")
            continue
        text = _read_text(path)
        if text is None:
            parts.append(
                f"diff --git a/{rel} b/{rel}\nnew file (binary or unreadable)"
            )
            continue
        parts.append(_untracked_as_diff(rel, text))
    return "\n".join(parts).strip()


def _read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _plan_row(item: DirtyRepo) -> dict:
    row = {
        "id": item.id,
        "path": item.path,
        "branch": item.branch,
        "porcelain": item.porcelain,
        "stat": item.stat,
        "files": item.files,
        "body": "",
    }
    if item.diff is not None:
        row["diff"] = item.diff
    return row


def _payload(
    dirty: list[DirtyRepo],
    *,
    from_file: str | None,
    header: str | None,
    header_only: bool,
) -> tuple[str, dict[str, str]]:
    dirty_ids = [item.id for item in dirty]
    if from_file:
        raw = _load_from(from_file)
        json_header = (raw.get("header") or "").strip()
        rows = raw.get("repos")
        if rows is None:
            raise GitConvoyError("--from JSON needs a repos array")
        if not isinstance(rows, list):
            raise GitConvoyError("--from JSON repos must be an array")
        payload_ids: list[str] = []
        bodies: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                raise GitConvoyError("--from JSON repos need an id")
            repo_id = str(row["id"])
            payload_ids.append(repo_id)
            bodies[repo_id] = "" if header_only else str(row.get("body") or "")
        _require_same_ids(dirty_ids, payload_ids)
        chosen_header = (header or "").strip() or json_header
        return chosen_header, bodies

    if not header_only:
        raise GitConvoyError("pass --from FILE or --header-only")
    if not (header or "").strip():
        raise GitConvoyError("--header-only requires --header")
    return (header or "").strip(), {repo_id: "" for repo_id in dirty_ids}


def _require_same_ids(dirty_ids: list[str], payload_ids: list[str]) -> None:
    dirty_set = set(dirty_ids)
    payload_set = set(payload_ids)
    if len(payload_ids) != len(payload_set):
        raise GitConvoyError("--from JSON has duplicate repo ids")
    missing = [repo_id for repo_id in dirty_ids if repo_id not in payload_set]
    extra = [repo_id for repo_id in payload_ids if repo_id not in dirty_set]
    if missing or extra:
        parts = []
        if missing:
            parts.append("missing dirty repos: " + ", ".join(missing))
        if extra:
            parts.append("not dirty (or unknown): " + ", ".join(extra))
        raise GitConvoyError(
            "commit plan does not match dirty participants ("
            + "; ".join(parts)
            + ")"
        )


def _load_from(path: str) -> dict:
    if path == "-":
        text = sys.stdin.read()
    else:
        file_path = Path(path)
        if not file_path.is_file():
            raise GitConvoyError(f"plan file not found: {path}")
        text = file_path.read_text()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GitConvoyError(f"invalid JSON in --from: {exc}") from exc
    if not isinstance(raw, dict):
        raise GitConvoyError("--from JSON must be an object")
    return raw


def format_commit_message(header: str, body: str) -> str:
    header = header.strip()
    if not header:
        raise GitConvoyError("header is empty")
    body = (body or "").strip()
    if body:
        return f"{header}\n\n{body}"
    return header


def color_diff(diff: str, *, enabled: bool | None = None) -> str:
    if enabled is None:
        enabled = _want_color()
    if not enabled or not diff:
        return diff
    lines: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            lines.append(f"{_BOLD}{line}{_RESET}")
        elif line.startswith("+"):
            lines.append(f"{_GREEN}{line}{_RESET}")
        elif line.startswith("-"):
            lines.append(f"{_RED}{line}{_RESET}")
        elif line.startswith("@@"):
            lines.append(f"{_CYAN}{line}{_RESET}")
        elif line.startswith("diff "):
            lines.append(f"{_BOLD}{line}{_RESET}")
        else:
            lines.append(line)
    return "\n".join(lines)


def _untracked_as_diff(rel: str, text: str) -> str:
    lines = text.splitlines()
    count = len(lines) or 1
    added = "\n".join(f"+{line}" for line in lines) if lines else "+"
    return (
        f"diff --git a/{rel} b/{rel}\n"
        f"new file\n"
        f"--- /dev/null\n"
        f"+++ b/{rel}\n"
        f"@@ -0,0 +1,{count} @@\n"
        f"{added}"
    )


def _want_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def _paint(text: str, code: str, enabled: bool) -> str:
    if not enabled or not text:
        return text
    return f"{code}{text}{_RESET}"


def _rule(char: str = "═") -> str:
    width = shutil.get_terminal_size((72, 20)).columns
    width = min(max(width, 40), 80)
    return char * width


def _stdout(text: str) -> None:
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
