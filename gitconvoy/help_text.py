from __future__ import annotations

from typing import NotRequired, TypedDict

from gitconvoy.errors import GitConvoyError


class HelpCommand(TypedDict):
    cmd: str
    summary: str


class HelpSection(TypedDict):
    name: str
    commands: list[HelpCommand]
    group: NotRequired[str]


class HelpGroup(TypedDict):
    key: str
    title: str
    note: str


# Golden paths, in the order `git convoy help` prints them. Every section in
# HELP_SECTIONS carries one of these keys.
HELP_GROUPS: list[HelpGroup] = [
    {
        "key": "where",
        "title": "WHERE AM I",
        "note": "Start here when you do not know what runs next.",
    },
    {
        "key": "product",
        "title": "PRODUCT — features into a running environment",
        "note": "Four cycles. Each one ends where the next begins.",
    },
    {
        "key": "ops",
        "title": "OPS — a tooling change the environment must install",
        "note": "Not a product train. After ops prs merge, ops publish tags main. It does not write renglo.yaml.",
    },
    {
        "key": "hotfix",
        "title": "HOTFIX — patch production now",
        "note": "",
    },
    {
        "key": "reference",
        "title": "SETUP AND REFERENCE",
        "note": "Needed once, or when a golden path does not fit.",
    },
]

