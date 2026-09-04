from __future__ import annotations

import sys
import time
from pathlib import Path

from gitconvoy import ghutil
from gitconvoy import gitutil, versions
from gitconvoy.sync import DevelopSyncEntry, format_develop_sync_text, sync_repos_develop
from gitconvoy.workflows import repo_publishes_on_tag, tag_push_workflows
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, Train, TrainRepo, save
from gitconvoy.workspace import Repo, merge_sort, product_repos, require_repo


def _has_version(repo: Path) -> bool:
    info = versions.read_version(repo)
    return bool(info.get("python") or info.get("npm"))


def cut(
    workspace: Path,
    state: State,
    name: str,
    bump: str = "patch",
    repo_ids: list[str] | None = None,
    no_bump: bool = False,
) -> dict:
    slug = _slug(name)
    branch = f"release/{slug}"
    repos = product_repos(workspace)
    skipped: list[dict] = []
    if repo_ids:
        chosen = [require_repo(repos, repo_id) for repo_id in repo_ids]
        for repo in chosen:
            if not _has_version(repo.path):
                raise GitConvoyError(
                    f"{repo.id}: no version file; cannot cut a release train for this repo"
                )
    else:
        chosen = []
        for repo in repos:
            if not gitutil.develop_ahead_of_stable(repo.path):
                continue
            if not _has_version(repo.path):
                skipped.append(
                    {
                        "id": repo.id,
                        "path": repo.rel,
                        "reason": "no-version-file",
                    }
                )
                continue
            chosen.append(repo)
    if not chosen:
        if skipped:
            ids = ", ".join(item["id"] for item in skipped)
            raise GitConvoyError(
                "no publishable repos are ahead of their last stable tag "
                f"(skipped without version files: {ids})"
            )
        raise GitConvoyError(
            "no repos are ahead of their last stable tag; pass --repos to force"
        )
    train = state.trains.get(slug) or Train(name=slug, branch=branch)
    train.status = "cut"
    added: list[dict] = []
    for repo in chosen:
        gitutil.fetch(repo.path)
        if gitutil.is_dirty(repo.path):
            raise GitConvoyError(f"{repo.id} is dirty; commit or stash before train cut")
        gitutil.checkout_integration(repo.path)
        gitutil.checkout_branch(repo.path, branch)
        info = versions.read_version(repo.path)
        current = info.get("python") or info.get("npm")
        to = None
        changed: list[str] = []
        if current and not no_bump:
            to = versions.bump(current, bump)
            pep, npm = versions.with_rc(to, 1)
            changed = versions.write_version(repo.path, pep, npm)
            gitutil.run(repo.path, "add", "-A")
            gitutil.run(
                repo.path,
                "commit",
                "-m",
                f"Set {pep} for train {slug}",
            )
            to = pep
        row = TrainRepo(
            id=repo.id,
            path=repo.rel,
            from_version=current,
            to=to,
        )
        train.add_repo(row)
        added.append(
            {
                "id": repo.id,
                "path": repo.rel,
                "from": current,
                "to": to,
                "files": changed,
            }
        )
    state.trains[slug] = train
    state.current_train = slug
    save(workspace, state)
    return {
        "ok": True,
        "train": slug,
        "branch": branch,
        "repos": added,
        "skipped": skipped,
    }


