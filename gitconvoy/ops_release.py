"""Ship ops packages: after ops prs merge to develop, ops publish tags main.

Does not open a second PR and does not write renglo.yaml or any *-bom file.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from gitconvoy import ghutil
from gitconvoy import gitutil
from gitconvoy import membership
from gitconvoy import versions
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import Ops, State, load
from gitconvoy.train import _verify_detail
from gitconvoy.workflows import tag_push_workflows
from gitconvoy.workspace import ops_repos, require_repo


_GONE = (
    "After ops prs merge into develop: git convoy ops publish. "
    "ops * does not write renglo.yaml."
)


def release(*_args, **_kwargs) -> dict:
    raise GitConvoyError(f"ops release is gone. {_GONE}")


def propose(*_args, **_kwargs) -> dict:
    raise GitConvoyError(f"ops propose is gone. {_GONE}")


def publish(
    workspace: Path,
    repo_ids: list[str] | None = None,
    *,
    state: State | None = None,
    bump: str = "patch",
    verify: bool = False,
    wait: bool = False,
    push: bool = True,
) -> dict:
    state = state or load(workspace)
    ids, from_sheet = _resolve_ids(state, repo_ids)
    sheet = None
    if state.current_ops and state.current_ops in state.ops_sheets:
        sheet = state.ops_sheets[state.current_ops]
    repos = ops_repos(workspace)
    rows: list[dict] = []
    failed: list[str] = []
    for repo_id in ids:
        try:
            repo = require_repo(repos, repo_id)
        except GitConvoyError:
            rows.append(
                {
                    "id": repo_id,
                    "status": "failed",
                    "error": f"{repo_id}: not an ops repo in this workspace",
                }
            )
            failed.append(repo_id)
            continue
        try:
            row = _publish_one(
                repo,
                sheet=sheet,
                from_sheet=from_sheet,
                bump=bump,
                verify=verify,
                wait=wait,
                push=push,
            )
        except GitConvoyError as exc:
            row = {
                "id": repo.id,
                "path": repo.rel,
                "status": "failed",
                "error": exc.message,
            }
        rows.append(row)
        if row.get("status") in {"failed", "pr-needed"}:
            failed.append(repo.id)
    note = _publish_note(rows, verify=verify)
    return {
        "ok": not failed,
        "phase": "publish",
        "sheet": sheet.name if from_sheet and sheet else None,
        "repos": rows,
        "failed": failed,
        "note": note,
    }


def _resolve_ids(state: State, repo_ids: list[str] | None) -> tuple[list[str], bool]:
    ids = [item.strip() for item in (repo_ids or []) if item and item.strip()]
    if ids:
        return ids, False
    if not state.current_ops:
        raise GitConvoyError(
            "ops publish needs a repo id or a current ops sheet; "
            "example: git convoy ops publish renglo-ops"
        )
    sheet = state.require_ops()
    if not sheet.repos:
        raise GitConvoyError(
            "ops sheet has no participants; run ops adopt or pass a repo id"
        )
    return list(sheet.repo_ids()), True


def _publish_one(
    repo,
    *,
    sheet: Ops | None,
    from_sheet: bool,
    bump: str,
    verify: bool,
    wait: bool,
    push: bool,
) -> dict:
    policy = membership.read_ops_policy(repo.path)
    if from_sheet and policy.get("publish") == "none":
        return {
            "id": repo.id,
            "path": repo.rel,
            "status": "skipped",
            "reason": "publish=none",
            "policy": policy,
            "next": None,
        }
    gitutil.fetch(repo.path)
    if gitutil.is_dirty(repo.path):
        raise GitConvoyError(
            f"{repo.id} is dirty; commit or stash in this repo, then retry"
        )
    ensured = gitutil.ensure_develop(repo.path, push=push)
    if ensured.get("status") == "failed":
        raise GitConvoyError(
            gitutil.format_ensure_develop_failure(repo.id, repo.path, ensured)
        )
    gitutil.checkout_branch(repo.path, "develop")
    if gitutil.rev_parse(repo.path, "origin/develop"):
        pulled = gitutil.run(
            repo.path, "merge", "--ff-only", "origin/develop", check=False
        )
        if pulled.returncode != 0:
            raise GitConvoyError(
                f"{repo.id}: cannot fast-forward develop; reconcile, then retry"
            )
    blocked = _unmerged_ops_pr(repo, sheet)
    if blocked:
        return blocked
    develop_ref = (
        "origin/develop"
        if gitutil.has_remote_branch(repo.path, "develop")
        else "develop"
    )
    main_ref = (
        "origin/main" if gitutil.has_remote_branch(repo.path, "main") else "main"
    )
    if not gitutil.rev_parse(repo.path, main_ref):
        raise GitConvoyError(f"{repo.id}: missing {main_ref}")
    current = _require_policy_version(repo.path, repo.id, policy)
    tag = gitutil.last_stable_tag(repo.path)
    tag_ver = tag[1:] if tag and tag.startswith("v") else None
    has_release_work = _has_release_work(repo.path, develop_ref, main_ref)
    if _release_up_to_date(
        repo.path, develop_ref, main_ref, current, tag_ver, has_release_work
    ):
        shipped = tag_ver or current
        return {
            "id": repo.id,
            "path": repo.rel,
            "status": "already",
            "from": shipped,
            "to": shipped,
            "bumped": False,
            "tag": f"v{shipped}" if shipped else None,
            "policy": policy,
            "next": None,
        }
    target, bumped = _resolve_target(
        current, tag_ver, bump, has_release_work=has_release_work
    )
    if bumped:
        pep, npm = versions.drop_rc(target)
        versions.write_version(repo.path, pep, npm)
        gitutil.commit_all(repo.path, f"Release {pep}")
        if push and gitutil.origin_url(repo.path):
            gitutil.push(repo.path, "origin", "develop")
        has_release_work = True
    if gitutil.ahead_of(repo.path, main_ref, "develop") and not gitutil.same_tree(
        repo.path, "develop", main_ref
    ):
        raise GitConvoyError(
            f"{repo.id}: main is ahead of develop; "
            "absorb the hotfix tag into develop, then retry"
        )
    if not _same_commit(repo.path, "develop", main_ref) and not gitutil.is_ancestor(
        repo.path, "develop", main_ref
    ):
        if not gitutil.is_ancestor(repo.path, main_ref, "develop"):
            raise GitConvoyError(
                f"{repo.id}: develop and main have diverged; reconcile, then retry"
            )
    tagged = _merge_and_tag(repo.path, repo.id, target, push=push)
    row = {
        "id": repo.id,
        "path": repo.rel,
        "status": tagged["status"],
        "from": tag_ver or current,
        "to": target,
        "bumped": bumped,
        "tag": tagged["tag"],
        "policy": policy,
        "next": None,
    }
    if verify:
        row["verify"] = _verify_release(
            repo.path,
            repo.id,
            policy,
            tagged["tag"],
            wait=wait,
        )
        if row["verify"].get("status") not in {"success", "skip"}:
            row["status"] = "failed"
            row["error"] = row["verify"].get("detail") or "publish verify failed"
    return row


def _unmerged_ops_pr(repo, sheet: Ops | None) -> dict | None:
    if sheet is None or repo.id not in sheet.repo_ids():
        return None
    row = next(item for item in sheet.repos if item.id == repo.id)
    merge_status = gitutil.pr_merge_status(
        repo.path, sheet.branch, row.pr, base="develop"
    )
    if merge_status == "merged":
        return None
    return {
        "id": repo.id,
        "path": repo.rel,
        "status": "pr-needed",
        "merge_status": merge_status,
        "pr": row.pr,
        "tag": None,
        "next": f"Merge the ops PR into develop, then: git convoy ops publish {repo.id}",
    }


def _require_policy_version(repo: Path, repo_id: str, policy: dict) -> str:
    info = versions.read_version(repo)
    kind = policy["version"]
    if kind in {"python", "both"} and "python" not in info:
        raise GitConvoyError(
            f"{repo_id}: policy version={kind} but no Python version file"
        )
    if kind in {"npm", "both"} and "npm" not in info:
        raise GitConvoyError(
            f"{repo_id}: policy version={kind} but no npm version file"
        )
    current = info.get("python") or info.get("npm")
    if not current:
        raise GitConvoyError(f"{repo_id}: no version file")
    return versions.drop_rc(current)[0]


def _has_release_work(repo: Path, develop_ref: str, main_ref: str) -> bool:
    if gitutil.ahead_of(repo, develop_ref, main_ref):
        return True
    return not gitutil.same_tree(repo, develop_ref, main_ref)


def _resolve_target(
    current: str,
    tag_ver: str | None,
    bump: str,
    *,
    has_release_work: bool,
) -> tuple[str, bool]:
    if tag_ver is None:
        return current, False
    cmp = versions.cmp_stable(current, tag_ver)
    if cmp > 0:
        return current, False
    if cmp < 0:
        raise GitConvoyError(
            f"develop version {current} is behind last tag v{tag_ver}"
        )
    if not has_release_work:
        return current, False
    return versions.bump(current, bump), True


def _release_up_to_date(
    repo: Path,
    develop_ref: str,
    main_ref: str,
    current: str,
    tag_ver: str | None,
    has_release_work: bool,
) -> bool:
    if has_release_work or not tag_ver:
        return False
    if versions.cmp_stable(current, tag_ver) != 0:
        return False
    tag = f"v{tag_ver}"
    if not gitutil.rev_parse(repo, tag):
        return False
    main_version = _version_on_ref(repo, main_ref)
    if not main_version or versions.drop_rc(main_version)[0] != tag_ver:
        return False
    tag_sha = gitutil.rev_parse(repo, tag)
    main_sha = gitutil.rev_parse(repo, main_ref)
    if not tag_sha or not main_sha or not gitutil.is_ancestor(repo, tag_sha, main_sha):
        return False
    return gitutil.same_tree(repo, develop_ref, main_ref)


def _same_commit(repo: Path, left: str, right: str) -> bool:
    a = gitutil.rev_parse(repo, left)
    b = gitutil.rev_parse(repo, right)
    return bool(a and b and a == b)


def _merge_and_tag(repo: Path, repo_id: str, target: str, *, push: bool) -> dict:
    gitutil.checkout_branch(repo, "main")
    if gitutil.rev_parse(repo, "origin/main"):
        pulled = gitutil.run(repo, "pull", "--ff-only", "origin", "main", check=False)
        if pulled.returncode != 0:
            gitutil.checkout_branch(repo, "develop")
            raise GitConvoyError(
                f"{repo_id}: cannot fast-forward main; reconcile, then retry"
            )
    if not gitutil.same_tree(repo, "develop", "main"):
        merged = gitutil.merge(repo, "develop")
        if merged.returncode != 0:
            gitutil.run(repo, "merge", "--abort", check=False)
            gitutil.checkout_branch(repo, "develop")
            raise GitConvoyError(
                f"{repo_id}: merge develop into main failed; reconcile, then retry"
            )
    on_main = _version_on_ref(repo, "main")
    if on_main:
        pep, _ = versions.drop_rc(on_main)
        if pep != target:
            gitutil.checkout_branch(repo, "develop")
            raise GitConvoyError(
                f"{repo_id}: main is {pep}, expected release version {target}"
            )
    tag = f"v{target}"
    created = False
    if not gitutil.rev_parse(repo, f"refs/tags/{tag}"):
        gitutil.run(repo, "tag", tag)
        created = True
    if push and gitutil.origin_url(repo):
        gitutil.push(repo, "origin", "main")
        gitutil.push(repo, "origin", tag)
    gitutil.checkout_branch(repo, "develop")
    return {
        "tag": tag,
        "status": "tagged" if created else "already",
        "created": created,
    }


def _version_on_ref(repo: Path, ref: str) -> str | None:
    for rel in versions.PYTHON_PYPROJECT_RELS:
        shown = gitutil.run(repo, "show", f"{ref}:{rel}", check=False)
        if shown.returncode != 0:
            continue
        match = re.search(
            r'(?m)^version\s*=\s*["\']([^"\']+)["\']', shown.stdout or ""
        )
        if match:
            return match.group(1)
    return None


def _verify_release(
    repo: Path,
    repo_id: str,
    policy: dict,
    tag: str | None,
    *,
    wait: bool,
) -> dict:
    if policy.get("publish") == "none":
        return {
            "status": "skip",
            "detail": "policy publish=none",
        }
    if not tag:
        return {"status": "skip", "detail": "not tagged yet"}
    workflows = tag_push_workflows(repo)
    if not workflows:
        return {
            "status": "failure",
            "detail": (
                f"{repo_id}: policy publish={policy['publish']} but no v* "
                "tag-push workflow"
            ),
        }
    if not gitutil.gh_bin():
        return {
            "status": "failure",
            "detail": "gh is not on PATH; install gh to verify publish",
        }
    slug = gitutil.github_slug(repo)
    if not slug:
        return {"status": "no-remote", "detail": "no github.com origin remote"}
    deadline = time.monotonic() + 1800 if wait else None
    row = _verify_once(repo, slug, tag, workflows)
    while wait and row.get("status") in {"pending", "missing"} and deadline:
        if time.monotonic() >= deadline:
            break
        time.sleep(30)
        row = _verify_once(repo, slug, tag, workflows)
    return row


def _verify_once(repo: Path, slug: str, tag: str, workflows: list[str]) -> dict:
    commit = ghutil.tag_sha(repo, tag)
    if not commit:
        return {
            "status": "no-tag-on-remote",
            "detail": f"tag {tag} not found on origin",
            "tag": tag,
            "workflows": workflows,
        }
    wf_rows = ghutil.publish_runs_for_commit(slug, commit, workflows, cwd=repo)
    status = ghutil.aggregate_workflow_status(wf_rows)
    return {
        "status": status,
        "detail": _verify_detail(tag, workflows, wf_rows, status),
        "tag": tag,
        "commit": commit[:7],
        "workflows": workflows,
        "workflow_runs": wf_rows,
    }


def _publish_note(rows: list[dict], *, verify: bool) -> str:
    bits: list[str] = []
    needed = [row["id"] for row in rows if row.get("status") == "pr-needed"]
    tagged = [row["id"] for row in rows if row.get("status") == "tagged"]
    already = [row["id"] for row in rows if row.get("status") == "already"]
    skipped = [row["id"] for row in rows if row.get("status") == "skipped"]
    failed = [row["id"] for row in rows if row.get("status") == "failed"]
    if needed:
        bits.append(
            "Merge the ops PR into develop, then: git convoy ops publish "
            + ", ".join(needed)
        )
    if tagged:
        wheel_ids = [
            row["id"]
            for row in rows
            if row.get("status") == "tagged"
            and (row.get("policy") or {}).get("publish") == "python-wheel"
        ]
        other_ids = [id_ for id_ in tagged if id_ not in wheel_ids]
        if wheel_ids:
            bits.append(
                "Tagged " + ", ".join(wheel_ids) + "; the tag push publishes wheels."
            )
        if other_ids:
            bits.append("Tagged " + ", ".join(other_ids) + ".")
    if already:
        bits.append("Already tagged: " + ", ".join(already) + ".")
    if skipped:
        bits.append(
            "Skipped (publish=none): " + ", ".join(skipped) + "."
        )
    if failed:
        bits.append("Failed: " + ", ".join(failed) + ".")
    if verify and any(
        (row.get("verify") or {}).get("status") in {"pending", "missing"}
        for row in rows
    ):
        bits.append("Re-run git convoy ops publish --verify --wait to poll CI.")
    return " ".join(bits) or "Ops publish complete."