# Full reference (git convoy help / git convoy help all)
HELP_SECTIONS: list[HelpSection] = [
    {
        "group": "reference",
        "name": "One-time setup",
        "commands": [
            {
                "cmd": "git convoy init",
                "summary": "Create local state, ops.toml membership, gitignore, and Cursor skill.",
            },
        ],
    },
    {
        "group": "where",
        "name": "Any time",
        "commands": [
            {
                "cmd": "git convoy status",
                "summary": "Show current feature, ops, train, hotfix sheets and dirty repos.",
            },
            {
                "cmd": "git convoy sync develop",
                "summary": "Merge stable/main into develop for named or all product repos (no idle check).",
            },
            {
                "cmd": "git convoy sync develop --repos renglo-lib,console",
                "summary": "Same as sync develop, scoped to listed product repo ids.",
            },
        ],
    },
    {
        "group": "where",
        "name": "Catch up",
        "commands": [
            {
                "cmd": "git convoy sync",
                "summary": "Update every clean clone in place; report repos that still need a commit or conflict fix.",
            },
        ],
    },
    {
        "group": "product",
        "name": "Cycle 1 — Feature",
        "commands": [
            {
                "cmd": "git convoy feature start NAME",
                "summary": "Open a feature sheet and checkout develop (or pick up existing feature/NAME with work).",
            },
            {
                "cmd": "git convoy feature adopt",
                "summary": (
                    "Branch dirty product repos onto feature/NAME; reset local develop if you committed there."
                ),
            },
            {
                "cmd": "git convoy feature adopt --repos renglo-lib,renglo-api",
                "summary": (
                    "Adopt only listed product repos so other dirty clones stay on develop for another feature."
                ),
            },
            {
                "cmd": "git convoy feature commit --header \"feat: …\" --header-only",
                "summary": "Commit every dirty feature participant with the same subject line.",
            },
            {
                "cmd": "git convoy feature prs",
                "summary": "Merge stable into develop, push feature branches, open PRs to develop (Full: via gh).",
            },
            {
                "cmd": "git convoy feature approve",
                "summary": "Approve all sibling PRs when CI is green (Full mode; merge stays in GitHub).",
            },
            {
                "cmd": "git convoy feature show",
                "summary": "Print feature sheet status per repo (committed, pending, merged, …).",
            },
            {
                "cmd": "git convoy feature close --yes",
                "summary": "After every PR merged: checkout develop and delete local feature branches.",
            },
        ],
    },
    {
        "group": "product",
        "name": "Cycle 2 — Release train (local)",
        "commands": [
            {
                "cmd": "git convoy train cut NAME",
                "summary": "Create release/NAME on changed product repos and open the train sheet.",
            },
            {
                "cmd": "git convoy train commit --header \"fix: …\" --header-only",
                "summary": "Commit dirty train participants on release/NAME.",
            },
            {
                "cmd": "git convoy train show",
                "summary": "Print the train sheet, versions, and tags.",
            },
        ],
    },
    {
        "group": "product",
        "name": "Cycle 3 — Staging adoption",
        "commands": [
            {
                "cmd": "git convoy train tag-rc",
                "summary": "Sync develop from stable for participants, push rc tags to trigger publish workflows.",
            },
            {
                "cmd": "git convoy train verify",
                "summary": "Check rc publish workflow status via gh (Full mode).",
            },
            {
                "cmd": "git convoy train verify --wait",
                "summary": "Poll until rc publish workflows finish or timeout.",
            },
            {
                "cmd": "git convoy bom check --bom ops/<system>-bom",
                "summary": "Compare the platform pin with package declarations. Writes nothing.",
            },
            {
                "cmd": "git convoy bom --bom ops/<system>-bom",
                "summary": "Write staging BOM pins from the current train; self-heals failed publishes to git SHAs. Warns on platform mismatches before writing.",
            },
            {
                "cmd": "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Adopt release train (staging)\" && git push",
                "summary": "Commit and push the BOM repo — that push deploys staging.",
            },
        ],
    },
    {
        "group": "product",
        "name": "Cycle 4 — Production release",
        "commands": [
            {
                "cmd": "git convoy train publish",
                "summary": "Merge release/NAME to main, tag stable vX.Y.Z, mergeback into develop for all product repos.",
            },
            {
                "cmd": "git convoy train verify --wait",
                "summary": "Confirm stable-tag publish workflows succeeded before promoting the BOM.",
            },
            {
                "cmd": "git convoy train mergeback",
                "summary": "Retry merging tagged main into develop when publish exited early or develop drifted.",
            },
            {
                "cmd": "git convoy bom --production --bom ops/<system>-bom",
                "summary": "Promote the current train BOM to production (stable pins, production.enabled: true).",
            },
            {
                "cmd": "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Adopt production train\" && git push",
                "summary": "Commit and push production BOM — that push deploys production.",
            },
            {
                "cmd": "git convoy train close --yes",
                "summary": "Remove merged release/NAME branches after production adoption.",
            },
        ],
    },
    {
        "group": "product",
        "name": "Product — optional",
        "commands": [
            {
                "cmd": "git convoy feature push",
                "summary": "Push feature/<name> to origin without opening PRs (backup only).",
            },
            {
                "cmd": "git convoy feature prs --no-gh",
                "summary": "Push and print compare URLs instead of opening PRs (Simple mode).",
            },
            {
                "cmd": "git convoy feature refresh",
                "summary": "Merge origin/develop into each feature/<name> participant.",
            },
            {
                "cmd": "git convoy feature switch NAME",
                "summary": "Switch the current feature sheet (refuses if any product repo is dirty).",
            },
            {
                "cmd": "git convoy feature abandon --yes",
                "summary": "Drop the feature sheet without deleting branches or uncommitted files.",
            },
            {
                "cmd": "git convoy train adopt",
                "summary": "Add late dirty product repos to the current train without a version bump.",
            },
            {
                "cmd": "git convoy train tag-rc --no-push",
                "summary": "Create rc tags locally without pushing (cycle 2 dry run).",
            },
            {
                "cmd": "git convoy train publish --no-push",
                "summary": "Tag stable locally without pushing (cycle 2 dry run).",
            },
            {
                "cmd": "git convoy bom --require-verify --bom ops/<system>-bom",
                "summary": "Write staging BOM but refuse when any publish workflow failed (strict).",
            },
            {
                "cmd": "git convoy bom --no-verify --bom ops/<system>-bom",
                "summary": "Write staging BOM using local workflow heuristic only (Simple mode).",
            },
        ],
    },
    {
        "group": "ops",
        "name": "Ship — review on develop, then publish",
        "commands": [
            {
                "cmd": "git convoy ops start NAME",
                "summary": "Open an ops sheet and checkout develop in clean ops repos.",
            },
            {
                "cmd": "git convoy ops adopt",
                "summary": "Branch dirty ops repos onto ops/NAME; ignores product repos.",
            },
            {
                "cmd": "git convoy ops commit --header \"fix: …\" --header-only",
                "summary": "Commit dirty ops participants on ops/NAME.",
            },
            {
                "cmd": "git convoy ops prs",
                "summary": "Open PRs into develop (the only GitHub PR). Merge in GitHub.",
            },
            {
                "cmd": "git convoy ops approve",
                "summary": "Approve sibling ops PRs when CI is green (Full mode; merge stays in GitHub).",
            },
            {
                "cmd": "git convoy ops publish",
                "summary": "After those PRs merge: merge develop→main and tag every publishing repo on the sheet. Does not write renglo.yaml.",
            },
            {
                "cmd": "git convoy ops close --yes",
                "summary": "After publish: checkout develop and delete local ops branches.",
            },
        ],
    },
    {
        "group": "ops",
        "name": "Ops — optional",
        "commands": [
            {
                "cmd": "git convoy ops publish REPO --verify --wait",
                "summary": "After the tag: wait until the publish workflow is green.",
            },
            {
                "cmd": "git convoy ops adopt --repos bom-helper,git-convoy",
                "summary": "Force-include named ops repos on the sheet even when clean.",
            },
            {
                "cmd": "git convoy ops push",
                "summary": "Push ops/<name> without opening PRs.",
            },
            {
                "cmd": "git convoy ops prs --no-gh",
                "summary": "Push and print compare URLs (Simple mode).",
            },
            {
                "cmd": "git convoy ops refresh",
                "summary": "Merge origin/develop into each ops/<name> participant.",
            },
            {
                "cmd": "git convoy ops switch NAME",
                "summary": "Switch the current ops sheet.",
            },
            {
                "cmd": "git convoy ops publish REPO",
                "summary": "Publish one named ops repo (no sheet required) after its develop PR is merged.",
            },
            {
                "cmd": "git convoy ops abandon --yes",
                "summary": "Drop the ops sheet without deleting branches or files.",
            },
        ],
    },
    {
        "group": "hotfix",
        "name": "Hotfix — PRs into main",
        "commands": [
            {
                "cmd": "git convoy hotfix start NAME",
                "summary": "Branch hotfix/NAME from main on dirty product repos; bump PATCH once.",
            },
            {
                "cmd": "git convoy hotfix commit --header \"fix: …\" --header-only",
                "summary": "Commit dirty hotfix participants on hotfix/NAME.",
            },
            {
                "cmd": "git convoy hotfix prs",
                "summary": "Push and open PRs into main (Full: via gh).",
            },
            {
                "cmd": "git convoy hotfix publish",
                "summary": "Tag vX.Y.Z on main, merge into develop, absorb local feature/* branches.",
            },
            {
                "cmd": "git convoy hotfix bom --bom ops/<system>-bom",
                "summary": "Draft next BOM patch; pin only hotfix packages; staging only.",
            },
            {
                "cmd": "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Hotfix (staging)\" && git push",
                "summary": "Commit and push hotfix BOM — that push deploys staging.",
            },
        ],
    },
    {
        "group": "hotfix",
        "name": "Hotfix — after publish",
        "commands": [
            {
                "cmd": "git convoy bom --production --bom ops/<system>-bom",
                "summary": "Enable production on that same BOM version once staging is acceptable.",
            },
            {
                "cmd": "git convoy feature refresh",
                "summary": "Merge the patched develop into every in-progress feature/* branch.",
            },
            {
                "cmd": "git convoy hotfix close --yes",
                "summary": "After the patch is in develop: checkout develop, delete the branch, drop the sheet.",
            },
        ],
    },
    {
        "group": "hotfix",
        "name": "Hotfix — optional",
        "commands": [
            {
                "cmd": "git convoy hotfix push",
                "summary": "Push hotfix/<name> without opening PRs.",
            },
            {
                "cmd": "git convoy hotfix prs --no-gh",
                "summary": "Push and print compare URLs into main (Simple mode).",
            },
            {
                "cmd": "git convoy hotfix show",
                "summary": "Print hotfix sheet: published or not, and whether the tag is in develop.",
            },
            {
                "cmd": "git convoy hotfix abandon --yes",
                "summary": "Drop the hotfix sheet without deleting branches or files.",
            },
        ],
    },
    {
        "group": "reference",
        "name": "BOM — manual primitives",
        "commands": [
            {
                "cmd": "git convoy bom draft --from 1.4.0 --to 1.4.1 --bom ops/<system>-bom",
                "summary": "Copy a version object to a new draft BOM file.",
            },
            {
                "cmd": "git convoy bom pin 1.4.1 renglo-lib 1.2.5 --bom ops/<system>-bom",
                "summary": "Set one package pin on an existing draft.",
            },
            {
                "cmd": "git convoy bom point 1.4.1 --bom ops/<system>-bom",
                "summary": "Point deploy_targets.yml bom: at a version (staging or production).",
            },
        ],
    },
    {
        "group": "reference",
        "name": "Agents",
        "commands": [
            {
                "cmd": "git convoy --json status",
                "summary": "Machine-readable workspace and sheet status.",
            },
            {
                "cmd": "git convoy --json feature commit",
                "summary": "Print a commit plan JSON document for agents to fill and replay.",
            },
            {
                "cmd": "git convoy --json feature commit --from -",
                "summary": "Apply a filled commit plan from stdin.",
            },
        ],
    },
]

