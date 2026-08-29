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
    if sub == "show":
        data = feature_cmd.show(state, args.name)
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
        return data, f"cut train {data['train']} on {len(data['repos'])} repos"
    if sub == "tag-rc":
        data = train_cmd.tag_rc(workspace, state, push=not args.no_push)
        return data, f"tagged rc for {data['train']}"
    if sub == "publish":
        data = train_cmd.publish(workspace, state, push=not args.no_push)
        return data, f"published {data['train']}: {', '.join(item['tag'] for item in data['repos'])}"
    if sub == "show":
        data = train_cmd.show(state, args.name)
        return data, _train_show_text(data)
    raise GitConvoyError(f"unknown train command: {sub}")


def _adopt(workspace: Path, state, args: argparse.Namespace) -> tuple[dict, str]:
    sub = args.adopt_cmd
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

    adopt = sub.add_parser("adopt", help="Draft and point a <name>-bom repo")
    asub = adopt.add_subparsers(dest="adopt_cmd", required=True)
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
    lines = [
        f"{data['name']}  {data['branch']}  {data['status']}  {data['repo_count']} repos",
        "merge order: " + " → ".join(data["merge_order"] or ["(empty)"]),
    ]
    for repo in data["repos"]:
        pr = f"  {repo['pr']}" if repo["pr"] else ""
        lines.append(f"  {repo['id']:20} {repo['path']}{pr}")
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


if __name__ == "__main__":
    sys.exit(main())
