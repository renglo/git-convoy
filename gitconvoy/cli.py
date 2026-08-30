from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gitconvoy import adopt as adopt_cmd
from gitconvoy import commit as commit_cmd
from gitconvoy import feature as feature_cmd
from gitconvoy import train as train_cmd
from gitconvoy.errors import GitConvoyError
from gitconvoy.initcmd import init
from gitconvoy.output import emit, fail
from gitconvoy.state import load
from gitconvoy.status import status
from gitconvoy.workspace import find_workspace


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    as_json = args.json
    workspace = find_workspace(Path(args.workspace) if args.workspace else None)
    try:
        payload, text = _dispatch(workspace, args)
    except GitConvoyError as exc:
        return fail(exc.message, as_json)
    emit(payload, as_json, text)
    if payload.get("ok") is False:
        return 1
    return 0


def _dispatch(workspace: Path, args: argparse.Namespace) -> tuple[dict, str]:
    state = load(workspace)
    cmd = args.cmd
    if cmd == "init":
        data = init(workspace, state)
        return data, _init_text(data)
    if cmd == "status":
        data = status(workspace, state)
        return data, _status_text(data)
    if cmd == "feature":
        return _feature(workspace, state, args)
    if cmd == "train":
        return _train(workspace, state, args)
    if cmd == "adopt":
        return _adopt(workspace, state, args)
    raise GitConvoyError(f"unknown command: {cmd}")


def _feature(workspace: Path, state, args: argparse.Namespace) -> tuple[dict, str]:
    sub = args.feature_cmd
    if sub == "start":
        data = feature_cmd.start(workspace, state, args.name)
        return data, f"feature {data['feature']} started ({data['branch']})"
    if sub == "adopt":
        data = feature_cmd.adopt(workspace, state)
        names = ", ".join(item["id"] for item in data["adopted"]) or "(none)"
        return data, f"adopted {data['repo_count']} repos: {names}"
    if sub == "abandon":
        data = feature_cmd.abandon(
            workspace,
            state,
            args.name,
            yes=args.yes,
            remote=args.remote,
            as_json=args.json,
        )
        return data, _abandon_text(data)
    if sub == "close":
        data = feature_cmd.close(
            workspace,
            state,
            args.name,
            yes=args.yes,
            remote=args.remote,
            keep_branch=args.keep_branch,
            as_json=args.json,
        )
        return data, _close_text(data)
    if sub == "switch":
        data = feature_cmd.switch(workspace, state, args.name)
        return data, f"switched to {data['feature']} ({', '.join(data['participants']) or 'no participants'})"
    if sub == "refresh":
        data = feature_cmd.refresh(workspace, state)
        return data, f"refreshed {data['feature']} from origin/develop"
    if sub == "commit":
        data = commit_cmd.commit(
            workspace,
            state,
            plan=args.plan,
            from_file=args.from_file,
            header=args.header,
            header_only=args.header_only,
            include_diff=args.diff,
            as_json=args.json,
        )
        if data.get("printed"):
            return data, "\n"
        return data, _commit_text(data)
    if sub == "push":
        data = feature_cmd.push(workspace, state)
        return data, _push_text(data)
    if sub == "prs":
        data = feature_cmd.prs(workspace, state, use_gh=not args.no_gh)
        return data, _prs_text(data)
    if sub == "approve":
        data = feature_cmd.approve(workspace, state, args.name, force=args.force)
        return data, _approve_text(data)
    if sub == "show":
        data = feature_cmd.show(workspace, state, args.name)
        return data, _feature_show_text(data)
    raise GitConvoyError(f"unknown feature command: {sub}")