# Topic workflows: ordered process views (liberal — include related commands).
HELP_TOPICS: dict[str, list[HelpSection]] = {
    "feature": [
        {
            "name": "Catch up",
            "commands": [
                {
                    "cmd": "git convoy sync",
                    "summary": "Update every clean clone in place; report repos that still need a commit or conflict fix.",
                },
            ],
        },
        {
            "name": "Feature workflow (cycle 1)",
            "commands": [
                {
                    "cmd": "git convoy feature start NAME",
                    "summary": "Open a feature sheet and checkout develop (or pick up existing feature/NAME with work).",
                },
                {
                    "cmd": "git convoy feature adopt",
                    "summary": (
                        "Branch dirty product repos onto feature/NAME; reset local develop if you committed there."
                    ),
                },
                {
                    "cmd": "git convoy feature adopt --repos renglo-lib,renglo-api",
                    "summary": (
                        "Adopt only listed repos; leave other dirty product repos on develop."
                    ),
                },
                {
                    "cmd": "git convoy feature commit --header \"feat: …\" --header-only",
                    "summary": "Commit every dirty feature participant with the same subject line.",
                },
                {
                    "cmd": "git convoy feature prs",
                    "summary": "Merge stable into develop, push feature branches, open PRs to develop.",
                },
                {
                    "cmd": "git convoy feature approve",
                    "summary": "Approve all sibling PRs when CI is green (Full mode; merge in GitHub).",
                },
                {
                    "cmd": "git convoy feature show",
                    "summary": "Print feature sheet status per repo before closing.",
                },
                {
                    "cmd": "git convoy feature close --yes",
                    "summary": "After every PR merged: checkout develop and delete local feature branches.",
                },
            ],
        },
        {
            "name": "While a feature is open",
            "commands": [
                {
                    "cmd": "git convoy sync develop",
                    "summary": "Heal develop from stable/main without closing the feature (product repos only).",
                },
                {
                    "cmd": "git convoy feature refresh",
                    "summary": "Merge origin/develop into each feature/<name> participant.",
                },
                {
                    "cmd": "git convoy status",
                    "summary": "See current sheet, branch, and dirty repos.",
                },
            ],
        },
        {
            "name": "After a hotfix lands (parallel path)",
            "commands": [
                {
                    "cmd": "git convoy hotfix publish",
                    "summary": "Tag on main and merge patch back into develop (hotfix workflow).",
                },
                {
                    "cmd": "git convoy feature refresh",
                    "summary": "Pull the hotfix into every in-progress feature/* branch.",
                },
            ],
        },
        {
            "name": "Optional",
            "commands": [
                {
                    "cmd": "git convoy feature push",
                    "summary": "Push feature/<name> without opening PRs.",
                },
                {
                    "cmd": "git convoy feature prs --no-gh",
                    "summary": "Push and print compare URLs (Simple mode).",
                },
                {
                    "cmd": "git convoy feature switch NAME",
                    "summary": "Switch the current feature sheet.",
                },
                {
                    "cmd": "git convoy feature abandon --yes",
                    "summary": "Drop the feature sheet without deleting branches.",
                },
            ],
        },
    ],
    "train": [
        {
            "name": "Cycle 2 — Cut and stabilize locally",
            "commands": [
                {
                    "cmd": "git convoy train cut NAME",
                    "summary": "Create release/NAME on changed product repos.",
                },
                {
                    "cmd": "git convoy train adopt",
                    "summary": "Add late dirty repos to the train without bumping versions.",
                },
                {
                    "cmd": "git convoy train commit --header \"fix: …\" --header-only",
                    "summary": "Commit dirty train participants.",
                },
                {
                    "cmd": "git convoy train show",
                    "summary": "Inspect train participants and version targets.",
                },
            ],
        },
        {
            "name": "Cycle 3 — Staging (rc tags + BOM)",
            "commands": [
                {
                    "cmd": "git convoy train tag-rc",
                    "summary": "Push rc tags; triggers CodeArtifact publish workflows.",
                },
                {
                    "cmd": "git convoy train verify --wait",
                    "summary": "Wait for rc publish workflows to finish (Full mode).",
                },
                {
                    "cmd": "git convoy bom check --bom ops/<system>-bom",
                    "summary": "Compare the platform pin with package declarations. Writes nothing.",
                },
                {
                    "cmd": "git convoy bom --bom ops/<system>-bom",
                    "summary": "Write staging BOM from the current train. Warns on platform mismatches before writing.",
                },
                {
                    "cmd": "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Adopt release train (staging)\" && git push",
                    "summary": "Push staging BOM — that push deploys staging.",
                },
            ],
        },
        {
            "name": "Cycle 4 — Production",
            "commands": [
                {
                    "cmd": "git convoy train publish",
                    "summary": "Tag stable on main and mergeback into develop.",
                },
                {
                    "cmd": "git convoy train verify --wait",
                    "summary": "Confirm stable publish workflows succeeded.",
                },
                {
                    "cmd": "git convoy train mergeback",
                    "summary": "Retry develop sync if publish stopped early.",
                },
                {
                    "cmd": "git convoy bom --production --bom ops/<system>-bom",
                    "summary": "Promote the train BOM to production.",
                },
                {
                    "cmd": "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Adopt production train\" && git push",
                    "summary": "Push production BOM — that push deploys production.",
                },
                {
                    "cmd": "git convoy train close --yes",
                    "summary": "Delete merged release/NAME branches.",
                },
            ],
        },
        {
            "name": "Optional / strict BOM",
            "commands": [
                {
                    "cmd": "git convoy bom --require-verify --bom ops/<system>-bom",
                    "summary": "Refuse BOM write when any publish workflow failed.",
                },
                {
                    "cmd": "git convoy bom --no-verify --bom ops/<system>-bom",
                    "summary": "Write BOM without gh verify (Simple mode heuristic).",
                },
                {
                    "cmd": "git convoy train tag-rc --no-push",
                    "summary": "Local rc tags only (stay in cycle 2).",
                },
                {
                    "cmd": "git convoy train publish --no-push",
                    "summary": "Local stable tags only (stay in cycle 2).",
                },
            ],
        },
    ],
    "staging": [
        {
            "name": "Cycle 3 — Staging adoption",
            "commands": [
                {
                    "cmd": "git convoy train tag-rc",
                    "summary": "Sync develop from stable for participants, push rc tags to trigger publish workflows.",
                },
                {
                    "cmd": "git convoy train verify",
                    "summary": "Check rc publish workflow status via gh (Full mode).",
                },
                {
                    "cmd": "git convoy train verify --wait",
                    "summary": "Poll until rc publish workflows finish or timeout.",
                },
                {
                    "cmd": "git convoy bom check --bom ops/<system>-bom",
                    "summary": "Compare the platform pin with package declarations. Writes nothing.",
                },
                {
                    "cmd": "git convoy bom --bom ops/<system>-bom",
                    "summary": "Write staging BOM pins from the current train; self-heals failed publishes to git SHAs. Warns on platform mismatches before writing.",
                },
                {
                    "cmd": "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Adopt release train (staging)\" && git push",
                    "summary": "Commit and push the BOM repo — that push deploys staging.",
                },
            ],
        },
    ],
    "production": [
        {
            "name": "Cycle 4 — Production release",
            "commands": [
                {
                    "cmd": "git convoy train publish",
                    "summary": "Merge release/NAME to main, tag stable vX.Y.Z, mergeback into develop for all product repos.",
                },
                {
                    "cmd": "git convoy train verify --wait",
                    "summary": "Confirm stable-tag publish workflows succeeded before promoting the BOM.",
                },
                {
                    "cmd": "git convoy train mergeback",
                    "summary": "Retry merging tagged main into develop when publish exited early or develop drifted.",
                },
                {
                    "cmd": "git convoy bom --production --bom ops/<system>-bom",
                    "summary": "Promote the current train BOM to production (stable pins, production.enabled: true).",
                },
                {
                    "cmd": "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Adopt production train\" && git push",
                    "summary": "Commit and push production BOM — that push deploys production.",
                },
                {
                    "cmd": "git convoy train close --yes",
                    "summary": "Remove merged release/NAME branches after production adoption.",
                },
            ],
        },
    ],
    "ops": [
        {
            "name": "Ship — review on develop, then publish",
            "commands": [
                {
                    "cmd": "git convoy ops start NAME",
                    "summary": "Open an ops sheet; checkout develop in clean ops repos.",
                },
                {
                    "cmd": "git convoy ops adopt",
                    "summary": "Branch dirty ops repos onto ops/NAME.",
                },
                {
                    "cmd": "git convoy ops commit --header \"fix: …\" --header-only",
                    "summary": "Commit dirty ops participants.",
                },
                {
                    "cmd": "git convoy ops prs",
                    "summary": "Push and open PRs into develop (the only GitHub PR).",
                },
                {
                    "cmd": "git convoy ops publish",
                    "summary": "After merge: merge develop→main and tag publishing repos on the sheet. Does not write renglo.yaml.",
                },
                {
                    "cmd": "git convoy ops close --yes",
                    "summary": "After publish: checkout develop and delete ops branches.",
                },
            ],
        },
        {
            "name": "While an ops sheet is open",
            "commands": [
                {
                    "cmd": "git convoy ops refresh",
                    "summary": "Merge origin/develop into ops/<name> participants.",
                },
                {
                    "cmd": "git convoy status",
                    "summary": "See current ops sheet and dirty repos.",
                },
            ],
        },
        {
            "name": "Optional",
            "commands": [
                {
                    "cmd": "git convoy ops adopt --repos bom-helper,git-convoy",
                    "summary": "Force-include named ops repos on the sheet even when clean.",
                },
                {
                    "cmd": "git convoy ops push",
                    "summary": "Push ops/<name> without opening PRs.",
                },
                {
                    "cmd": "git convoy ops prs --no-gh",
                    "summary": "Push and print compare URLs (Simple mode).",
                },
                {
                    "cmd": "git convoy ops switch NAME",
                    "summary": "Switch the current ops sheet.",
                },
                {
                    "cmd": "git convoy ops publish REPO",
                    "summary": "Publish one named ops repo after its develop PR is merged.",
                },
                {
                    "cmd": "git convoy ops abandon --yes",
                    "summary": "Drop the ops sheet without deleting branches or files.",
                },
            ],
        },
    ],
    "hotfix": [
        {
            "name": "Hotfix emergency (PRs into main)",
            "commands": [
                {
                    "cmd": "git convoy hotfix start NAME",
                    "summary": "Branch hotfix/NAME from main; bump PATCH once.",
                },
                {
                    "cmd": "git convoy hotfix commit --header \"fix: …\" --header-only",
                    "summary": "Commit dirty hotfix participants.",
                },
                {
                    "cmd": "git convoy hotfix prs",
                    "summary": "Push and open PRs into main.",
                },
                {
                    "cmd": "git convoy hotfix publish",
                    "summary": "Tag on main, merge into develop, absorb local feature/*.",
                },
                {
                    "cmd": "git convoy hotfix bom --bom ops/<system>-bom",
                    "summary": "Pin only hotfix packages on the next BOM patch (staging).",
                },
                {
                    "cmd": "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Hotfix (staging)\" && git push",
                    "summary": "Push hotfix BOM — that push deploys staging.",
                },
            ],
        },
        {
            "name": "After hotfix publish",
            "commands": [
                {
                    "cmd": "git convoy feature refresh",
                    "summary": "Merge patched develop into in-progress feature/* branches.",
                },
                {
                    "cmd": "git convoy bom --production --bom ops/<system>-bom",
                    "summary": "Enable production on the same BOM version when staging is acceptable.",
                },
            ],
        },
        {
            "name": "Optional",
            "commands": [
                {
                    "cmd": "git convoy hotfix push",
                    "summary": "Push hotfix/<name> without opening PRs.",
                },
                {
                    "cmd": "git convoy hotfix prs --no-gh",
                    "summary": "Push and print compare URLs into main (Simple mode).",
                },
                {
                    "cmd": "git convoy hotfix show",
                    "summary": "Print hotfix sheet: published or not, and whether the tag is in develop.",
                },
                {
                    "cmd": "git convoy hotfix close --yes",
                    "summary": "After the patch is in develop: checkout develop, delete the hotfix branch, drop the sheet.",
                },
                {
                    "cmd": "git convoy feature refresh",
                    "summary": "After hotfix publish: merge develop into in-progress feature/* branches.",
                },
                {
                    "cmd": "git convoy hotfix abandon --yes",
                    "summary": "Drop the hotfix sheet without deleting branches or files.",
                },
            ],
        },
    ],
    "bom": [
        {
            "name": "Typical train adoption (cycles 3–4)",
            "commands": [
                {
                    "cmd": "git convoy train verify --wait",
                    "summary": "Confirm publish workflows before writing the BOM.",
                },
                {
                    "cmd": "git convoy bom check --bom ops/<system>-bom",
                    "summary": "Compare the platform pin with package declarations. Writes nothing.",
                },
                {
                    "cmd": "git convoy bom --bom ops/<system>-bom",
                    "summary": "Write staging BOM from the current train. Warns on platform mismatches before writing.",
                },
                {
                    "cmd": "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Adopt release train (staging)\" && git push",
                    "summary": "Push staging BOM.",
                },
                {
                    "cmd": "git convoy bom --production --bom ops/<system>-bom",
                    "summary": "Promote the same train to production when ready.",
                },
            ],
        },
        {
            "name": "Hotfix BOM",
            "commands": [
                {
                    "cmd": "git convoy hotfix bom --bom ops/<system>-bom",
                    "summary": "Patch BOM; pin only hotfix packages; staging only.",
                },
            ],
        },
        {
            "name": "Manual BOM editing",
            "commands": [
                {
                    "cmd": "git convoy bom --require-verify --bom ops/<system>-bom",
                    "summary": "Write staging BOM but refuse when any publish workflow failed (strict).",
                },
                {
                    "cmd": "git convoy bom --no-verify --bom ops/<system>-bom",
                    "summary": "Write staging BOM using local workflow heuristic only (Simple mode).",
                },
                {
                    "cmd": "git convoy bom draft --from 1.4.0 --to 1.4.1 --bom ops/<system>-bom",
                    "summary": "Copy a version object to a new draft BOM file.",
                },
                {
                    "cmd": "git convoy bom pin 1.4.1 renglo-lib 1.2.5 --bom ops/<system>-bom",
                    "summary": "Set one package pin on an existing draft.",
                },
                {
                    "cmd": "git convoy bom point 1.4.1 --bom ops/<system>-bom",
                    "summary": "Point deploy_targets.yml bom: at a version (staging or production).",
                },
            ],
        },
    ],
    "sync": [
        {
            "name": "Workspace sync",
            "commands": [
                {
                    "cmd": "git convoy sync",
                    "summary": "Update every clean clone in place; report repos that still need a commit or conflict fix.",
                },
                {
                    "cmd": "git convoy sync develop",
                    "summary": "Merge stable/main into develop for all product repos.",
                },
                {
                    "cmd": "git convoy sync develop --repos renglo-lib,console",
                    "summary": "Heal develop for named product repos only.",
                },
            ],
        },
        {
            "name": "While work is in progress",
            "commands": [
                {
                    "cmd": "git convoy feature refresh",
                    "summary": "Merge origin/develop into feature/<name> participants.",
                },
                {
                    "cmd": "git convoy ops refresh",
                    "summary": "Merge origin/develop into ops/<name> participants.",
                },
                {
                    "cmd": "git convoy status",
                    "summary": "Check current sheets before syncing.",
                },
            ],
        },
    ],
    "init": [
        {
            "name": "One-time setup",
            "commands": [
                {
                    "cmd": "git convoy init",
                    "summary": "Create local state, ops.toml membership, gitignore, and Cursor skill.",
                },
            ],
        },
    ],
    "status": [
        {
            "name": "Inspect workspace",
            "commands": [
                {
                    "cmd": "git convoy status",
                    "summary": "Show current feature, ops, train, hotfix sheets and dirty repos.",
                },
            ],
        },
    ],
}

