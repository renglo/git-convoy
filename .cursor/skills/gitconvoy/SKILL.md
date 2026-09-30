---
name: gitconvoy
description: >-
  Operate the git-convoy CLI for cross-repo features, ops (operator tooling),
  release trains, hotfixes, and BOM adoption. Use when the user mentions git
  convoy, git-convoy, gitconvoy, a feature sheet, an ops sheet, a release train,
  a production hotfix, which repos a feature touches, what is on the current
  train, catch up every clone in place, adopt onto a feature or ops
  branch, commit participant repos, refresh from develop, or staging/production
  pins.
---

# git-convoy

Authority process: `ops/git-convoy/cross-repo-feature-manual.md`.
CLI manual: `ops/git-convoy/README.md`.

Prefer `git convoy` over raw git for any step that spans more than one repo.

## Simple vs Full mode

- **Simple:** `git` only. `feature prs --no-gh` prints compare URLs; merge status via git; approve PRs and publish CI checks in the GitHub UI.
- **Full:** `gh` logged in or `GH_TOKEN` set. Enables `feature prs`, `feature approve`, squash-safe `feature show`, and `train verify`. No AWS profile required for publish checks.

Setup: install `gh`, run `gh auth login`, verify with `gh auth status`. Token needs pull-request and Actions read on every participant repo. See README “Simple vs Full mode”.

## Ask the CLI first

Run from the workspace root (or pass `--workspace`). Always add `--json` when you need to answer a question.

```bash
git convoy --json status
git convoy --json sync
git convoy --json feature show
git convoy --json ops show
git convoy --json train show
git convoy --json hotfix show
git convoy --json feature commit
```

- "What's on the current train?" → `git convoy --json train show`
- "Catch up after time away / put me on develop?" → `git convoy --json sync`
- "How many repos is this feature touching?" → `git convoy --json feature show` (`repo_count`)
- "Which feature am I on?" → `git convoy --json status`
- "Which ops sheet am I on?" → `git convoy --json status` / `git convoy --json ops show`
- "Which hotfix am I on?" → `git convoy --json status` / `git convoy --json hotfix show`

Do not guess membership by scanning dirty directories. The state file is `.gitconvoy/state.json` (gitignored). Ops/product membership is `.gitconvoy/ops.toml` (written by `git convoy init` from each repo’s `gitconvoy.toml` `role`). BOM membership is `packages:` in the BOM repo `deploy_targets.yml` when present.

## Start of a work session

Bring every clone up to date without requiring an idle workspace:

```bash
git convoy --json sync
```

Updates each clean repo **in place** and continues when one repo cannot move. A repo on `develop` fast-forwards `origin/develop` and, for product repos, merges the latest stable tag (or `origin/main`). Ops repos on `develop` fast-forward `develop` and merge a stable tag only when a hotfix landed on `main` — not raw `origin/main`. A repo on `feature/*` or `ops/*` stays there and receives `develop`. `release/*` receives only `origin/release/<name>`, so work committed to `develop` after the cut stays off the train. `hotfix/*` and `main` receive `main`. BOM on `main` fast-forwards `origin/main`. Tracked local edits are left untouched and reported as `needs-commit`. Merge conflicts abort that repo only. The summary lists how many repos are still behind and the next step for each. Re-run `git convoy sync` until `remaining` is 0. Do not `git pull` on `main` to start product work.

## Heal develop from main (no idle workspace required)

When `develop` is behind tagged `main` — repo not on the last train, new extension, post-hotfix drift — and you are not doing a full catch-up:

```bash
git convoy --json sync develop
git convoy --json sync develop --repos data,console
```

Merges latest stable tag (or `origin/main`) into `develop` for every product repo. Does not require a fully idle workspace. Same logic as the automatic step in `feature prs`, `train tag-rc`, and `train mergeback`. Re-run after resolving conflicts.

## After editing code

Agents start on `develop`. After you change files:

```bash
git convoy --json feature adopt
```

That creates `feature/<name>` only in repos that changed and resets local `develop` if you committed there. Do not commit feature work onto `develop`.