def _train(workspace: Path, state, args: argparse.Namespace) -> tuple[dict, str]:
    sub = args.train_cmd
    if sub == "cut":
        repos = [item.strip() for item in args.repos.split(",") if item.strip()] if args.repos else None
        data = train_cmd.cut(
            workspace,
            state,
            args.name,
            bump=args.bump,
            repo_ids=repos,
            no_bump=args.no_bump,
        )
        return data, _cut_train_text(data)
    if sub == "tag-rc":
        data = train_cmd.tag_rc(workspace, state, push=not args.no_push)
        return data, f"tagged rc for {data['train']}"
    if sub == "publish":
        data = train_cmd.publish(workspace, state, push=not args.no_push)
        return data, f"published {data['train']}: {', '.join(item['tag'] for item in data['repos'])}"
    if sub == "show":
        data = train_cmd.show(state, args.name)
        return data, _train_show_text(data)
    if sub == "delete":
        data = train_cmd.delete(
            workspace,
            state,
            args.name,
            yes=args.yes,
            remote=args.remote,
            as_json=args.json,
        )
        return data, _delete_train_text(data)
    if sub == "verify":
        stable = True if args.stable else False if args.rc else None
        data = train_cmd.verify(
            workspace,
            state,
            args.name,
            wait=args.wait,
            timeout_sec=args.timeout * 60,
            poll_sec=args.poll,
            stable=stable,
        )
        return data, train_cmd.format_verify_text(data)
    raise GitConvoyError(f"unknown train command: {sub}")


def _adopt(workspace: Path, state, args: argparse.Namespace) -> tuple[dict, str]:
    sub = args.adopt_cmd
    production = getattr(args, "production", False)
    if production and sub == "take":
        raise GitConvoyError(
            "adopt --production promotes the current BOM; omit take / --train / --from / --to"
        )
    if sub == "production" or (sub is None and production):
        if any(
            getattr(args, name, None)
            for name in ("train", "from_version", "to_version")
        ):
            raise GitConvoyError(
                "adopt --production promotes the current BOM; omit --train, --from, and --to"
            )
        data = adopt_cmd.promote(
            workspace,
            state,
            bom=args.bom,
            require_verify=args.require_verify,
            no_verify=args.no_verify,
        )
        mode = data.get("mode") or "take"
        return data, _adopt_text(data, production=True)
    if sub in (None, "take"):
        data = adopt_cmd.take(
            workspace,
            state,
            bom=args.bom,
            train=args.train,
            from_version=args.from_version,
            to_version=args.to_version,
            description=args.description,
            require_verify=args.require_verify,
            no_verify=args.no_verify,
        )
        return data, _adopt_text(data)
    if sub == "draft":
        data = adopt_cmd.draft(
            workspace,
            state,
            args.from_version,
            args.to_version,
            bom=args.bom,
            train=args.train,
            description=args.description,
        )
        return data, f"drafted {data['version']} from {data['from']}"
    if sub == "pin":
        data = adopt_cmd.pin(
            workspace,
            args.version,
            args.package,
            args.pin,
            bom=args.bom,
            ecosystem=args.ecosystem,
        )
        return data, f"pinned {data['package']}={data['pin']}"
    if sub == "point":
        data = adopt_cmd.point(
            workspace,
            args.version,
            bom=args.bom,
            production=args.production,
        )
        stage = "production" if data["production_enabled"] else "staging only"
        return data, f"deploy_targets bom={data['bom']} ({stage})"
    raise GitConvoyError(f"unknown adopt command: {sub}")