TOPIC_ALIASES: dict[str, str] = {
    "all": "all",
    "cycle1": "feature",
    "cycle2": "train",
    "cycle3": "staging",
    "cycle4": "production",
    "release": "train",
    "platform": "ops",
}

HELP_TOPIC_NAMES: tuple[str, ...] = (
    "all",
    "feature",
    "train",
    "staging",
    "production",
    "ops",
    "hotfix",
    "bom",
    "sync",
    "init",
    "status",
)


# Second column on a shortcut that reprints the block above it.
_ONLY = "Only the commands in this section."

# (parent, section name) → (shortcut, blurb). Parent is a group key or a topic name.
_SECTION_LINKS: dict[tuple[str, str], tuple[str, str]] = {
    ("reference", "One-time setup"): ("init", _ONLY),
    ("where", "Any time"): ("anytime", _ONLY),
    ("where", "Catch up"): ("catchup", _ONLY),
    ("product", "Cycle 1 — Feature"): (
        "feature",
        "Feature sheet, plus sync and hotfix refresh.",
    ),
    ("product", "Cycle 2 — Release train (local)"): ("cycle-2", _ONLY),
    ("product", "Cycle 3 — Staging adoption"): ("staging", _ONLY),
    ("product", "Cycle 4 — Production release"): ("production", _ONLY),
    ("product", "Product — optional"): ("product-optional", _ONLY),
    ("ops", "Ship — review on develop, then publish"): ("ship", _ONLY),
    ("ops", "Ops — optional"): ("ops-optional", _ONLY),
    ("hotfix", "Hotfix — PRs into main"): ("hotfix-steps", _ONLY),
    ("hotfix", "Hotfix — after publish"): ("hotfix-after", _ONLY),
    ("hotfix", "Hotfix — optional"): ("hotfix-optional", _ONLY),
    ("reference", "BOM — manual primitives"): ("bom-manual", _ONLY),
    ("reference", "Agents"): ("agents", _ONLY),
    ("feature", "Catch up"): ("catchup", _ONLY),
    ("feature", "Feature workflow (cycle 1)"): ("feature-workflow", _ONLY),
    ("feature", "While a feature is open"): ("feature-open", _ONLY),
    ("feature", "After a hotfix lands (parallel path)"): ("feature-hotfix", _ONLY),
    ("feature", "Optional"): ("feature-extra", _ONLY),
    ("train", "Cycle 2 — Cut and stabilize locally"): ("train-cut", _ONLY),
    ("train", "Cycle 3 — Staging (rc tags + BOM)"): ("train-staging", _ONLY),
    ("train", "Cycle 4 — Production"): ("train-production", _ONLY),
    ("train", "Optional / strict BOM"): ("train-optional", _ONLY),
    ("ops", "While an ops sheet is open"): ("ops-open", _ONLY),
    ("ops", "Optional"): ("ops-extra", _ONLY),
    ("hotfix", "Hotfix emergency (PRs into main)"): ("hotfix-prs", _ONLY),
    ("hotfix", "After hotfix publish"): ("hotfix-landed", _ONLY),
    ("hotfix", "Optional"): ("hotfix-extra", _ONLY),
    ("bom", "Typical train adoption (cycles 3–4)"): ("bom-adopt", _ONLY),
    ("bom", "Hotfix BOM"): ("bom-hotfix", _ONLY),
    ("bom", "Manual BOM editing"): ("bom-edit", _ONLY),
    ("sync", "Workspace sync"): ("sync-now", _ONLY),
    ("sync", "While work is in progress"): ("sync-open", _ONLY),
    ("init", "One-time setup"): ("init", _ONLY),
    ("status", "Inspect workspace"): ("status", _ONLY),
    ("staging", "Cycle 3 — Staging adoption"): ("staging", _ONLY),
    ("production", "Cycle 4 — Production release"): ("production", _ONLY),
}

