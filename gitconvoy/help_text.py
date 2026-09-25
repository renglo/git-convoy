from __future__ import annotations

from typing import TypedDict

from gitconvoy.errors import GitConvoyError


class HelpCommand(TypedDict):
    cmd: str
    summary: str


class HelpSection(TypedDict):
    name: str
    commands: list[HelpCommand]


# Full reference (git convoy help / git convoy help all)
HELP_SECTIONS: list[HelpSection] = [
    {
        "name": "One-time setup",
        "commands": [
            {
                "cmd": "git convoy init",
                "summary": "Create local state, ops.toml membership, gitignore, and Cursor skill.",
            },
        ],
    },
    {
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
        "name": "Start of session (idle workspace)",
        "commands": [
            {
                "cmd": "git convoy sync",
                "summary": "Fetch all clones, checkout develop, absorb hotfixes; refuses if workspace is busy.",
            },
        ],
    },
    {
        "name": "Cycle 1 — Feature",
        "commands": [
            {
                "cmd": "git convoy feature start NAME",
                "summary": "Open a feature sheet and checkout develop (or pick up existing feature/NAME with work).",
            },
            {
                "cmd": "git convoy feature adopt",
                "summary": "Branch dirty product repos onto feature/NAME; reset local develop if you committed there.",
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
        "name": "Cycle 1 — Feature (optional)",
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
        ],
    },
    {
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
                "cmd": "git convoy train adopt",
                "summary": "Add late dirty product repos to the current train without a version bump.",
            },
            {
                "cmd": "git convoy train show",
                "summary": "Print the train sheet, versions, and tags.",
            },
            {
                "cmd": "git convoy train delete --yes",
                "summary": "Delete merged local release/NAME branches after publish (never drops uncommitted work).",
            },
        ],
    },
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
                "cmd": "git convoy bom --bom ops/<system>-bom",
                "summary": "Write staging BOM pins from the current train; self-heals failed publishes to git SHAs.",
            },
            {
                "cmd": "cd ops/<system>-bom && git add bom/ deploy_targets.yml && git commit -m \"Adopt release train (staging)\" && git push",
                "summary": "Commit and push the BOM repo — that push deploys staging.",
            },
        ],
    },
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
                "cmd": "git convoy train delete --yes",
                "summary": "Remove merged release/NAME branches after production adoption.",
            },
        ],
    },
    {
        "name": "Ops — Operator tooling",
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
                "summary": "Merge origin/develop, push, open PRs into develop (Full: via gh).",
            },
            {
                "cmd": "git convoy ops show",
                "summary": "Print ops sheet status per participant.",
            },
            {
                "cmd": "git convoy ops close --yes",
                "summary": "After PRs merge to develop: checkout develop and delete local ops branches.",
            },
        ],
    },
    {
        "name": "Ops — Operator tooling (optional)",
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
                "cmd": "git convoy ops approve",
                "summary": "Approve sibling ops PRs via gh (Full mode).",
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
                "cmd": "git convoy ops promote",
                "summary": "Sheet-scoped develop→main PRs when develop is ahead (no bump or tag).",
            },
            {
                "cmd": "git convoy ops release bom-helper",
                "summary": "Per-repo platform release: bump, develop→main PR, or tag on main.",
            },
            {
                "cmd": "git convoy ops release bom-helper --verify --wait --pin --bom ops/<system>-bom",
                "summary": "Tag, confirm publish CI, and pin helper.ref in the tenant BOM.",
            },
            {
                "cmd": "git convoy ops abandon --yes",
                "summary": "Drop the ops sheet without deleting branches or files.",
            },
        ],
    },
    {
        "name": "Hotfix — Production emergency",
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
        "name": "Hotfix — Production emergency (optional)",
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
                "summary": "Print hotfix sheet status per participant.",
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
    {
        "name": "BOM — Manual primitives",
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
    {
        "name": "Train — Git-only (stay in cycle 2)",
        "commands": [
            {
                "cmd": "git convoy train tag-rc --no-push",
                "summary": "Create rc tags locally without pushing (cycle 2 dry run).",
            },
            {
                "cmd": "git convoy train publish --no-push",
                "summary": "Tag stable locally without pushing (cycle 2 dry run).",
            },
        ],
    },
    {
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
            "name": "Start of session (idle workspace)",
            "commands": [
                {
                    "cmd": "git convoy sync",
                    "summary": "Fetch all clones, checkout develop, absorb hotfixes; refuses if workspace is busy.",
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
                    "summary": "Branch dirty product repos onto feature/NAME; reset local develop if you committed there.",
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
                    "cmd": "git convoy bom --bom ops/<system>-bom",
                    "summary": "Write staging BOM from the current train.",
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
                    "cmd": "git convoy train delete --yes",
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
                    "cmd": "git convoy bom --bom ops/<system>-bom",
                    "summary": "Write staging BOM pins from the current train; self-heals failed publishes to git SHAs.",
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
                    "cmd": "git convoy train delete --yes",
                    "summary": "Remove merged release/NAME branches after production adoption.",
                },
            ],
        },
    ],
    "ops": [
        {
            "name": "Daily ops work (ops/<name> → develop)",
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
                    "summary": "Push and open PRs into develop.",
                },
                {
                    "cmd": "git convoy ops approve",
                    "summary": "Approve sibling PRs (Full mode).",
                },
                {
                    "cmd": "git convoy ops show",
                    "summary": "Print ops sheet status.",
                },
                {
                    "cmd": "git convoy ops close --yes",
                    "summary": "After merge to develop: checkout develop and delete ops branches.",
                },
            ],
        },
        {
            "name": "Platform release (no sheet)",
            "commands": [
                {
                    "cmd": "git convoy ops release bom-helper",
                    "summary": "Bump, open develop→main PR, or tag on main as repo state requires.",
                },
                {
                    "cmd": "git convoy ops release bom-helper --verify --wait --pin --bom ops/<system>-bom",
                    "summary": "Tag, verify publish CI, pin helper.ref; then commit and push the BOM.",
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
                    "cmd": "git convoy ops approve",
                    "summary": "Approve sibling ops PRs via gh (Full mode).",
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
                    "cmd": "git convoy ops promote",
                    "summary": "Sheet-scoped develop→main PRs when develop is ahead (no bump or tag).",
                },
                {
                    "cmd": "git convoy ops release bom-helper",
                    "summary": "Per-repo platform release: bump, develop→main PR, or tag on main.",
                },
                {
                    "cmd": "git convoy ops release bom-helper --verify --wait --pin --bom ops/<system>-bom",
                    "summary": "Tag, confirm publish CI, and pin helper.ref in the tenant BOM.",
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
                    "summary": "Print hotfix sheet status per participant.",
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
                    "cmd": "git convoy bom --bom ops/<system>-bom",
                    "summary": "Write staging BOM from the current train.",
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
                    "summary": "Idle workspace: fetch all, checkout develop, absorb hotfixes (refuses if busy).",
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


def resolve_help_topic(topic: str | None) -> str:
    if not topic:
        return "all"
    key = topic.strip().lower()
    if key in HELP_TOPICS:
        return key
    if key in TOPIC_ALIASES:
        return TOPIC_ALIASES[key]
    valid = ", ".join(HELP_TOPIC_NAMES)
    raise GitConvoyError(f"unknown help topic {topic!r}; choose from: {valid}")


def sections_for_topic(topic: str) -> list[HelpSection]:
    if topic == "all":
        return HELP_SECTIONS
    return HELP_TOPICS[topic]


def help_payload(*, topic: str | None = None, summaries: bool = False) -> dict:
    resolved = resolve_help_topic(topic)
    sections = sections_for_topic(resolved)
    payload_sections = []
    for section in sections:
        rows = []
        for item in section["commands"]:
            rows.append({"cmd": item["cmd"], "summary": item["summary"]})
        payload_sections.append({"name": section["name"], "commands": rows})
    return {
        "ok": True,
        "topic": resolved,
        "summaries": summaries,
        "sections": payload_sections,
        "topics": list(HELP_TOPIC_NAMES),
    }


def format_help_text(*, topic: str | None = None, summaries: bool = False) -> str:
    resolved = resolve_help_topic(topic)
    sections = sections_for_topic(resolved)
    if resolved == "all":
        title = "git convoy — command sequences (all topics)"
    else:
        title = f"git convoy help {resolved} — command sequence"
    lines = [title, ""]
    if resolved != "all":
        lines.append("Run in order within each section. Related commands from other topics are included.")
        lines.append("")
    for section in sections:
        lines.append(section["name"])
        for item in section["commands"]:
            lines.append(f"  {item['cmd']}")
            if summaries:
                lines.append(f"    {item['summary']}")
        lines.append("")
    lines.append(f"Topics: {', '.join(HELP_TOPIC_NAMES)}")
    lines.append("Summaries: git convoy help [TOPIC] -s")
    return "\n".join(lines).rstrip() + "\n"
