from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gitconvoy import adopt as adopt_cmd
from gitconvoy import ops as ops_cmd
from gitconvoy import ops_release as ops_release_cmd
from gitconvoy import commit as commit_cmd
from gitconvoy import feature as feature_cmd
from gitconvoy import hotfix as hotfix_cmd
from gitconvoy import sync as sync_cmd
from gitconvoy import train as train_cmd
from gitconvoy.errors import GitConvoyError
from gitconvoy.help_text import format_help_text, help_payload
from gitconvoy.initcmd import init
from gitconvoy.output import emit, fail
from gitconvoy.state import load
from gitconvoy.status import status
from gitconvoy.workspace import find_workspace


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    as_json = args.json
    if args.cmd == "help":
        try:
            payload = help_payload(
                topic=getattr(args, "help_topic", None),
                summaries=getattr(args, "summaries", False),
            )
            emit(
                payload,
                as_json,
                format_help_text(
                    topic=getattr(args, "help_topic", None),
                    summaries=getattr(args, "summaries", False),
                ),
            )
        except GitConvoyError as exc:
            return fail(exc.message, as_json)
        return 0
    try:
        workspace = find_workspace(Path(args.workspace) if args.workspace else None)
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
    if cmd == "ops":
        return _ops(workspace, state, args)
    if cmd == "train":
        return _train(workspace, state, args)
    if cmd == "bom":
        return _bom(workspace, state, args)
    if cmd == "hotfix":
        return _hotfix(workspace, state, args)
    if cmd == "sync":
        return _sync(workspace, state, args)
    raise GitConvoyError(f"unknown command: {cmd}")