_TOPIC_TITLES: dict[str, str] = {
    "feature": "Ship a feature",
    "train": "Cut a train and adopt it",
    "staging": "Cycle 3 — Staging adoption",
    "production": "Cycle 4 — Production release",
    "ops": "Ship an ops change",
    "hotfix": "Patch production now",
    "bom": "Write the BOM",
    "sync": "Catch up",
    "init": "One-time setup",
    "status": "See where you are",
}


def _section_link(parent: str, name: str) -> tuple[str, str]:
    try:
        return _SECTION_LINKS[(parent, name)]
    except KeyError as exc:
        raise GitConvoyError(f"help section {name!r} under {parent!r} has no shortcut") from exc


def _group_sections() -> dict[str, list[HelpSection]]:
    grouped: dict[str, list[HelpSection]] = {group["key"]: [] for group in HELP_GROUPS}
    for section in grouped_sections():
        grouped[section["group"]].append(section)
    return grouped


def _exact_sections() -> dict[str, list[HelpSection]]:
    """Shortcuts that reprint one section. Named topics (feature, ops, …) stay sequences."""
    found: dict[str, list[HelpSection]] = {}

    def add(slug: str, section: HelpSection) -> None:
        if slug in HELP_TOPICS or slug in TOPIC_ALIASES:
            return
        found.setdefault(slug, [section])

    for section in grouped_sections():
        slug, _blurb = _section_link(section["group"], section["name"])
        add(slug, section)
    for topic, sections in HELP_TOPICS.items():
        for section in sections:
            slug, _blurb = _section_link(topic, section["name"])
            add(slug, section)
    for key, sections in _group_sections().items():
        if key not in HELP_TOPICS and key not in TOPIC_ALIASES:
            found.setdefault(key, sections)
    return found