def _add_take_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bom", help="Path to *-bom repo")
    parser.add_argument("--train", help="Train to pin (default: current)")
    parser.add_argument(
        "--from",
        dest="from_version",
        help="System version to copy (default: bom: in deploy_targets.yml)",
    )
    parser.add_argument(
        "--to",
        dest="to_version",
        help="New system version (default: patch bump of --from)",
    )
    parser.add_argument("--description")
    verify = parser.add_mutually_exclusive_group()
    verify.add_argument(
        "--require-verify",
        action="store_true",
        help="Refuse adopt when any publish workflow failed (strict)",
    )
    verify.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip train verify; use local workflow heuristic only",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="git convoy",
        description="Keep a convoy of git repositories together through features, trains, and BOM adoption.",
    )
    parser.add_argument("--workspace", help="Workspace root (default: discover)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Create local state, gitignore, and Cursor skill")
    sub.add_parser("status", help="Current feature, train, and dirty repos")

    feature = sub.add_parser("feature", help="Feature sheet commands")
    fsub = feature.add_subparsers(dest="feature_cmd", required=True)
    start = fsub.add_parser("start", help="Create the feature sheet; checkout develop")
    start.add_argument("name")
    fsub.add_parser("adopt", help="Move local changes onto feature/<name>")
    abandon = fsub.add_parser(
        "abandon",
        help="Delete local feature/<name> branches (discards that work)",
    )
    abandon.add_argument("name", nargs="?")
    abandon.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt",
    )
    abandon.add_argument(
        "--remote",
        action="store_true",
        help="Also delete origin/feature/<name>",
    )
    close = fsub.add_parser(
        "close",
        help="After all PRs merge: checkout develop and remove feature branches",
    )
    close.add_argument("name", nargs="?")
    close.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt",
    )
    close.add_argument(
        "--remote",
        action="store_true",
        help="Also delete origin/feature/<name>",
    )
    close.add_argument(
        "--keep-branch",
        action="store_true",
        help="Keep local feature/<name> branches",
    )
    commit = fsub.add_parser("commit", help="Commit dirty participant repos")
    commit.add_argument(
        "--plan",
        action="store_true",
        help="Print the commit plan; do not commit",
    )
    commit.add_argument(
        "--from",
        dest="from_file",
        help="Apply a filled plan (JSON file, or - for stdin)",
    )
    commit.add_argument("--header", help="Commit subject (required with --header-only)")
    commit.add_argument(
        "--header-only",
        action="store_true",
        help="Commit every dirty participant with only --header",
    )
    commit.add_argument(
        "--diff",
        action="store_true",
        help="Include full patches in the plan",
    )
    switch = fsub.add_parser("switch", help="Checkout a feature's participant repos")
    switch.add_argument("name")
    fsub.add_parser("refresh", help="Merge origin/develop into participant branches")
    fsub.add_parser(
        "push",
        help="Push feature/<name> to origin (no PRs)",
    )
    prs = fsub.add_parser("prs", help="Push branches and open PRs (gh if available)")
    prs.add_argument("--no-gh", action="store_true", help="Only print compare URLs")
    approve = fsub.add_parser(
        "approve",
        help="Approve sibling PRs via gh (Full mode)",
    )
    approve.add_argument("name", nargs="?")
    approve.add_argument(
        "--force",
        action="store_true",
        help="Approve even when CI checks are failing or pending",
    )
    show = fsub.add_parser("show", help="Print the feature sheet")
    show.add_argument("name", nargs="?")

    train = sub.add_parser("train", help="Release train commands")
    tsub = train.add_subparsers(dest="train_cmd", required=True)
    cut = tsub.add_parser("cut", help="Create release/<train> on changed repos")
    cut.add_argument("name")
    cut.add_argument("--bump", choices=("patch", "minor", "major"), default="patch")
    cut.add_argument("--no-bump", action="store_true")
    cut.add_argument("--repos", help="Comma-separated repo ids (skip discovery)")
    tag = tsub.add_parser("tag-rc", help="Tag vX.Y.Z-rc.N and optionally push")
    tag.add_argument("--no-push", action="store_true")
    pub = tsub.add_parser("publish", help="Drop rc, merge main, tag stable")
    pub.add_argument("--no-push", action="store_true")
    tshow = tsub.add_parser("show", help="Print the train sheet")
    tshow.add_argument("name", nargs="?")
    tdelete = tsub.add_parser(
        "delete",
        help="Delete release/<train> branches and remove the train sheet",
    )
    tdelete.add_argument("name", nargs="?")
    tdelete.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt",
    )
    tdelete.add_argument(
        "--remote",
        action="store_true",
        help="Also delete origin/release/<train>",
    )
    verify = tsub.add_parser(
        "verify",
        help="Check publish workflow status via gh (Full mode)",
    )
    verify.add_argument("name", nargs="?")
    verify.add_argument(
        "--wait",
        action="store_true",
        help="Poll until all workflows succeed or timeout",
    )
    verify.add_argument(
        "--timeout",
        type=int,
        default=30,
        metavar="MIN",
        help="Max wait time in minutes (default: 30)",
    )
    verify.add_argument(
        "--poll",
        type=int,
        default=30,
        metavar="SEC",
        help="Seconds between polls when using --wait (default: 30)",
    )
    verify.add_argument(
        "--rc",
        action="store_true",
        help="Verify rc tags even when train is published",
    )
    verify.add_argument(
        "--stable",
        action="store_true",
        help="Verify stable tags even when train is still stabilizing",
    )

    adopt = sub.add_parser(
        "adopt",
        help="Write a release BOM from the current train, or promote it to production",
    )
    _add_take_flags(adopt)
    adopt.add_argument(
        "--production",
        action="store_true",
        help="Promote the current BOM to production",
    )
    asub = adopt.add_subparsers(dest="adopt_cmd", required=False)
    take = asub.add_parser(
        "take",
        help="Write a release BOM from the current train (staging)",
    )
    _add_take_flags(take)
    production = asub.add_parser(
        "production",
        help="Promote the current BOM to production",
    )
    production.add_argument("--bom", help="Path to *-bom repo")
    draft = asub.add_parser("draft", help="Copy last version object to a new draft")
    draft.add_argument("--from", dest="from_version", required=True)
    draft.add_argument("--to", dest="to_version", required=True)
    draft.add_argument("--bom", help="Path to *-bom repo")
    draft.add_argument("--train")
    draft.add_argument("--description")
    pin = asub.add_parser("pin", help="Set one package pin on a draft")
    pin.add_argument("version")
    pin.add_argument("package")
    pin.add_argument("pin")
    pin.add_argument("--bom")
    pin.add_argument("--ecosystem", choices=("python", "npm"))
    point = asub.add_parser("point", help="Point deploy_targets.yml at a version")
    point.add_argument("version")
    point.add_argument("--bom")
    point.add_argument(
        "--production",
        action="store_true",
        help="Enable production (default: staging only)",
    )
    return parser