def _feature(workspace: Path, state, args: argparse.Namespace) -> tuple[dict, str]:
    sub = args.feature_cmd
    if sub == "start":
        data = feature_cmd.start(workspace, state, args.name)
        n = data.get("repo_count") or 0
        if n:
            names = ", ".join(item["id"] for item in data["repos"]) or f"{n} repos"
            return (
                data,
                f"feature {data['feature']} started ({data['branch']}): picked up {names}",
            )
        return data, f"feature {data['feature']} started ({data['branch']})"
    if sub == "adopt":
        data = feature_cmd.adopt(workspace, state)
        names = ", ".join(item["id"] for item in data["adopted"]) or "(none)"
        dropped = ", ".join(item["id"] for item in data.get("dropped") or [])
        text = f"adopted {data['repo_count']} repos: {names}"
        if dropped:
            text += f"; dropped empty {dropped}"
        return data, text
    if sub == "abandon":
        data = feature_cmd.abandon(
            workspace,
            state,
            args.name,
            yes=args.yes,
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


def _ops(workspace: Path, state, args: argparse.Namespace) -> tuple[dict, str]:
    sub = args.ops_cmd
    if sub == "start":
        data = ops_cmd.start(workspace, state, args.name)
        n = data.get("repo_count") or 0
        if n:
            names = ", ".join(item["id"] for item in data["repos"]) or f"{n} repos"
            return (
                data,
                f"ops {data['ops']} started ({data['branch']}): picked up {names}",
            )
        return data, f"ops {data['ops']} started ({data['branch']})"
    if sub == "adopt":
        repos = (
            [item.strip() for item in args.repos.split(",") if item.strip()]
            if args.repos
            else None
        )
        data = ops_cmd.adopt(workspace, state, repo_ids=repos)
        names = ", ".join(item["id"] for item in data["adopted"]) or "(none)"
        dropped = ", ".join(item["id"] for item in data.get("dropped") or [])
        text = f"adopted {data['repo_count']} repos: {names}"
        if dropped:
            text += f"; dropped empty {dropped}"
        return data, text
    if sub == "abandon":
        data = ops_cmd.abandon(
            workspace,
            state,
            args.name,
            yes=args.yes,
            as_json=args.json,
        )
        return data, _abandon_text(data)
    if sub == "close":
        data = ops_cmd.close(
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
        data = ops_cmd.switch(workspace, state, args.name)
        return data, f"switched to {data['ops']} ({', '.join(data['participants']) or 'no participants'})"
    if sub == "refresh":
        data = ops_cmd.refresh(workspace, state)
        return data, f"refreshed {data['ops']} from origin/develop"
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
            kind="ops",
        )
        if data.get("printed"):
            return data, "\n"
        return data, _commit_text(data)
    if sub == "push":
        data = ops_cmd.push(workspace, state)
        return data, _push_text(data)
    if sub == "prs":
        data = ops_cmd.prs(workspace, state, use_gh=not args.no_gh)
        return data, _prs_text(data)
    if sub == "approve":
        data = ops_cmd.approve(workspace, state, args.name, force=args.force)
        return data, _approve_text(data)
    if sub == "promote":
        data = ops_cmd.promote(workspace, state, args.name, use_gh=not args.no_gh)
        return data, _promote_text(data)
    if sub == "release":
        data = ops_release_cmd.release(
            workspace,
            list(args.repos or []),
            bump=args.bump,
            pin=args.pin,
            bom=args.bom,
            verify=args.verify,
            wait=args.wait,
            use_gh=not args.no_gh,
            push=not args.no_push,
        )
        return data, _ops_release_text(data)
    if sub == "show":
        data = ops_cmd.show(workspace, state, args.name)
        return data, _feature_show_text(data)
    raise GitConvoyError(f"unknown ops command: {sub}")



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
    if sub == "adopt":
        repos = (
            [item.strip() for item in args.repos.split(",") if item.strip()]
            if args.repos
            else None
        )
        data = train_cmd.adopt(workspace, state, repo_ids=repos)
        return data, _adopt_train_text(data)
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
            kind="train",
        )
        if data.get("printed"):
            return data, "\n"
        return data, _commit_text(data)
    if sub == "tag-rc":
        data = train_cmd.tag_rc(workspace, state, push=not args.no_push)
        return data, _tag_rc_text(data)
    if sub == "publish":
        data = train_cmd.publish(workspace, state, push=not args.no_push)
        return data, _publish_text(data)
    if sub == "mergeback":
        data = train_cmd.mergeback(
            workspace, state, args.name, push=not args.no_push
        )
        return data, train_cmd.format_mergeback_text(data)
    if sub == "show":
        data = train_cmd.show(state, args.name)
        return data, _train_show_text(data)
    if sub in ("close", "delete"):
        data = train_cmd.close(
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


def _hotfix(workspace: Path, state, args: argparse.Namespace) -> tuple[dict, str]:
    sub = args.hotfix_cmd
    if sub == "start":
        repos = (
            [item.strip() for item in args.repos.split(",") if item.strip()]
            if args.repos
            else None
        )
        data = hotfix_cmd.start(workspace, state, args.name, repo_ids=repos)
        names = ", ".join(item["id"] for item in data["repos"]) or "(none)"
        return data, f"hotfix {data['hotfix']} started ({data['branch']}): {names}"
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
            kind="hotfix",
        )
        if data.get("printed"):
            return data, "\n"
        return data, _commit_text(data)
    if sub == "push":
        data = hotfix_cmd.push(workspace, state)
        return data, _push_text(data)
    if sub == "prs":
        data = hotfix_cmd.prs(workspace, state, use_gh=not args.no_gh)
        return data, _hotfix_prs_text(data)
    if sub == "publish":
        data = hotfix_cmd.publish(workspace, state, push_remote=not args.no_push)
        return data, _hotfix_publish_text(data)
    if sub in ("bom", "adopt"):
        data = hotfix_cmd.bom(
            workspace,
            state,
            bom=args.bom,
            from_version=args.from_version,
            to_version=args.to_version,
            description=args.description,
        )
        pins = ", ".join(
            f"{row['package']}={row['pin']}" for row in data.get("pins") or []
        )
        return data, f"hotfix bom {data['version']}  {pins}"
    if sub == "show":
        data = hotfix_cmd.show(workspace, state, args.name)
        return data, _hotfix_show_text(data)
    if sub == "close":
        data = hotfix_cmd.close(
            workspace,
            state,
            args.name,
            yes=args.yes,
            remote=args.remote,
            keep_branch=args.keep_branch,
            as_json=args.json,
        )
        return data, _close_text(data)
    if sub == "abandon":
        data = hotfix_cmd.abandon(
            workspace,
            state,
            args.name,
            yes=args.yes,
            as_json=args.json,
        )
        return data, _abandon_text(data)
    raise GitConvoyError(f"unknown hotfix command: {sub}")