def _known_topic_names() -> list[str]:
    names = list(HELP_TOPIC_NAMES)
    seen = set(names) | set(TOPIC_ALIASES)
    for slug in _exact_sections():
        if slug not in seen:
            names.append(slug)
            seen.add(slug)
    return names


def resolve_help_topic(topic: str | None) -> str:
    if not topic:
        return "all"
    key = topic.strip().lower()
    if key in HELP_TOPICS:
        return key
    if key in TOPIC_ALIASES:
        return TOPIC_ALIASES[key]
    if key in _exact_sections():
        return key
    valid = ", ".join(_known_topic_names())
    raise GitConvoyError(f"unknown help topic {topic!r}; choose from: {valid}")


def grouped_sections() -> list[HelpSection]:
    """HELP_SECTIONS in golden-path order: every section, grouped, no duplicates."""
    order = [group["key"] for group in HELP_GROUPS]
    known = set(order)
    for section in HELP_SECTIONS:
        key = section.get("group")
        if key not in known:
            raise GitConvoyError(
                f"help section {section['name']!r} has no known group "
                f"(expected one of: {', '.join(order)})"
            )
    return [
        section
        for key in order
        for section in HELP_SECTIONS
        if section.get("group") == key
    ]


def sections_for_topic(topic: str) -> list[HelpSection]:
    if topic == "all":
        return grouped_sections()
    if topic in HELP_TOPICS:
        return HELP_TOPICS[topic]
    exact = _exact_sections()
    if topic in exact:
        return exact[topic]
    raise GitConvoyError(f"unknown help topic {topic!r}")