def _init_text(data: dict) -> str:
    lines = [
        f"workspace: {data['workspace']}",
        f"state:     {data['state']}",
        f"skill:     {data['skill']}",
        f"repos:     {data['repo_count']}",
    ]
    for repo in data["repos"]:
        lines.append(f"  {repo['kind']:10} {repo['id']:20} {repo['path']}")
    return "\n".join(lines)


def _status_text(data: dict) -> str:
    lines = [f"workspace: {data['workspace']}"]
    if data["feature"]:
        feat = data["feature"]
        lines.append(
            f"feature:   {feat['name']}  ({feat['repo_count']} repos)  {feat['branch']}"
        )
        if feat["repos"]:
            lines.append("           " + ", ".join(feat["repos"]))
    else:
        lines.append("feature:   (none)")
    if data["train"]:
        train = data["train"]
        lines.append(
            f"train:     {train['name']}  ({train['repo_count']} repos)  {train['status']}"
        )
    else:
        lines.append("train:     (none)")
    if data["dirty"]:
        lines.append("dirty:     " + ", ".join(data["dirty"]))
    return "\n".join(lines)


def _feature_show_text(data: dict) -> str:
    merged = data.get("merged_count", 0)
    total = data.get("repo_count", 0)
    progress = f"  {merged}/{total} merged" if total else ""
    lines = [
        f"{data['name']}  {data['branch']}  {data['status']}{progress}  {total} repos",
        "merge order: " + " → ".join(data["merge_order"] or ["(empty)"]),
    ]
    for repo in data["repos"]:
        pr = f"  {repo['pr']}" if repo.get("pr") else ""
        status = repo.get("merge_status") or "unknown"
        lines.append(
            f"  {repo['id']:20} {repo['path']:24} {status:8}{pr}"
        )
    return "\n".join(lines)