def tag_rc(workspace: Path, state: State, push: bool = True) -> dict:
    train = state.require_train()
    develop_sync = _sync_train_develop(
        workspace,
        train,
        push=push,
        retry_hint="git convoy train tag-rc",
    )
    tagged: list[dict] = []
    for repo_row in _ordered(train):
        repo_path = workspace / repo_row.path
        gitutil.checkout_branch(repo_path, train.branch)
        info = versions.read_version(repo_path)
        current = info.get("python") or info.get("npm")
        if not current:
            raise GitConvoyError(f"{repo_row.id}: no version file")
        pep, npm = _ensure_rc(current)
        tag = f"v{_tag_body(pep)}"
        # Re-running tag-rc after more commits on release/<name> must mint a
        # new rc. If HEAD still matches the existing tag, keep it (idempotent).
        existing = gitutil.rev_parse(repo_path, f"refs/tags/{tag}")
        head = gitutil.rev_parse(repo_path, "HEAD")
        if existing and head and existing != head:
            pep, npm = versions.next_rc(pep)
            tag = f"v{_tag_body(pep)}"
        if pep != current or info.get("npm") not in {None, npm}:
            versions.write_version(repo_path, pep, npm)
            gitutil.run(repo_path, "add", "-A")
            gitutil.run(
                repo_path,
                "commit",
                "-m",
                f"Set {pep} for train {train.name}",
                check=False,
            )
        if not gitutil.rev_parse(repo_path, f"refs/tags/{tag}"):
            gitutil.run(repo_path, "tag", tag)
        if push:
            gitutil.push(repo_path, "-u", "origin", train.branch)
            gitutil.push(repo_path, "origin", tag)
        repo_row.to = pep
        repo_row.rc_tag = tag
        tagged.append({"id": repo_row.id, "tag": tag, "version": pep})
    train.status = "stabilizing"
    save(workspace, state)
    result = {
        "ok": develop_sync["ok"],
        "train": train.name,
        "repos": tagged,
        "develop_sync": develop_sync,
    }
    if not develop_sync["ok"]:
        result["note"] = develop_sync.get("note")
    return result


def mergeback(
    workspace: Path,
    state: State,
    name: str | None = None,
    push: bool = True,
) -> dict:
    """Merge tagged main into develop for every product repo.

    Train participants use the stable tag from the sheet; other repos use their
    latest stable tag (or main). Idempotent. Safe to re-run after a partial
    publish or a conflict. Continues past per-repo failures.
    """
    train = state.require_train(name)
    if train.status != "published":
        raise GitConvoyError(
            f"train {train.name} is {train.status}; "
            "mergeback runs after train publish"
        )
    data = _sync_all_product_develop(
        workspace,
        train,
        push=push,
        retry_hint="git convoy train mergeback",
    )
    data["train"] = train.name
    if data.get("failed"):
        data["note"] = (
            "stable tags are on main; "
            "fix the failed repos, then: git convoy train mergeback"
        )
    return data


def format_mergeback_text(data: dict) -> str:
    return format_develop_sync_text(data, label=f"mergeback {data['train']}")


def publish(workspace: Path, state: State, push: bool = True) -> dict:
    train = state.require_train()
    published: list[dict] = []
    for repo_row in _ordered(train):
        repo_path = workspace / repo_row.path
        gitutil.checkout_branch(repo_path, train.branch)
        if gitutil.is_dirty(repo_path):
            raise GitConvoyError(f"{repo_row.id} is dirty")
        info = versions.read_version(repo_path)
        current = info.get("python") or info.get("npm")
        if not current:
            raise GitConvoyError(f"{repo_row.id}: no version file")
        pep, npm = versions.drop_rc(current)
        versions.write_version(repo_path, pep, npm)
        gitutil.run(repo_path, "add", "-A")
        gitutil.run(
            repo_path,
            "commit",
            "-m",
            f"Release {pep}",
            check=False,
        )
        gitutil.checkout_branch(repo_path, "main")
        gitutil.run(repo_path, "pull", "--ff-only", "origin", "main", check=False)
        merged = gitutil.merge(repo_path, train.branch)
        if merged.returncode != 0:
            raise GitConvoyError(
                f"{repo_row.id}: merge to main failed. stop; do not continue the set"
            )
        tag = f"v{pep}"
        if not gitutil.rev_parse(repo_path, f"refs/tags/{tag}"):
            gitutil.run(repo_path, "tag", tag)
        if push:
            gitutil.push(repo_path, "origin", "main")
            gitutil.push(repo_path, "origin", tag)
        repo_row.to = pep
        repo_row.stable_tag = tag
        published.append({"id": repo_row.id, "tag": tag, "version": pep})
    train.status = "published"
    save(workspace, state)
    mb = mergeback(workspace, state, train.name, push=push)
    by_id = {row["id"]: row for row in mb["repos"]}
    for row in published:
        extra = by_id.get(row["id"]) or {}
        row["synced_develop"] = bool(extra.get("synced"))
        row["develop_status"] = extra.get("status")
    result = {
        "ok": mb["ok"],
        "train": train.name,
        "merge_order": [row.id for row in _ordered(train)],
        "repos": published,
        "mergeback": mb,
    }
    if not mb["ok"]:
        result["note"] = mb.get("note") or (
            "stable tags are on main; re-run: git convoy train mergeback"
        )
    return result


