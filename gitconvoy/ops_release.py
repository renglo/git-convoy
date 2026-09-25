"""Sheet-free ops platform release: bump, PR, tag, verify, optional helper pin."""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from gitconvoy import adopt as adopt_cmd
from gitconvoy import ghutil
from gitconvoy import gitutil
from gitconvoy import membership
from gitconvoy import versions
from gitconvoy.errors import GitConvoyError
from gitconvoy.train import _verify_detail
from gitconvoy.workflows import tag_push_workflows
from gitconvoy.workspace import ops_repos, require_repo


def release(
    workspace: Path,
    repo_ids: list[str],
    *,
    bump: str = "patch",
    pin: str | None = None,
    bom: str | None = None,
    verify: bool = False,
    wait: bool = False,
    use_gh: bool = True,
    push: bool = True,
) -> dict:
    ids = [item.strip() for item in repo_ids if item and item.strip()]
    if not ids:
        raise GitConvoyError(
            "ops release needs at least one repo id; "
            "example: git convoy ops release bom-helper"
        )
    if pin not in (None, "tag", "sha"):
        raise GitConvoyError("ops release --pin must be tag or sha")
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
            row = _release_one(
                workspace,
                repo,
                bump=bump,
                pin=pin,
                bom=bom,
                verify=verify,
                wait=wait,
                use_gh=use_gh,
                push=push,
            )
        except GitConvoyError as exc:
            row = {
                "id": repo.id,
                "path": repo.rel,
                "status": "failed",
                "error": exc.message,
            }
            failed.append(repo.id)
        rows.append(row)
        if row.get("status") == "failed" and repo.id not in failed:
            failed.append(repo.id)
    note = _release_note(rows, pin=pin, verify=verify)
    return {
        "ok": not failed,
        "repos": rows,
        "failed": failed,
        "note": note,
    }