def _close_text(data: dict) -> str:
    if not data.get("closed"):
        return f"{data['feature']}  not closed"
    feature_branch = data.get("branch") or "feature/<name>"
    lines = [
        f"{data['feature']}  closed  {feature_branch}",
        data.get("note") or "",
    ]
    for repo in data.get("repos") or []:
        checked_out = repo.get("branch") or "develop"
        bits = [f"checked out {checked_out}"]
        if repo.get("deleted_local"):
            bits.append(f"deleted local {feature_branch}")
        if repo.get("deleted_remote"):
            bits.append(f"deleted origin {feature_branch}")
        elif repo.get("on_origin"):
            bits.append(f"{feature_branch} still on origin")
        lines.append(f"  {repo['id']:20}  " + "; ".join(bits))
    return "\n".join(lines)


def _cut_train_text(data: dict) -> str:
    lines = [f"cut train {data['train']} on {len(data.get('repos') or [])} repos"]
    skipped = data.get("skipped") or []
    if skipped:
        lines.append(
            "skipped (no version file): "
            + ", ".join(item["id"] for item in skipped)
        )
    return "\n".join(lines)


def _delete_train_text(data: dict) -> str:
    if not data.get("deleted"):
        return f"{data['train']}  not deleted"
    lines = [
        f"{data['train']}  deleted  {data['branch']}",
        data.get("note") or "",
    ]
    for repo in data.get("repos") or []:
        bits = [f"checked out {repo.get('integration_branch') or repo.get('branch') or 'develop'}"]
        if repo.get("deleted_local"):
            bits.append(f"deleted local {data['branch']}")
        if repo.get("deleted_remote"):
            bits.append("deleted origin")
        if repo.get("on_origin"):
            bits.append(f"{data['branch']} still on origin")
        lines.append(f"  {repo['id']:20}  " + "; ".join(bits))
    return "\n".join(lines)


def _train_show_text(data: dict) -> str:
    lines = [
        f"{data['name']}  {data['branch']}  {data['status']}  {data['repo_count']} repos",
    ]
    for repo in data["repos"]:
        lines.append(
            f"  {repo['id']:20} {repo['from'] or '-'} → {repo['to'] or '-'}  "
            f"{repo['rc_tag'] or ''} {repo['stable_tag'] or ''}"
        )
    return "\n".join(lines)


def _abandon_text(data: dict) -> str:
    if not data.get("abandoned"):
        return f"{data['feature']}  not abandoned"
    lines = [
        f"{data['feature']}  abandoned  {data['branch']}",
        data.get("note") or "",
    ]
    for repo in data.get("repos") or []:
        bits = []
        if repo.get("deleted_local"):
            bits.append("deleted local")
        if repo.get("deleted_remote"):
            bits.append("deleted origin")
        if repo.get("on_origin"):
            bits.append("still on origin")
        if repo.get("discarded_dirty"):
            bits.append("discarded uncommitted")
        lines.append(
            f"  {repo['id']:20} {repo.get('branch') or ''}  "
            + ", ".join(bits)
        )
    return "\n".join(lines)