def verify(
    workspace: Path,
    state: State,
    name: str | None = None,
    *,
    wait: bool = False,
    timeout_sec: int = 1800,
    poll_sec: int = 30,
    stable: bool | None = None,
) -> dict:
    train = state.require_train(name)
    ghutil.require_gh()
    use_stable = stable if stable is not None else train.status == "published"

    def _verify_repo(repo_row: TrainRepo) -> dict:
        repo_path = workspace / repo_row.path
        tag = (
            (repo_row.stable_tag if use_stable else repo_row.rc_tag)
            or repo_row.stable_tag
            or repo_row.rc_tag
        )
        slug = gitutil.github_slug(repo_path)
        row: dict = {
            "id": repo_row.id,
            "path": repo_row.path,
            "tag": tag,
            "slug": slug,
        }
        publish_wfs = tag_push_workflows(repo_path) if repo_path.is_dir() else []
        row["workflows"] = publish_wfs
        if not publish_wfs:
            row["status"] = "skip"
            row["detail"] = "no workflow triggers on v* tag push (git-clone participant)"
            return row
        if not tag:
            row["status"] = "no-tag"
            row["detail"] = "no tag on train sheet"
            return row
        if not slug:
            row["status"] = "no-remote"
            row["detail"] = "no github.com origin remote"
            return row
        commit = ghutil.tag_sha(repo_path, tag)
        if not commit:
            row["status"] = "no-tag-on-remote"
            row["detail"] = f"tag {tag} not found on origin"
            return row
        wf_rows = ghutil.publish_runs_for_commit(
            slug, commit, publish_wfs, cwd=repo_path
        )
        row["commit"] = commit[:7]
        row["workflow_runs"] = wf_rows
        row["status"] = ghutil.aggregate_workflow_status(wf_rows)
        row["detail"] = _verify_detail(tag, publish_wfs, wf_rows, row["status"])
        success_run = next(
            (w for w in wf_rows if w.get("status") == "success" and w.get("run_url")),
            None,
        )
        if success_run:
            row["run_url"] = success_run["run_url"]
        elif row["status"] == "failure":
            failed = next(
                (w for w in wf_rows if w.get("status") == "failure" and w.get("run_url")),
                None,
            )
            if failed:
                row["run_url"] = failed["run_url"]
        return row

    def _check_once() -> list[dict]:
        return [_verify_repo(repo_row) for repo_row in _ordered(train)]

    def _waiting(rows: list[dict]) -> bool:
        return any(row.get("status") in {"pending", "missing"} for row in rows)

    rows = _check_once()
    deadline = time.monotonic() + timeout_sec if wait else None
    while wait and _waiting(rows) and deadline is not None:
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_sec)
        rows = _check_once()

    verified = [row for row in rows if row.get("status") == "success"]
    skipped = [row for row in rows if row.get("status") == "skip"]
    pending = [
        row for row in rows if row.get("status") in {"pending", "missing"}
    ]
    failed = [
        row
        for row in rows
        if row.get("status") not in {"success", "skip", "pending", "missing"}
    ]
    incomplete = pending + failed
    payload = {
        "ok": not incomplete,
        "train": train.name,
        "status": train.status,
        "tag_kind": "stable" if use_stable else "rc",
        "verified_count": len(verified),
        "skipped_count": len(skipped),
        "pending_count": len(pending),
        "failed_count": len(failed),
        "repo_count": len(rows),
        "repos": rows,
    }
    notes: list[str] = []
    if pending and not wait:
        notes.append("Re-run with --wait to poll for in-progress workflows.")
    if failed:
        notes.append("Fix failed publish workflows, then re-run train verify.")
    if notes:
        payload["note"] = " ".join(notes)
    return payload