def _sync(workspace: Path, state, args: argparse.Namespace) -> tuple[dict, str]:
    sub = args.sync_cmd
    if not sub:
        data = sync_cmd.sync_workspace(
            workspace, state, push=not args.no_push
        )
        return data, sync_cmd.format_develop_sync_text(data, label="sync")
    if sub == "develop":
        repos = (
            [item.strip() for item in args.repos.split(",") if item.strip()]
            if getattr(args, "repos", None)
            else None
        )
        data = sync_cmd.sync_product_repos(
            workspace,
            repo_ids=repos,
            push=not args.no_push,
        )
        return data, sync_cmd.format_develop_sync_text(data, label="sync develop")
    raise GitConvoyError(f"unknown sync command: {sub}")


def _bom(workspace: Path, state, args: argparse.Namespace) -> tuple[dict, str]:
    sub = args.bom_cmd
    production = getattr(args, "production", False)
    if production and sub == "take":
        raise GitConvoyError(
            "bom --production promotes the current BOM; omit take / --train / --from / --to"
        )
    if sub == "production" or (sub is None and production):
        if any(
            getattr(args, name, None)
            for name in ("train", "from_version", "to_version")
        ):
            raise GitConvoyError(
                "bom --production promotes the current BOM; omit --train, --from, and --to"
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
    raise GitConvoyError(f"unknown bom command: {sub}")


def _add_take_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bom", help="BOM repo path (default: .gitconvoy/ops.toml [bom], else *-bom)")
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
        help="Refuse writing the BOM when any publish workflow failed (strict)",
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

    sub.add_parser("init", help="Create local state, membership, gitignore, and Cursor skill")
    help_parser = sub.add_parser(
        "help",
        help="Command sequences by topic (reduced README)",
    )
    help_parser.add_argument(
        "help_topic",
        nargs="?",
        help="Topic: all, feature, train, staging, production, ops, hotfix, bom, sync, init, status",
    )
    help_parser.add_argument(
        "-s",
        "--summaries",
        action="store_true",
        help="Print one-line description after each command",
    )
    sub.add_parser("status", help="Current feature, ops, train, hotfix, and dirty repos")

    feature = sub.add_parser("feature", help="Feature sheet commands")
    fsub = feature.add_subparsers(dest="feature_cmd", required=True)
    start = fsub.add_parser(
        "start",
        help="Create the feature sheet; pick up existing feature/<name>; otherwise checkout develop",
    )
    start.add_argument("name")
    fsub.add_parser("adopt", help="Move local changes onto feature/<name>")
    abandon = fsub.add_parser(
        "abandon",
        help="Drop the feature sheet (does not delete branches or files)",
    )
    abandon.add_argument("name", nargs="?")
    abandon.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt",
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

    ops = sub.add_parser("ops", help="Operator tooling sheet commands")
    asub = ops.add_subparsers(dest="ops_cmd", required=True)
    astart = asub.add_parser(
        "start",
        help="Create the ops sheet; pick up existing ops/<name>; otherwise checkout integration",
    )
    astart.add_argument("name")
    aadopt = asub.add_parser(
        "adopt",
        help="Move local ops-repo changes from develop or main onto ops/<name>",
    )
    aadopt.add_argument(
        "--repos",
        help="Comma-separated ops repo ids (force-include even when clean)",
    )
    aabandon = asub.add_parser(
        "abandon",
        help="Drop the ops sheet (does not delete branches or files)",
    )
    aabandon.add_argument("name", nargs="?")
    aabandon.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    aclose = asub.add_parser(
        "close",
        help="After PRs merge into develop: check out develop and remove ops branches",
    )
    aclose.add_argument("name", nargs="?")
    aclose.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    aclose.add_argument(
        "--remote",
        action="store_true",
        help="Also delete origin/ops/<name>",
    )
    aclose.add_argument(
        "--keep-branch",
        action="store_true",
        help="Keep local ops/<name> branches",
    )
    acommit = asub.add_parser("commit", help="Commit dirty ops participant repos")
    acommit.add_argument("--plan", action="store_true", help="Print the commit plan; do not commit")
    acommit.add_argument("--from", dest="from_file", help="Apply a filled plan (JSON file, or - for stdin)")
    acommit.add_argument("--header", help="Commit subject (required with --header-only)")
    acommit.add_argument(
        "--header-only",
        action="store_true",
        help="Commit every dirty participant with only --header",
    )
    acommit.add_argument("--diff", action="store_true", help="Include full patches in the plan")
    aswitch = asub.add_parser("switch", help="Checkout an ops sheet's participant repos")
    aswitch.add_argument("name")
    asub.add_parser("refresh", help="Merge origin/develop into participant ops branches")
    asub.add_parser("push", help="Push ops/<name> to origin (no PRs)")
    aprs = asub.add_parser("prs", help="Push branches and open PRs into develop (gh if available)")
    aprs.add_argument("--no-gh", action="store_true", help="Only print compare URLs")
    aapprove = asub.add_parser("approve", help="Approve sibling PRs via gh (Full mode)")
    aapprove.add_argument("name", nargs="?")
    aapprove.add_argument(
        "--force",
        action="store_true",
        help="Approve even when CI checks are failing or pending",
    )
    apromote = asub.add_parser(
        "promote",
        help="Sheet-scoped: open develop→main PRs when develop is ahead (no bump/tag)",
    )
    apromote.add_argument("name", nargs="?")
    apromote.add_argument("--no-gh", action="store_true", help="Only print compare URLs")
    arelease = asub.add_parser(
        "release",
        help="Per-repo platform release: bump, PR develop→main, tag, optional verify/pin",
    )
    arelease.add_argument(
        "repos",
        nargs="+",
        help="Ops repo ids (no sheet required)",
    )
    arelease.add_argument(
        "--bump",
        choices=("patch", "minor", "major"),
        default="patch",
        help="Semver part to bump when develop still matches the last v* tag",
    )
    arelease.add_argument(
        "--pin",
        nargs="?",
        const="tag",
        choices=("tag", "sha"),
        help="Update deploy_targets.yml helper.ref (tag first; omit value for tag, or --pin sha)",
    )
    arelease.add_argument("--bom", help="BOM repo path for --pin (default: workspace BOM)")
    arelease.add_argument(
        "--verify",
        action="store_true",
        help="After tagging, check v* publish workflows (Full mode)",
    )
    arelease.add_argument(
        "--wait",
        action="store_true",
        help="With --verify, poll until publish workflows finish",
    )
    arelease.add_argument("--no-gh", action="store_true", help="Only print compare URLs")
    arelease.add_argument(
        "--no-push",
        action="store_true",
        help="Do not push develop, main, or tags",
    )
    ashow = asub.add_parser("show", help="Print the ops sheet")
    ashow.add_argument("name", nargs="?")

    train = sub.add_parser("train", help="Release train commands")
    tsub = train.add_subparsers(dest="train_cmd", required=True)
    cut = tsub.add_parser("cut", help="Create release/<train> on changed repos")
    cut.add_argument("name")
    cut.add_argument("--bump", choices=("patch", "minor", "major"), default="patch")
    cut.add_argument("--no-bump", action="store_true")
    cut.add_argument("--repos", help="Comma-separated repo ids (skip discovery)")
    tadopt = tsub.add_parser(
        "adopt",
        help="Add dirty product repos (or --repos) to the current train; no version bump",
    )
    tadopt.add_argument(
        "--repos",
        help="Comma-separated product repo ids (force-include even when clean)",
    )
    tcommit = tsub.add_parser("commit", help="Commit dirty train participant repos")
    tcommit.add_argument("--plan", action="store_true", help="Print the commit plan; do not commit")
    tcommit.add_argument("--from", dest="from_file", help="Apply a filled plan (JSON file, or - for stdin)")
    tcommit.add_argument("--header", help="Commit subject (required with --header-only)")
    tcommit.add_argument(
        "--header-only",
        action="store_true",
        help="Commit every dirty participant with only --header",
    )
    tcommit.add_argument("--diff", action="store_true", help="Include full patches in the plan")
    tag = tsub.add_parser("tag-rc", help="Tag vX.Y.Z-rc.N and optionally push")
    tag.add_argument("--no-push", action="store_true")
    pub = tsub.add_parser(
        "publish",
        help="Drop rc, merge main, tag stable, then mergeback into develop",
    )
    pub.add_argument("--no-push", action="store_true")
    mergeback = tsub.add_parser(
        "mergeback",
        help="Merge tagged main into develop (retryable; also run by train publish)",
    )
    mergeback.add_argument("name", nargs="?")
    mergeback.add_argument("--no-push", action="store_true")
    tshow = tsub.add_parser("show", help="Print the train sheet")
    tshow.add_argument("name", nargs="?")
    tclose = tsub.add_parser(
        "close",
        help="After the release is merged: checkout develop, delete release/<train>, drop the sheet",
    )
    tclose.add_argument("name", nargs="?")
    tclose.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt",
    )
    tclose.add_argument(
        "--remote",
        action="store_true",
        help="Also delete origin/release/<train>",
    )
    tdelete = tsub.add_parser(
        "delete",
        help=argparse.SUPPRESS,
    )
    tdelete.add_argument("name", nargs="?")
    tdelete.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)
    tdelete.add_argument("--remote", action="store_true", help=argparse.SUPPRESS)
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

    bom = sub.add_parser(
        "bom",
        help="Write a release BOM from the current train, or promote it to production",
    )
    _add_take_flags(bom)
    bom.add_argument(
        "--production",
        action="store_true",
        help="Promote the current BOM to production",
    )
    bsub = bom.add_subparsers(dest="bom_cmd", required=False)
    take = bsub.add_parser(
        "take",
        help="Write a release BOM from the current train (staging)",
    )
    _add_take_flags(take)
    production = bsub.add_parser(
        "production",
        help="Promote the current BOM to production",
    )
    production.add_argument("--bom", help="BOM repo path (override ops.toml)")
    draft = bsub.add_parser("draft", help="Copy last version object to a new draft")
    draft.add_argument("--from", dest="from_version", required=True)
    draft.add_argument("--to", dest="to_version", required=True)
    draft.add_argument("--bom", help="BOM repo path (override ops.toml)")
    draft.add_argument("--train")
    draft.add_argument("--description")
    pin = bsub.add_parser("pin", help="Set one package pin on a draft")
    pin.add_argument("version")
    pin.add_argument("package")
    pin.add_argument("pin")
    pin.add_argument("--bom")
    pin.add_argument("--ecosystem", choices=("python", "npm"))
    point = bsub.add_parser("point", help="Point deploy_targets.yml at a version")
    point.add_argument("version")
    point.add_argument("--bom")
    point.add_argument(
        "--production",
        action="store_true",
        help="Enable production (default: staging only)",
    )

    hotfix = sub.add_parser(
        "hotfix",
        help="Production PATCH: branch from main, tag, merge back to develop",
    )
    hsub = hotfix.add_subparsers(dest="hotfix_cmd", required=True)
    hstart = hsub.add_parser(
        "start",
        help="Branch hotfix/<name> from main, or pick up an existing one; bump PATCH unless already bumped",
    )
    hstart.add_argument("name")
    hstart.add_argument("--repos", help="Comma-separated repo ids (skip dirty discovery)")
    hcommit = hsub.add_parser("commit", help="Commit dirty hotfix participants")
    hcommit.add_argument("--plan", action="store_true")
    hcommit.add_argument("--from", dest="from_file")
    hcommit.add_argument("--header")
    hcommit.add_argument("--header-only", action="store_true")
    hcommit.add_argument("--diff", action="store_true")
    hsub.add_parser("push", help="Push hotfix/<name> to origin (no PRs)")
    hprs = hsub.add_parser("prs", help="Push and open PRs into main (gh if available)")
    hprs.add_argument("--no-gh", action="store_true")
    hpub = hsub.add_parser(
        "publish",
        help="Tag vX.Y.Z on main, merge into develop, absorb local feature/* branches",
    )
    hpub.add_argument("--no-push", action="store_true")
    hbom = hsub.add_parser(
        "bom",
        help="Draft next BOM, pin only hotfix packages, staging only",
    )
    hbom.add_argument("--bom", help="BOM repo path (override ops.toml)")
    hbom.add_argument("--from", dest="from_version")
    hbom.add_argument("--to", dest="to_version")
    hbom.add_argument("--description")
    hadopt = hsub.add_parser(
        "adopt",
        help=argparse.SUPPRESS,
    )
    hadopt.add_argument("--bom", help=argparse.SUPPRESS)
    hadopt.add_argument("--from", dest="from_version")
    hadopt.add_argument("--to", dest="to_version")
    hadopt.add_argument("--description")
    hshow = hsub.add_parser("show", help="Print the hotfix sheet")
    hshow.add_argument("name", nargs="?")
    hclose = hsub.add_parser(
        "close",
        help="After the patch is in develop: checkout develop, delete the hotfix branch, drop the sheet",
    )
    hclose.add_argument("name", nargs="?")
    hclose.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    hclose.add_argument(
        "--remote",
        action="store_true",
        help="Also delete origin/hotfix/<name>",
    )
    hclose.add_argument(
        "--keep-branch",
        action="store_true",
        help="Keep local hotfix/<name> branches",
    )
    habandon = hsub.add_parser(
        "abandon",
        help="Drop the hotfix sheet (does not delete branches or files)",
    )
    habandon.add_argument("name", nargs="?")
    habandon.add_argument("--yes", action="store_true")

    sync = sub.add_parser(
        "sync",
        help=(
            "Bring latest commits into every clone "
            "(or sync develop to merge stable/main only)"
        ),
    )
    sync.add_argument("--no-push", action="store_true")
    ssub = sync.add_subparsers(dest="sync_cmd", required=False)
    develop = ssub.add_parser(
        "develop",
        help="Merge latest stable tag (or main) into develop for product repos",
    )
    develop.add_argument(
        "--repos",
        help="Comma-separated repo ids (default: all product repos)",
    )
    develop.add_argument("--no-push", action="store_true")

    return parser