If `feature/<name>` already exists (you created it, another checkout, or a previous start/adopt), `git convoy --json feature start NAME` checks those branches out and puts them on the sheet **only when they have work** (dirty files on the branch, or commits not in `develop`). Empty leftover branches stay off the sheet. Dirty work already on `feature/<name>` is kept. It still does not create the branch in untouched repos — that is `adopt`. `feature adopt` also drops empty `feature/<name>` participants already on the sheet. Do **not** put `*-bom` on a feature sheet — BOM pins land via `git convoy bom` / `hotfix bom` on `main` (that push deploys).

Then commit on the feature branch. `--json` without `--from` or `--header-only` prints a plan (never a prompt). Fill `header` and each repo `body`, send the same document back.

```bash
git convoy --json feature commit
git convoy --json feature commit --from -
```

Every dirty participant must appear in `repos`. Empty `body` is allowed (header only). `--header-only` with `--header` commits the same subject in every dirty participant. Do not use an interactive `feature commit` loop.

To put commits on GitHub without opening PRs (end of day / backup):

```bash
git convoy --json feature push
```

Uncommitted files are not pushed. Status stays `in-progress`.

## Switching features

```bash
git convoy --json feature switch other-name
```

Refuses if any product repo is dirty. Run `git convoy --json feature commit` first, or stash.

## PRs

```bash
git convoy --json feature prs           # Full: opens PRs
git convoy --json feature prs --no-gh   # Simple: compare URLs only
```

Before opening PRs, merges each participant’s latest stable tag (or `main`) into `develop` so hotfixes and repos that sat out of the last train are absorbed. Conflicts block PR creation — resolve on `develop`, then re-run.

Full mode — approve when CI is green (do not merge until every sibling is approved):

```bash
git convoy --json feature approve
git convoy --json feature approve --force   # skip failing/pending checks
```

Merge order is `renglo-lib` → `renglo-api` → console/extensions. Do not merge a subset. Merge stays in GitHub.

After merges, check status and close the feature:

```bash
git convoy --json feature show
git convoy --json feature close --yes
```

`feature show` reports `committed`, `pending`, `uncommitted`, or `merged` per repo. `committed` means commits exist on the feature branch but no PR yet — run `feature prs`. `uncommitted` is local work that has not been committed yet (the branch tip may still equal `develop`). `pending` means a PR is open or recorded. A `note` field captions the usual next step. `feature close` checks out `develop` and removes feature branches once every participant is merged.

## Ops (operator tooling, parallel to features)

Use for ops tooling that must not ride product trains: launcher, bom-helper, git-convoy, publisher, bootstrap, etc. Repos declare `role = "ops"` in committed `gitconvoy.toml`; `git convoy init` refreshes local `.gitconvoy/ops.toml`. Default for unmarked repos is **product**.

`ops *` is independent of the current feature/train/hotfix. It only touches ops repos. Branch prefix `ops/<name>`. PRs target **`develop`**. **`develop` is the neutral branch**. `ops close` checks out `develop` after PRs merge — no `main` → `develop` step.

Platform release does **not** use a sheet:

```bash
git convoy --json ops release bom-helper
git convoy --json ops release bom-helper --bump minor
git convoy --json ops release bom-helper --verify --wait --pin --bom ops/<system>-bom
```

Flags: `--bump patch|minor|major`, `--pin` / `--pin sha`, `--bom`, `--verify`, `--wait`, `--no-gh`, `--no-push`. Merge any develop→main PR in GitHub, then run again to tag.

```bash
git convoy --json ops start codeartifact-mosaic
git convoy --json ops adopt
git convoy --json ops commit --header "fix: …" --header-only
git convoy --json ops prs
# merge PRs to develop in GitHub
git convoy --json ops show
git convoy --json ops close --yes
```

Do **not** put ops repos on a feature sheet (and vice versa). Dirty product repos are ignored by `ops adopt`; dirty ops repos are ignored by `feature adopt`.

## Publish verification (cycles 3–4, Full mode)

```bash
git convoy --json train verify
git convoy --json train verify --wait
git convoy --json bom --bom ops/<system>-bom                    # verify + self-heal (default)
git convoy --json bom --require-verify --bom ops/<system>-bom    # strict: refuse on failure
git convoy --json bom --no-verify --bom ops/<system>-bom        # Simple heuristic only
```