def format_verify_text(data: dict) -> str:
    lines = [
        f"{data['train']}  verified {data['verified_count']}/{data['repo_count']} "
        f"({data['tag_kind']} tags; {data.get('skipped_count', 0)} skipped)",
    ]
    groups = [
        ("succeeded", "success"),
        ("skipped", "skip"),
        ("pending", "pending"),
        ("waiting", "missing"),
        ("failed", "failure"),
    ]
    shown: set[str] = set()
    for label, status in groups:
        bucket = [
            row for row in data.get("repos") or [] if row.get("status") == status
        ]
        for row in bucket:
            shown.add(row["id"])
        if not bucket:
            continue
        lines.append(f"{label} ({len(bucket)}):")
        for repo in bucket:
            wf = ", ".join(repo.get("workflows") or []) or "-"
            tag = repo.get("tag") or "-"
            url = f"  {repo['run_url']}" if repo.get("run_url") else ""
            lines.append(
                f"  {repo['id']:20} {tag:16} [{wf}]{url}"
            )
            detail = repo.get("detail")
            if detail and repo.get("status") != "success":
                lines.append(f"    {detail}")
            elif detail and repo.get("status") == "success" and url == "":
                lines.append(f"    {detail}")
    other = [
        row
        for row in data.get("repos") or []
        if row.get("id") not in shown
        and row.get("status") not in {"success", "skip"}
    ]
    if other:
        lines.append(f"unknown ({len(other)}):")
        for repo in other:
            wf = ", ".join(repo.get("workflows") or []) or "-"
            tag = repo.get("tag") or "-"
            lines.append(f"  {repo['id']:20} {tag:16} [{wf}]")
            detail = repo.get("detail")
            if detail:
                lines.append(f"    {detail}")
    note = (data.get("note") or "").strip()
    if note:
        lines.append(note)
    return "\n".join(lines)


def _verify_detail(
    tag: str,
    workflow_files: list[str],
    wf_rows: list[dict],
    status: str,
) -> str:
    wf_list = ", ".join(workflow_files)
    if status == "success":
        return f"{tag} — {wf_list} succeeded"
    if status == "pending":
        return f"{tag} — {wf_list} still running"
    if status == "failure":
        parts = []
        for row in wf_rows:
            if row.get("status") == "failure":
                url = row.get("run_url") or row.get("file")
                parts.append(f"{row['file']} failed ({url})")
        return f"{tag} — " + "; ".join(parts or [f"{wf_list} failed"])
    if status == "missing":
        return (
            f"{tag} @ commit — no Actions run yet for workflows [{wf_list}] "
            "(tag push should trigger these)"
        )
    return status


def delete(
    workspace: Path,
    state: State,
    name: str | None = None,
    *,
    yes: bool = False,
    remote: bool = False,
    as_json: bool = False,
    input_fn=None,
    is_tty: bool | None = None,
) -> dict:
    train = state.require_train(name)
    branch = train.branch
    targets = _delete_targets(workspace, train)
    if not yes:
        if as_json or not (sys.stdin.isatty() if is_tty is None else is_tty):
            raise GitConvoyError(
                "train delete removes release branches; pass --yes to confirm"
            )
        ids = ", ".join(repo.id for repo in targets) or "(none)"
        prompt = (
            f"This will delete local {branch} in {len(targets)} repos ({ids})"
            + (" and on origin" if remote else "")
            + ", remove the train sheet, and check out the integration branch. "
            "Continue? : "
        )
        answer = _confirm_yes(input_fn or input, prompt)
        if not answer:
            return {
                "ok": True,
                "deleted": False,
                "train": train.name,
                "branch": branch,
                "repos": [],
            }

    removed: list[dict] = []
    for repo in targets:
        gitutil.fetch(repo.path)
        current = gitutil.current_branch(repo.path)
        dirty = gitutil.is_dirty(repo.path)
        if dirty and current == branch:
            raise GitConvoyError(
                f"{repo.id} has uncommitted changes on {branch}; "
                "commit or stash before train delete"
            )
        integration = gitutil.current_branch(repo.path)
        if current == branch:
            integration = gitutil.checkout_integration(repo.path)
        on_origin = gitutil.has_remote_branch(repo.path, branch)
        deleted_local = False
        if gitutil.has_local_branch(repo.path, branch):
            gitutil.delete_branch(repo.path, branch)
            deleted_local = True
        deleted_remote = False
        if remote and on_origin:
            gitutil.delete_remote_branch(repo.path, branch)
            deleted_remote = True
        removed.append(
            {
                "id": repo.id,
                "path": repo.rel,
                "branch": gitutil.current_branch(repo.path),
                "integration_branch": integration,
                "deleted_local": deleted_local,
                "deleted_remote": deleted_remote,
                "on_origin": on_origin and not deleted_remote,
            }
        )

    if state.current_train == train.name:
        state.current_train = None
    state.trains.pop(train.name, None)
    save(workspace, state)
    still_on_origin = [row["id"] for row in removed if row["on_origin"]]
    note = (
        f"Removed train {train.name}. Local {branch} deleted where present. "
        "Checked out the integration branch when needed."
    )
    if still_on_origin and not remote:
        note += (
            f" {branch} still on origin in: "
            + ", ".join(still_on_origin)
            + ". Re-run with --remote to delete there."
        )
    return {
        "ok": True,
        "deleted": True,
        "train": train.name,
        "branch": branch,
        "note": note,
        "repos": removed,
    }