def _init_text(data: dict) -> str:
    lines = [
        f"workspace: {data['workspace']}",
        f"state:     {data['state']}",
        f"skill:     {data['skill']}",
        f"repos:     {data['repo_count']}",
    ]
    if data.get("membership"):
        lines.append(f"membership:{data['membership']}")
        ops_ids = ", ".join(data.get("ops") or []) or "(none)"
        bom = ", ".join(data.get("bom") or []) or "(none)"
        lines.append(f"ops:       {ops_ids}")
        lines.append(f"bom:       {bom}")
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
    if data.get("ops"):
        item = data["ops"]
        lines.append(
            f"ops:       {item['name']}  ({item['repo_count']} repos)  {item['branch']}"
        )
        if item["repos"]:
            lines.append("           " + ", ".join(item["repos"]))
    else:
        lines.append("ops:       (none)")
    if data["train"]:
        train = data["train"]
        lines.append(
            f"train:     {train['name']}  ({train['repo_count']} repos)  {train['status']}"
        )
    else:
        lines.append("train:     (none)")
    if data.get("hotfix"):
        item = data["hotfix"]
        bits = [
            item["name"],
            f"({item['repo_count']} repos)",
            item.get("status") or "",
        ]
        if item.get("status") == "published":
            tags = " ".join(item.get("stable_tags") or [])
            if tags:
                bits.append(tags)
            if item.get("in_develop"):
                bits.append("in develop")
            else:
                missing = ", ".join(item.get("develop_missing") or [])
                bits.append(
                    "not in develop" + (f": {missing}" if missing else "")
                )
        else:
            bits.append(item["branch"])
        lines.append("hotfix:    " + "  ".join(bit for bit in bits if bit))
    else:
        lines.append("hotfix:    (none)")
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
            f"  {repo['id']:20} {repo['path']:24} {status:12}{pr}"
        )
    note = (data.get("note") or "").strip()
    if note:
        lines.append(note)
    return "\n".join(lines)