Run after `tag-rc` or `train publish`. Detects workflows by **v* tag push** trigger in `.github/workflows/` (any filename). Skips repos without such a workflow (console today). Default `bom` clears registry pins for failed publishes and falls back to `repos.*.commit`. `--require-verify` refuses to write the BOM when verify fails.

## Cycles (see README)

- **1–2:** features and local release branches — git only (Full optional).
- **3:** `train tag-rc` syncs develop from stable for participants, then push → `train verify` (Full) or manual Actions → `bom` → push BOM (staging).
- **4:** `train publish` (merge to `main`, tag, then automatic `train mergeback` into `develop` for **all product repos**) → `train verify` (Full) or manual Actions → `bom --production` → push BOM.
  If publish exits non-zero after tagging, or `develop` is behind the stable tag: `git convoy --json train mergeback`.
- **Hotfix** (parallel, not a fifth cycle): production PATCH without a new train. May touch several repos. PRs into `main`. Publish merges tagged `main` into `develop` and absorbs local `feature/*`.

Do not run cycle 3/4 without tenant publisher + BOM setup (README: “Setup for cycles 3 and 4”).

## Production hotfix

Use when production is already on a stable train and you need a PATCH now.

```bash
git convoy --json hotfix start NAME                 # dirty repos, existing hotfix/<name>, or --repos a,b
git convoy --json hotfix commit --header "fix: …" --header-only
git convoy --json hotfix prs                        # PRs into main
# merge those PRs in GitHub
git convoy --json hotfix publish
git convoy --json hotfix bom --bom ops/<system>-bom
```

`hotfix start` branches from `main` and bumps PATCH. Start from `main` or `develop`, not a dirty `feature/*`. If `hotfix/<name>` already exists, start picks it up and does not bump PATCH again. It does not convert `feature/<name>` into a hotfix. `hotfix publish` tags `vX.Y.Z` on `main`, merges into `develop` (and pushes when origin exists), then merges that `develop` into local `feature/*` so in-process work gets the patch. Conflicts are listed; then `git convoy feature refresh`. `hotfix bom` pins **only** those packages on the next BOM patch and points **staging**. It does not enable production. Commit and push the BOM; `bom --production` when staging is acceptable.

## What not to do

- Do not create `feature/<name>` in every repo.
- Do not `git pull` on `main` to start product work; `git convoy sync` updates clean repos in place and reports the rest.
- Do not put ops (tooling) repos on a feature sheet; use `git convoy ops`.
- Do not put `*-bom` on a feature branch or feature PR; deploy only via `bom` on `main`.
- `feature abandon` / `ops abandon` / `hotfix abandon` drop the sheet only. They never delete git branches or uncommitted files. `feature close`, `ops close`, `hotfix close`, and `train close` remove merged branches, and they refuse if that would lose work.
- Do not merge PRs through git-convoy (approve is OK in Full mode).
- Do not query CodeArtifact or invent unpublished pins.
- In Full mode, default `bom` self-heals failed publishes to git SHAs; use `--require-verify` when the BOM must not be written until CI is green.
- Do not run `bom --no-verify` on a real train unless you checked Actions manually.
- Do not increment semver again at publish; drop the rc suffix only.
- Do not skip merging a hotfix back to `develop`; in-process feature branches need that patch.

To put a train onto a running system, two golden paths:

```bash
git convoy --json bom --bom ops/<system>-bom
```

That is the **release** path. Run it after each `train tag-rc`. The first `bom` for a train drafts a new system version (patch bump). Later `bom` runs for the same train refresh pins in that same BOM file — the CLI prints `(refresh)`. If staging fails, go back to cycle 2, tag-rc again, and run `bom` again. Many attempts are fine.

After `train publish`, either run `bom` alone (optional staging smoke-test pause) or go straight to production:

```bash
git convoy --json bom --production --bom ops/<system>-bom
```

That is the **production** path. Run it only after `train publish` (which also runs `train mergeback` into `develop`). If develop is still behind the stable tag, run `git convoy --json train mergeback` and retry. Refreshes stable pins and enables production in one step. Refuses while the train is still stabilizing. After push, CI deploys staging, verifies it, then production — production is blocked if staging fails (watch GitHub Actions or failure notifications).