def show(state: State, name: str | None = None) -> dict:
    train = state.require_train(name)
    return {
        "ok": True,
        "name": train.name,
        "branch": train.branch,
        "status": train.status,
        "features": train.features,
        "repo_count": len(train.repos),
        "repos": [
            {
                "id": repo.id,
                "path": repo.path,
                "from": repo.from_version,
                "to": repo.to,
                "rc_tag": repo.rc_tag,
                "stable_tag": repo.stable_tag,
            }
            for repo in train.repos
        ],
    }


def _ordered(train: Train) -> list[TrainRepo]:
    order = merge_sort([repo.id for repo in train.repos])
    by_id = {repo.id: repo for repo in train.repos}
    return [by_id[name] for name in order]


def _sync_train_develop(
    workspace: Path,
    train: Train,
    *,
    push: bool,
    retry_hint: str,
) -> dict:
    entries = [
        DevelopSyncEntry(
            id=repo_row.id,
            rel=repo_row.path,
            ref=repo_row.stable_tag,
        )
        for repo_row in _ordered(train)
    ]
    return sync_repos_develop(
        workspace, entries, push=push, retry_hint=retry_hint
    )


def _sync_all_product_develop(
    workspace: Path,
    train: Train,
    *,
    push: bool,
    retry_hint: str,
) -> dict:
    participant_refs = {
        repo_row.id: repo_row.stable_tag for repo_row in train.repos
    }
    entries: list[DevelopSyncEntry] = []
    seen: set[str] = set()
    for repo_row in _ordered(train):
        entries.append(
            DevelopSyncEntry(
                id=repo_row.id,
                rel=repo_row.path,
                ref=participant_refs.get(repo_row.id),
            )
        )
        seen.add(repo_row.id)
    for repo in sorted(product_repos(workspace), key=lambda row: row.id):
        if repo.id in seen:
            continue
        entries.append(DevelopSyncEntry(id=repo.id, rel=repo.rel))
    return sync_repos_develop(
        workspace, entries, push=push, retry_hint=retry_hint
    )


def _delete_targets(workspace: Path, train: Train) -> list[Repo]:
    products = product_repos(workspace)
    by_id = {repo.id: repo for repo in products}
    seen: set[str] = set()
    targets: list[Repo] = []
    for row in train.repos:
        repo = by_id.get(row.id)
        if repo and repo.id not in seen:
            seen.add(repo.id)
            targets.append(repo)
    for repo in products:
        if repo.id in seen:
            continue
        if gitutil.has_local_branch(repo.path, train.branch):
            seen.add(repo.id)
            targets.append(repo)
    return targets


def _confirm_yes(input_fn, prompt: str) -> bool:
    while True:
        answer = input_fn(prompt).strip().lower()
        if answer in {"yes", "y"}:
            return True
        if answer in {"no", "n"}:
            return False


def _ensure_rc(version: str) -> tuple[str, str]:
    _major, _minor, _patch, rc = versions.parse(version)
    if rc is None:
        return versions.with_rc(version, 1)
    return versions.with_rc(version, rc)


def _tag_body(pep: str) -> str:
    major, minor, patch, rc = versions.parse(pep)
    if rc is None:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{patch}-rc.{rc}"


def _slug(name: str) -> str:
    slug = name.strip().replace(" ", "-")
    if slug.startswith("release/"):
        slug = slug[len("release/") :]
    if not slug:
        raise GitConvoyError("train name is empty")
    return slug