def _close_text(data: dict) -> str:
    name = _sheet_name(data)
    if not data.get("closed"):
        return f"{name}  not closed"
    branch = data.get("branch") or "feature/<name>"
    lines = [
        f"{name}  closed  {branch}",
        data.get("note") or "",
    ]
    for repo in data.get("repos") or []:
        checked_out = repo.get("branch") or "develop"
        bits = [f"checked out {checked_out}"]
        if repo.get("deleted_local"):
            bits.append(f"deleted local {branch}")
        if repo.get("deleted_remote"):
            bits.append(f"deleted origin {branch}")
        elif repo.get("on_origin"):
            bits.append(f"{branch} still on origin")
        lines.append(f"  {repo['id']:20}  " + "; ".join(bits))
    return "\n".join(lines)


def _tag_rc_text(data: dict) -> str:
    lines = [f"tagged rc for {data['train']}"]
    sync = data.get("develop_sync") or {}
    failed = sync.get("failed") or []
    if failed:
        lines.append("develop sync failed in: " + ", ".join(failed))
        note = data.get("note") or sync.get("note")
        if note:
            lines.append(note)
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


def _adopt_train_text(data: dict) -> str:
    names = ", ".join(item["id"] for item in data.get("adopted") or []) or "(none)"
    lines = [
        f"adopted {data.get('repo_count') or 0} repos onto train {data['train']}: {names}"
    ]
    note = data.get("note")
    if note:
        lines.append(note)
    return "\n".join(lines)