def _commit_text(data: dict) -> str:
    repos = data.get("repos") or []
    if data.get("mode") == "plan":
        lines = [
            f"{data['feature']}  {data['branch']}  plan  {len(repos)} repos",
        ]
        if data.get("header"):
            lines.append(f"header:    {data['header']}")
        if not repos:
            lines.append("nothing to commit")
        for repo in repos:
            lines.append(f"  {repo['id']:20} {repo.get('stat') or ''}")
        return "\n".join(lines)
    lines = [
        f"{data['feature']}  committed {len(repos)} repos",
    ]
    if data.get("header"):
        lines.append(f"header:    {data['header']}")
    if not repos:
        lines.append("nothing to commit")
    for repo in repos:
        sha = repo.get("sha") or ""
        lines.append(f"  {repo['id']:20} {sha}")
    return "\n".join(lines)


def _push_text(data: dict) -> str:
    repos = data.get("repos") or []
    lines = [
        f"{data['feature']}  pushed {len(repos)} repos  ({data['branch']})",
        data["note"],
    ]
    for repo in repos:
        extra = "  dirty: uncommitted files not pushed" if repo.get("dirty") else ""
        lines.append(f"  {repo['id']:20} origin/{repo.get('branch') or ''}{extra}")
    return "\n".join(lines)


def _prs_text(data: dict) -> str:
    lines = [
        f"{data['feature']} PRs",
        "merge order: " + " → ".join(data["merge_order"]),
        data["note"],
    ]
    for repo in data["repos"]:
        target = repo["pr"] or repo["compare"] or ""
        lines.append(f"  {repo['id']:20} {target}")
    return "\n".join(lines)


def _approve_text(data: dict) -> str:
    lines = [
        f"{data['feature']}  approved {data['approved_count']}/{data['repo_count']} PRs",
        "merge order: " + " → ".join(data["merge_order"]),
        data["note"],
    ]
    for repo in data["repos"]:
        pr = f"  {repo['pr']}" if repo.get("pr") else ""
        extra = ""
        if repo.get("checks"):
            extra = f"  checks={repo['checks']}"
        lines.append(f"  {repo['id']:20} {repo['status']:18}{extra}{pr}")
    return "\n".join(lines)


def _adopt_text(data: dict, *, production: bool = False) -> str:
    mode = data.get("mode") or "draft"
    if production:
        lines = [
            f"production adopt ({mode}): bom={data['point']['bom']}  {data.get('description', '')}",
        ]
    else:
        lines = [
            f"adopted {data['version']} from train {data['train']} ({mode}):",
        ]
    verify = data.get("verify")
    if isinstance(verify, dict) and verify.get("ran"):
        lines.append(
            f"  verify: {verify.get('verified_count', 0)}/{verify.get('repo_count', 0)} "
            f"succeeded, {verify.get('skipped_count', 0)} skipped, "
            f"{verify.get('failed_count', 0)} fallback to git"
        )
    by_repo: dict[str, list[dict]] = {}
    for row in data.get("pins") or []:
        by_repo.setdefault(row.get("id") or "?", []).append(row)
    if not by_repo:
        lines.append("  (no pins changed)")
    for repo_id, rows in by_repo.items():
        lines.append(f"  {repo_id}")
        for row in rows:
            action = row.get("action")
            section = row.get("section") or "?"
            package = row.get("package") or "?"
            pin = row.get("pin") or "?"
            if action == "cleared":
                lines.append(f"    cleared {section} {package}")
                continue
            kind = row.get("kind")
            if kind == "registry":
                label = "registry"
            elif kind == "fallback":
                label = "fallback"
            elif kind == "git":
                label = "git"
            else:
                label = section
            short_pin = pin if pin.startswith("(") else (
                pin[:12] + "…" if len(pin) > 12 and section == "repos" else pin
            )
            lines.append(f"    {label:8} {package}={short_pin}")
    note = (data.get("note") or "").strip()
    if note:
        lines.append(note)
    return "\n".join(lines)


def _verify_text(data: dict) -> str:
    from gitconvoy import train as train_cmd

    return train_cmd.format_verify_text(data)


if __name__ == "__main__":
    sys.exit(main())