def _release_one(
    workspace: Path,
    repo,
    *,
    bump: str,
    pin: str | None,
    bom: str | None,
    verify: bool,
    wait: bool,
    use_gh: bool,
    push: bool,
) -> dict:
    policy = membership.read_ops_policy(repo.path)
    gitutil.fetch(repo.path)
    if gitutil.is_dirty(repo.path):
        raise GitConvoyError(
            f"{repo.id} is dirty; commit or stash in this repo, then retry"
        )
    ensured = gitutil.ensure_develop(repo.path, push=push)
    if ensured.get("status") == "failed":
        raise GitConvoyError(
            f"{repo.id}: cannot ensure develop"
            + (f" ({ensured.get('error')})" if ensured.get("error") else "")
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
    current = _require_policy_version(repo.path, repo.id, policy)
    tag = gitutil.last_stable_tag(repo.path)
    tag_ver = tag[1:] if tag and tag.startswith("v") else None
    target, bumped = _resolve_target(current, tag_ver, bump)
    if bumped:
        pep, npm = versions.drop_rc(target)
        versions.write_version(repo.path, pep, npm)
        gitutil.commit_all(repo.path, f"Release {pep}")
        if push and gitutil.origin_url(repo.path):
            gitutil.push(repo.path, "origin", "develop")
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
    if gitutil.ahead_of(repo.path, main_ref, develop_ref):
        raise GitConvoyError(
            f"{repo.id}: main is ahead of develop; "
            "absorb the hotfix tag into develop, then retry"
        )
    if gitutil.ahead_of(repo.path, develop_ref, main_ref):
        pr_info = _open_release_pr(
            repo.path, repo.id, target, use_gh=use_gh
        )
        row = {
            "id": repo.id,
            "path": repo.rel,
            "status": "pr-needed",
            "from": current if bumped else (tag_ver or current),
            "to": target,
            "bumped": bumped,
            "tag": None,
            "policy": policy,
            **pr_info,
        }
        if pin:
            row["pin"] = _pin_helper(
                workspace,
                repo,
                style=pin,
                tag=None,
                sha=_pin_sha(repo.path, develop_ref),
                bom=bom,
            )
        return row
    if not _same_commit(repo.path, develop_ref, main_ref) and not gitutil.is_ancestor(
        repo.path, develop_ref, main_ref
    ):
        raise GitConvoyError(
            f"{repo.id}: develop and main have diverged; reconcile, then retry"
        )
    tagged = _tag_main(repo.path, repo.id, target, push=push)
    row = {
        "id": repo.id,
        "path": repo.rel,
        "status": tagged["status"],
        "from": tag_ver or current,
        "to": target,
        "bumped": bumped,
        "tag": tagged["tag"],
        "policy": policy,
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
    if pin:
        row["pin"] = _pin_helper(
            workspace,
            repo,
            style=pin,
            tag=tagged["tag"],
            sha=_pin_sha(repo.path, main_ref),
            bom=bom,
        )
    return row


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


def _resolve_target(current: str, tag_ver: str | None, bump: str) -> tuple[str, bool]:
    if tag_ver is None:
        return current, False
    cmp = versions.cmp_stable(current, tag_ver)
    if cmp > 0:
        return current, False
    if cmp < 0:
        raise GitConvoyError(
            f"develop version {current} is behind last tag v{tag_ver}"
        )
    return versions.bump(current, bump), True


def _same_commit(repo: Path, left: str, right: str) -> bool:
    a = gitutil.rev_parse(repo, left)
    b = gitutil.rev_parse(repo, right)
    return bool(a and b and a == b)


def _open_release_pr(
    repo: Path, repo_id: str, target: str, *, use_gh: bool
) -> dict:
    slug = gitutil.github_slug(repo)
    compare = (
        f"https://github.com/{slug}/compare/main...develop" if slug else None
    )
    pr_url = None
    if use_gh and slug and gitutil.gh_bin():
        pr_url = _gh_create_release_pr(repo, slug, repo_id, target)
    return {"pr": pr_url, "compare": compare}


def _gh_create_release_pr(
    repo: Path, slug: str, repo_id: str, target: str
) -> str | None:
    gh = gitutil.gh_bin()
    if not gh:
        return None
    existing = subprocess.run(
        [
            gh,
            "pr",
            "list",
            "--repo",
            slug,
            "--head",
            "develop",
            "--base",
            "main",
            "--json",
            "url",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if existing.returncode == 0 and existing.stdout:
        rows = json.loads(existing.stdout)
        if rows:
            return rows[0].get("url")
    result = subprocess.run(
        [
            gh,
            "pr",
            "create",
            "--repo",
            slug,
            "--base",
            "main",
            "--head",
            "develop",
            "--title",
            f"Release {repo_id} {target} (develop → main)",
            "--body",
            f"Promote `{repo_id}` to `{target}` and tag `v{target}` after merge.",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def _tag_main(repo: Path, repo_id: str, target: str, *, push: bool) -> dict:
    gitutil.checkout_branch(repo, "main")
    if gitutil.rev_parse(repo, "origin/main"):
        pulled = gitutil.run(repo, "pull", "--ff-only", "origin", "main", check=False)
        if pulled.returncode != 0:
            gitutil.checkout_branch(repo, "develop")
            raise GitConvoyError(
                f"{repo_id}: cannot fast-forward main; merge the release PR, then retry"
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
    for rel in ("pyproject.toml", "package/pyproject.toml"):
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


def _pin_sha(repo: Path, ref: str) -> str:
    return gitutil.rev_parse(repo, ref) or ""


def _pin_helper(
    workspace: Path,
    repo,
    *,
    style: str,
    tag: str | None,
    sha: str,
    bom: str | None,
) -> dict:
    root = adopt_cmd.find_bom_repo(workspace, bom)
    targets = root / "deploy_targets.yml"
    if not targets.is_file():
        raise GitConvoyError(f"missing {targets}")
    helper = _read_helper(targets)
    if helper is None:
        raise GitConvoyError(f"{targets}: no helper: section")
    slug = gitutil.github_slug(repo.path)
    if not _helper_matches(helper.get("repository") or "", repo.id, slug):
        return {
            "status": "skipped",
            "reason": "not deploy_targets.helper",
            "file": str(targets.relative_to(workspace)),
        }
    if style == "tag" and tag:
        ref = tag
        kind = "tag"
    else:
        if not sha:
            raise GitConvoyError(f"{repo.id}: no SHA available to pin")
        ref = sha
        kind = "sha"
    text = targets.read_text()
    updated = _set_helper_ref(text, ref)
    if updated != text:
        targets.write_text(updated)
    return {
        "status": "updated",
        "kind": kind,
        "ref": ref,
        "file": str(targets.relative_to(workspace)),
        "note": "commit and push the BOM repo; git-convoy does not push *-bom",
    }


def _read_helper(targets: Path) -> dict | None:
    text = targets.read_text()
    if not re.search(r"(?m)^helper:\s*$", text):
        return None
    repo_match = re.search(
        r"(?m)^helper:\n(?:[ \t]+.+\n)*?[ \t]+repository:\s+(\S+)", text
    )
    ref_match = re.search(
        r"(?m)^helper:\n(?:[ \t]+.+\n)*?[ \t]+ref:\s+(\S+)", text
    )
    return {
        "repository": (repo_match.group(1) if repo_match else "").strip(),
        "ref": (ref_match.group(1) if ref_match else "").strip(),
    }


def _helper_matches(helper_repo: str, repo_id: str, slug: str | None) -> bool:
    name = helper_repo.strip()
    if not name:
        return False
    if name == repo_id:
        return True
    if name.endswith("/" + repo_id):
        return True
    if slug and name == slug:
        return True
    return False


def _set_helper_ref(text: str, ref: str) -> str:
    newline = "\n" if text.endswith("\n") or "\n" in text else "\n"
    lines = text.splitlines()
    out: list[str] = []
    in_helper = False
    wrote_ref = False
    saw_helper = False
    for line in lines:
        if re.match(r"^helper:\s*$", line):
            in_helper = True
            saw_helper = True
            out.append(line)
            continue
        if in_helper:
            if line.strip() and not line.startswith((" ", "\t")):
                if not wrote_ref:
                    out.append(f"  ref: {ref}")
                    wrote_ref = True
                in_helper = False
                out.append(line)
                continue
            if re.match(r"^[ \t]+ref:\s*", line):
                indent = re.match(r"^([ \t]+)", line)
                prefix = indent.group(1) if indent else "  "
                out.append(f"{prefix}ref: {ref}")
                wrote_ref = True
                continue
        out.append(line)
    if in_helper and not wrote_ref:
        out.append(f"  ref: {ref}")
        wrote_ref = True
    if not saw_helper:
        raise GitConvoyError("deploy_targets.yml has no helper: section")
    return newline.join(out) + (newline if text.endswith("\n") else "")


def _release_note(rows: list[dict], *, pin: str | None, verify: bool) -> str:
    bits: list[str] = []
    needed = [row["id"] for row in rows if row.get("status") == "pr-needed"]
    tagged = [row["id"] for row in rows if row.get("status") == "tagged"]
    already = [row["id"] for row in rows if row.get("status") == "already"]
    failed = [row["id"] for row in rows if row.get("status") == "failed"]
    if needed:
        bits.append(
            "Merge develop→main PRs, then re-run git convoy ops release "
            + ",".join(needed)
            + " to tag."
        )
    if tagged:
        bits.append("Tagged " + ", ".join(tagged) + "; v* push publishes wheels.")
    if already:
        bits.append("Already tagged: " + ", ".join(already) + ".")
    if failed:
        bits.append("Failed: " + ", ".join(failed) + ".")
    if pin:
        bits.append("BOM helper pin is local until you commit *-bom.")
    if verify and any(
        (row.get("verify") or {}).get("status") in {"pending", "missing"}
        for row in rows
    ):
        bits.append("Re-run with --verify --wait to poll publish workflows.")
    return " ".join(bits) or "Ops release complete."