def help_payload(*, topic: str | None = None, summaries: bool = False) -> dict:
    resolved = resolve_help_topic(topic)
    sections = sections_for_topic(resolved)
    payload_sections = []
    for section in sections:
        rows = []
        for item in section["commands"]:
            rows.append({"cmd": item["cmd"], "summary": item["summary"]})
        row: dict = {"name": section["name"], "commands": rows}
        group = section.get("group")
        if group:
            row["group"] = group
        payload_sections.append(row)
    payload = {
        "ok": True,
        "topic": resolved,
        "summaries": summaries,
        "sections": payload_sections,
        "topics": list(HELP_TOPIC_NAMES),
    }
    if resolved == "all":
        payload["groups"] = [
            {"key": group["key"], "title": group["title"], "note": group["note"]}
            for group in HELP_GROUPS
        ]
    return payload


def format_help_text(*, topic: str | None = None, summaries: bool = False) -> str:
    """Text help. Summaries are always shown; ``summaries`` is accepted and ignored."""
    del summaries
    resolved = resolve_help_topic(topic)
    if resolved == "all":
        return _format_all()
    if resolved in _TOPIC_TITLES:
        return _format_named_topic(resolved)
    return _format_exact(resolved)


def _row(command: str, blurb: str, width: int) -> str:
    return f"  {command:<{width}}  {blurb}"