def _publish_text(data: dict) -> str:
    tags = ", ".join(item["tag"] for item in data.get("repos") or [])
    lines = [f"published {data['train']}: {tags}"]
    mb = data.get("mergeback") or {}
    failed = mb.get("failed") or []
    if failed:
        lines.append("mergeback failed in: " + ", ".join(failed))
        lines.append(
            data.get("note")
            or "stable tags are on main; re-run: git convoy train mergeback"
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


def _sheet_name(data: dict) -> str:
    return (
        data.get("feature")
        or data.get("hotfix")
        or data.get("ops")
        or data.get("train")
        or "?"
    )


def _ops_release_text(data: dict) -> str:
    lines = [f"ops release  {len(data.get('repos') or [])} repos"]
    note = (data.get("note") or "").strip()
    if note:
        lines.append(note)
    for repo in data.get("repos") or []:
        status = repo.get("status") or "?"
        extra = repo.get("error") or repo.get("pr") or repo.get("compare") or ""
        tag = repo.get("tag") or ""
        ver = repo.get("to") or ""
        bits = [status]
        if ver:
            bits.append(ver)
        if tag:
            bits.append(tag)
        if extra:
            bits.append(str(extra))
        lines.append(f"  {repo.get('id', '?'):20} " + "  ".join(bits))
        pin = repo.get("pin")
        if pin:
            lines.append(
                f"    pin {pin.get('status')} {pin.get('kind') or ''} "
                f"{pin.get('ref') or pin.get('reason') or ''}"
            )
        verify = repo.get("verify")
        if verify:
            lines.append(
                f"    verify {verify.get('status')} {verify.get('detail') or ''}"
            )
    return "\n".join(lines)


def _promote_text(data: dict) -> str:
    lines = [f"{data.get('ops') or '?'}  promote  {len(data.get('repos') or [])} repos"]
    note = (data.get("note") or "").strip()
    if note:
        lines.append(note)
    for repo in data.get("repos") or []:
        if repo.get("skipped"):
            lines.append(f"  {repo['id']:20} skipped ({repo['skipped']})")
            continue
        url = repo.get("pr") or repo.get("compare") or ""
        lines.append(f"  {repo['id']:20} {url}")
    return "\n".join(lines)

def _abandon_text(data: dict) -> str:
    name = _sheet_name(data)
    if not data.get("abandoned"):
        return f"{name}  not abandoned"
    lines = [
        f"{name}  abandoned  {data['branch']}",
        data.get("note") or "",
    ]
    for repo in data.get("repos") or []:
        bits = []
        if repo.get("dirty"):
            bits.append("dirty")
        if repo.get("kept_local_branch"):
            bits.append("branch kept")
        lines.append(
            f"  {repo['id']:20} {repo.get('branch') or ''}  "
            + ", ".join(bits)
        )
    return "\n".join(lines)


def _commit_text(data: dict) -> str:
    repos = data.get("repos") or []
    name = _sheet_name(data)
    if data.get("mode") == "plan":
        lines = [
            f"{name}  {data['branch']}  plan  {len(repos)} repos",
        ]
        if data.get("header"):
            lines.append(f"header:    {data['header']}")
        if not repos:
            lines.append("nothing to commit")
        for repo in repos:
            lines.append(f"  {repo['id']:20} {repo.get('stat') or ''}")
        return "\n".join(lines)
    lines = [
        f"{name}  committed {len(repos)} repos",
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
        f"{_sheet_name(data)}  pushed {len(repos)} repos  ({data['branch']})",
        data["note"],
    ]
    for repo in repos:
        extra = "  dirty: uncommitted files not pushed" if repo.get("dirty") else ""
        lines.append(f"  {repo['id']:20} origin/{repo.get('branch') or ''}{extra}")
    return "\n".join(lines)


def _hotfix_prs_text(data: dict) -> str:
    lines = [
        f"{data['hotfix']} PRs → main",
        "merge order: " + " → ".join(data["merge_order"]),
        data["note"],
    ]
    for repo in data["repos"]:
        target = repo["pr"] or repo["compare"] or ""
        lines.append(f"  {repo['id']:20} {target}")
    return "\n".join(lines)


def _hotfix_publish_text(data: dict) -> str:
    tags = ", ".join(item.get("tag") or "" for item in data.get("repos") or [])
    lines = [f"published hotfix {data['hotfix']}: {tags}"]
    for repo in data.get("repos") or []:
        develop = (repo.get("develop") or {}).get("status") or ""
        lines.append(f"  {repo['id']:20} {repo.get('tag') or ''}  develop={develop}")
        for item in repo.get("feature_branches") or []:
            flag = "ok" if item.get("ok") else "failed"
            lines.append(f"    {item['branch']:18} {flag}  {item.get('status') or ''}")
    if data.get("note"):
        lines.append(data["note"])
    return "\n".join(lines)


def _hotfix_show_text(data: dict) -> str:
    lines = [
        f"{data['name']}  {data['branch']}  {data['status']}  {data['repo_count']} repos",
        "merge order: " + " → ".join(data["merge_order"] or ["(empty)"]),
    ]
    for repo in data["repos"]:
        pr = f"  {repo['pr']}" if repo.get("pr") else ""
        lines.append(
            f"  {repo['id']:20} {repo.get('from') or ''} → {repo.get('to') or ''}  "
            f"{repo.get('merge_status') or ''}  "
            f"{'in develop' if repo.get('in_develop') else 'not in develop'}{pr}"
        )
    return "\n".join(lines)


def _prs_text(data: dict) -> str:
    lines = [
        f"{_sheet_name(data)} PRs",
        "merge order: " + " → ".join(data["merge_order"]),
        data["note"],
    ]
    synced = {
        row["id"]: row.get("main") or {}
        for row in data.get("ensure_develop") or []
        if row.get("id")
    }
    for repo in data["repos"]:
        target = repo["pr"] or repo["compare"] or ""
        extra = ""
        main = synced.get(repo["id"]) or {}
        moved = main.get("moved") or []
        if main.get("action") == "absorbed" and moved:
            extra = f"  absorbed {len(moved)} from local main"
        lines.append(f"  {repo['id']:20} {target}{extra}")
    return "\n".join(lines)


def _approve_text(data: dict) -> str:
    lines = [
        f"{_sheet_name(data)}  approved {data['approved_count']}/{data['repo_count']} PRs",
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
            f"adopted {data['version']} from train {data['train']} ({mode})",
        ]
    publish_ci = _format_publish_ci(data.get("verify"))
    if publish_ci:
        lines.append(publish_ci)
    files = data.get("files") or []
    if files:
        lines.append("  wrote:")
        for row in files:
            path = row.get("path") or "?"
            lines.append(f"    {path}")
            for section in ("python", "npm", "repos"):
                pins = row.get(section)
                if not isinstance(pins, dict) or not pins:
                    continue
                rendered = ", ".join(
                    f"{name}={value}" for name, value in pins.items() if value not in (None, "")
                )
                if rendered:
                    lines.append(f"      {section}: {rendered}")
    else:
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


def _format_publish_ci(verify: object) -> str | None:
    if not isinstance(verify, dict) or not verify.get("ran"):
        return None
    total = verify.get("repo_count", 0)
    succeeded = [str(item) for item in (verify.get("succeeded") or []) if item]
    pending = [str(item) for item in (verify.get("pending") or []) if item]
    skipped = [str(item) for item in (verify.get("skipped") or []) if item]
    failed = [str(item) for item in (verify.get("failed") or []) if item]
    succeeded_n = len(succeeded) or int(verify.get("verified_count") or 0)
    parts: list[str] = [f"{succeeded_n}/{total} succeeded"]
    if succeeded:
        parts[0] += f" ({', '.join(succeeded)})"
    if pending:
        parts.append(f"pending: {', '.join(pending)}")
    elif int(verify.get("pending_count") or 0):
        parts.append(f"{verify.get('pending_count')} pending")
    if skipped:
        parts.append(f"skipped: {', '.join(skipped)}")
    elif int(verify.get("skipped_count") or 0):
        parts.append(f"{verify.get('skipped_count')} skipped")
    if failed:
        parts.append(f"failed, pinned git SHA: {', '.join(failed)}")
    elif int(verify.get("failed_count") or 0):
        parts.append(f"{verify.get('failed_count')} fallback to git")
    return "  publish CI: " + "; ".join(parts)


def _verify_text(data: dict) -> str:
    from gitconvoy import train as train_cmd

    return train_cmd.format_verify_text(data)


if __name__ == "__main__":
    sys.exit(main())
