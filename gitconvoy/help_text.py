from __future__ import annotations

from typing import TypedDict


class HelpSection(TypedDict):
    name: str
    commands: list[str]


HELP_SECTIONS: list[HelpSection] = [
    {
        "name": "One-time setup",
        "commands": [
            "git convoy init",
        ],
    },
    {
        "name": "Any time",
        "commands": [
            "git convoy status",
            "git convoy sync develop",
            "git convoy sync develop --repos renglo-lib,console",
        ],
    },
    {
        "name": "Start of session (idle workspace)",
        "commands": [
            "git convoy sync",
        ],
    },
    {
        "name": "Cycle 1 — Feature",
        "commands": [
            "git convoy feature start NAME",
            "git convoy feature adopt",
            "git convoy feature commit --header \"feat: …\" --header-only",
            "git convoy feature prs",
            "git convoy feature approve",
            "git convoy feature show",
            "git convoy feature close --yes",
        ],
    },
    {
        "name": "Cycle 1 — Feature (optional)",
        "commands": [
            "git convoy feature push",
            "git convoy feature prs --no-gh",
            "git convoy feature refresh",
            "git convoy feature switch NAME",
            "git convoy feature abandon --yes",
        ],
    },
    {
        "name": "Cycle 2 — Release train (local)",
        "commands": [
            "git convoy train cut NAME",
            "git convoy train commit --header \"fix: …\" --header-only",
            "git convoy train adopt",
            "git convoy train show",
            "git convoy train delete --yes",
        ],
    },
    {
        "name": "Cycle 3 — Staging adoption",
        "commands": [
            "git convoy train tag-rc",
            "git convoy train verify",
            "git convoy train verify --wait",
            "git convoy bom --bom ops/<system>-bom",
            "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Adopt release train (staging)\" && git push",
        ],
    },
    {
        "name": "Cycle 4 — Production release",
        "commands": [
            "git convoy train publish",
            "git convoy train verify --wait",
            "git convoy train mergeback",
            "git convoy bom --production --bom ops/<system>-bom",
            "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Adopt production train\" && git push",
            "git convoy train delete --yes",
        ],
    },
    {
        "name": "Aux — Platform tooling",
        "commands": [
            "git convoy aux start NAME",
            "git convoy aux adopt",
            "git convoy aux commit --header \"fix: …\" --header-only",
            "git convoy aux prs",
            "git convoy aux show",
            "git convoy aux close --yes",
        ],
    },
    {
        "name": "Aux — Platform tooling (optional)",
        "commands": [
            "git convoy aux adopt --repos bom-helper,git-convoy",
            "git convoy aux push",
            "git convoy aux prs --no-gh",
            "git convoy aux approve",
            "git convoy aux refresh",
            "git convoy aux switch NAME",
            "git convoy aux promote",
            "git convoy aux abandon --yes",
        ],
    },
    {
        "name": "Hotfix — Production emergency",
        "commands": [
            "git convoy hotfix start NAME",
            "git convoy hotfix commit --header \"fix: …\" --header-only",
            "git convoy hotfix prs",
            "git convoy hotfix publish",
            "git convoy hotfix adopt --bom ops/<system>-bom",
            "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Hotfix (staging)\" && git push",
        ],
    },
    {
        "name": "Hotfix — Production emergency (optional)",
        "commands": [
            "git convoy hotfix push",
            "git convoy hotfix prs --no-gh",
            "git convoy hotfix show",
            "git convoy hotfix abandon --yes",
        ],
    },
    {
        "name": "BOM — Manual primitives",
        "commands": [
            "git convoy bom --require-verify --bom ops/<system>-bom",
            "git convoy bom --no-verify --bom ops/<system>-bom",
            "git convoy bom draft --from 1.4.0 --to 1.4.1 --bom ops/<system>-bom",
            "git convoy bom pin 1.4.1 renglo-lib 1.2.5 --bom ops/<system>-bom",
            "git convoy bom point 1.4.1 --bom ops/<system>-bom",
        ],
    },
    {
        "name": "Train — Git-only (stay in cycle 2)",
        "commands": [
            "git convoy train tag-rc --no-push",
            "git convoy train publish --no-push",
        ],
    },
    {
        "name": "Agents",
        "commands": [
            "git convoy --json status",
            "git convoy --json feature commit",
            "git convoy --json feature commit --from -",
        ],
    },
]


def help_payload() -> dict:
    return {
        "ok": True,
        "sections": HELP_SECTIONS,
    }


def format_help_text() -> str:
    lines = ["git convoy — command sequences", ""]
    for section in HELP_SECTIONS:
        lines.append(section["name"])
        for cmd in section["commands"]:
            lines.append(f"  {cmd}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