def _width(commands: list[str]) -> int:
    convoy = [command for command in commands if command.startswith("git convoy")]
    pool = convoy or commands
    return max(len(command) for command in pool)


def _render_commands(commands: list[HelpCommand], width: int) -> list[str]:
    return [_row(item["cmd"], item["summary"], width) for item in commands]


def _format_all() -> str:
    names = ["git convoy help"]
    grouped = _group_sections()
    for group in HELP_GROUPS:
        names.append(f"git convoy help {group['key']}")
        for section in grouped[group["key"]]:
            slug, _blurb = _section_link(group["key"], section["name"])
            names.append(f"git convoy help {slug}")
            names.extend(item["cmd"] for item in section["commands"])
    width = _width(names)
    lines = [
        "git convoy — quick reference",
        "",
        _row("git convoy help", "Every command, grouped by the job you are doing.", width),
        "",
        "Process and detail: ops/git-convoy/README.md",
        "",
    ]
    for index, group in enumerate(HELP_GROUPS):
        if index:
            lines.append("")
        lines.extend(_render_group(group, grouped[group["key"]], width))
    return "\n".join(lines).rstrip() + "\n"


def _render_group(group: HelpGroup, sections: list[HelpSection], width: int) -> list[str]:
    note = group["note"].strip() or _ONLY
    lines = [
        group["title"],
        _row(f"git convoy help {group['key']}", note, width),
    ]
    for section in sections:
        lines.append("")
        lines.extend(_render_section(section, group["key"], width, nested=True))
    return lines


def _render_section(
    section: HelpSection,
    parent: str,
    width: int,
    *,
    nested: bool,
    shortcut: str | None = None,
    blurb: str | None = None,
) -> list[str]:
    slug, section_blurb = _section_link(parent, section["name"])
    title = f"  {section['name']}" if nested else section["name"]
    lines = [
        title,
        _row(f"git convoy help {shortcut or slug}", blurb or section_blurb, width),
    ]
    lines.extend(_render_commands(section["commands"], width))
    return lines


def _format_named_topic(topic: str) -> str:
    sections = HELP_TOPICS[topic]
    names = [f"git convoy help {topic}"]
    for section in sections:
        slug, _blurb = _section_link(topic, section["name"])
        names.append(f"git convoy help {slug}")
        names.extend(item["cmd"] for item in section["commands"])
    width = _width(names)
    if len(sections) == 1:
        return "\n".join(_render_section(sections[0], topic, width, nested=False)) + "\n"
    lines = [
        _TOPIC_TITLES[topic],
        _row(f"git convoy help {topic}", _ONLY, width),
    ]
    for section in sections:
        lines.append("")
        lines.extend(_render_section(section, topic, width, nested=True))
    return "\n".join(lines).rstrip() + "\n"


def _format_exact(topic: str) -> str:
    sections = _exact_sections()[topic]
    if topic in {group["key"] for group in HELP_GROUPS}:
        group = next(item for item in HELP_GROUPS if item["key"] == topic)
        names = [f"git convoy help {topic}"]
        for section in sections:
            slug, _blurb = _section_link(group["key"], section["name"])
            names.append(f"git convoy help {slug}")
            names.extend(item["cmd"] for item in section["commands"])
        return "\n".join(_render_group(group, sections, _width(names))).rstrip() + "\n"
    section = sections[0]
    parent = section.get("group") or ""
    if not parent:
        for owner, owned in HELP_TOPICS.items():
            if section in owned:
                parent = owner
                break
    names = [f"git convoy help {topic}"]
    names.extend(item["cmd"] for item in section["commands"])
    lines = _render_section(
        section,
        parent,
        _width(names),
        nested=False,
        shortcut=topic,
        blurb=_ONLY,
    )
    return "\n".join(lines).rstrip() + "\n"
