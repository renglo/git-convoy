from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from gitconvoy.errors import GitConvoyError
from gitconvoy import gitutil


def require_gh() -> str:
    gh = gitutil.gh_bin()
    if not gh:
        raise GitConvoyError(
            "gh is not on PATH; install gh and run gh auth login (Full mode)"
        )
    return gh


def _gh_run(
    args: list[str],
    *,
    cwd: Path | None = None,
    json_fields: str | None = None,
) -> subprocess.CompletedProcess[str]:
    gh = require_gh()
    cmd = [gh, *args]
    if json_fields is not None:
        cmd.extend(["--json", json_fields])
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _parse_json(stdout: str) -> Any:
    text = (stdout or "").strip()
    if not text:
        return None
    return json.loads(text)


def gh_available() -> bool:
    return gitutil.gh_bin() is not None and gh_auth_status()


def gh_auth_status() -> bool:
    gh = gitutil.gh_bin()
    if not gh:
        return False
    result = subprocess.run(
        [gh, "auth", "status"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def find_pr_url(slug: str, branch: str, *, cwd: Path | None = None) -> str | None:
    result = _gh_run(
        ["pr", "list", "--repo", slug, "--head", branch, "--state", "all"],
        cwd=cwd,
        json_fields="url,number,state",
    )
    if result.returncode != 0:
        return None
    rows = _parse_json(result.stdout)
    if not rows:
        return None
    open_rows = [row for row in rows if (row.get("state") or "").upper() == "OPEN"]
    chosen = open_rows[0] if open_rows else rows[0]
    return chosen.get("url")


def pr_details(
    slug: str,
    number: int,
    *,
    cwd: Path | None = None,
) -> dict[str, Any] | None:
    result = _gh_run(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            slug,
        ],
        cwd=cwd,
        json_fields="state,mergedAt,reviewDecision,statusCheckRollup",
    )
    if result.returncode != 0:
        return None
    row = _parse_json(result.stdout)
    return row if isinstance(row, dict) else None


def approve_pr(
    slug: str,
    number: int,
    *,
    cwd: Path | None = None,
) -> tuple[bool, str]:
    result = _gh_run(
        [
            "pr",
            "review",
            str(number),
            "--repo",
            slug,
            "--approve",
        ],
        cwd=cwd,
    )
    if result.returncode == 0:
        return True, "approved"
    err = (result.stderr or result.stdout or "gh pr review failed").strip()
    return False, err


def checks_state(details: dict[str, Any] | None) -> str:
    if not details:
        return "unknown"
    rollup = details.get("statusCheckRollup") or {}
    state = (rollup.get("state") or "").upper()
    if state in {"SUCCESS", "FAILURE", "PENDING", "ERROR", "EXPECTED", "ACTION_REQUIRED"}:
        return state.lower()
    return "unknown"


def tag_sha(repo: Path, tag: str) -> str | None:
    gitutil.fetch(repo)
    sha = gitutil.rev_parse(repo, f"refs/tags/{tag}")
    if sha:
        return sha
    result = gitutil.run(repo, "ls-remote", "origin", f"refs/tags/{tag}", check=False)
    line = (result.stdout or "").strip().split()
    return line[0] if line else None


def publish_runs_for_commit(
    slug: str,
    commit: str,
    workflow_files: list[str],
    *,
    cwd: Path | None = None,
) -> list[dict[str, Any]]:
    """One row per workflow file: file, run (or None), status."""
    rows: list[dict[str, Any]] = []
    for workflow in workflow_files:
        result = _gh_run(
            [
                "run",
                "list",
                "--repo",
                slug,
                "--workflow",
                workflow,
                "--commit",
                commit,
                "--limit",
                "3",
            ],
            cwd=cwd,
            json_fields="databaseId,conclusion,status,url,workflowName,createdAt,headSha,event",
        )
        run = None
        if result.returncode == 0:
            parsed = _parse_json(result.stdout) or []
            if parsed:
                run = parsed[0]
        rows.append(
            {
                "file": workflow,
                "run": run,
                "status": run_publish_status(run),
                "run_url": run.get("url") if run else None,
                "workflow_name": run.get("workflowName") if run else None,
            }
        )
    return rows


def aggregate_workflow_status(workflows: list[dict[str, Any]]) -> str:
    if not workflows:
        return "missing"
    statuses = [row["status"] for row in workflows]
    if any(status == "failure" for status in statuses):
        return "failure"
    if any(status == "pending" for status in statuses):
        return "pending"
    if all(status == "success" for status in statuses):
        return "success"
    if all(status == "missing" for status in statuses):
        return "missing"
    return "unknown"


def run_publish_status(run: dict[str, Any] | None) -> str:
    if not run:
        return "missing"
    status = (run.get("status") or "").lower()
    conclusion = (run.get("conclusion") or "").lower()
    if status == "completed":
        if conclusion == "success":
            return "success"
        if conclusion in {"failure", "cancelled", "timed_out", "action_required"}:
            return "failure"
        return conclusion or "failure"
    if status in {"queued", "in_progress", "waiting", "requested", "pending"}:
        return "pending"
    return status or "unknown"
