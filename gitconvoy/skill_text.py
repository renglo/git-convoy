SKILL_MARKDOWN = """---
name: gitconvoy
description: >-
  Operate the git-convoy CLI for cross-repo features, release trains, hotfixes,
  and BOM adoption. Use when the user mentions git convoy, git-convoy, gitconvoy,
  a feature sheet, a release train, a production hotfix, which repos a feature
  touches, what is on the current train, adopt onto a feature branch, commit
  participant repos, refresh from develop, or staging/production pins.
---

# git-convoy

Authority process: `ops/docs/cross-repo-feature-manual.md`.
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
git convoy --json feature show
git convoy --json train show
git convoy --json hotfix show
git convoy --json feature commit
```

- "What's on the current train?" → `git convoy --json train show`
- "How many repos is this feature touching?" → `git convoy --json feature show` (`repo_count`)
- "Which feature am I on?" → `git convoy --json status`
- "Which hotfix am I on?" → `git convoy --json status` / `git convoy --json hotfix show`

Do not guess membership by scanning dirty directories. The state file is `.gitconvoy/state.json` (gitignored).

## After editing code

Agents start on `develop`. After you change files:

```bash
git convoy --json feature adopt
```

That creates `feature/<name>` only in repos that changed and resets local `develop` if you committed there. Do not commit feature work onto `develop`.

If `feature/<name>` already exists (you created it, another checkout, or a previous start/adopt), `git convoy --json feature start NAME` checks those branches out and puts them on the sheet **only when they have work** (dirty files on the branch, or commits not in `develop`). Empty leftover branches stay off the sheet. Dirty work already on `feature/<name>` is kept. It still does not create the branch in untouched repos — that is `adopt`. `feature adopt` also drops empty `feature/<name>` participants already on the sheet.

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

`feature show` reports `pending`, `uncommitted`, or `merged` per repo. `uncommitted` is local work that has not been committed yet (the branch tip may still equal `develop`). `feature close` checks out `develop` and removes feature branches once every participant is merged.

## Publish verification (cycles 3–4, Full mode)

```bash
git convoy --json train verify
git convoy --json train verify --wait
git convoy --json adopt --bom ops/<system>-bom                    # verify + self-heal (default)
git convoy --json adopt --require-verify --bom ops/<system>-bom    # strict: refuse on failure
git convoy --json adopt --no-verify --bom ops/<system>-bom        # Simple heuristic only
```

Run after `tag-rc` or `train publish`. Detects workflows by **v* tag push** trigger in `.github/workflows/` (any filename). Skips repos without such a workflow (console today). Default adopt clears registry pins for failed publishes and falls back to `repos.*.commit`. `--require-verify` refuses to write the BOM when verify fails.

## Cycles (see README)

- **1–2:** features and local release branches — git only (Full optional).
- **3:** `train tag-rc` (push) → `train verify` (Full) or manual Actions → `adopt` → push BOM (staging).
- **4:** `train publish` (merge to `main`, tag, then `train mergeback` into `develop`) → `train verify` (Full) or manual Actions → `adopt --production` → push BOM.
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
git convoy --json hotfix adopt --bom ops/<system>-bom
```

`hotfix start` branches from `main` and bumps PATCH. Start from `main` or `develop`, not a dirty `feature/*`. If `hotfix/<name>` already exists, start picks it up and does not bump PATCH again. It does not convert `feature/<name>` into a hotfix. `hotfix publish` tags `vX.Y.Z` on `main`, merges into `develop` (and pushes when origin exists), then merges that `develop` into local `feature/*` so in-process work gets the patch. Conflicts are listed; then `git convoy feature refresh`. `hotfix adopt` pins **only** those packages on the next BOM patch and points **staging**. It does not enable production. Commit and push the BOM; `adopt --production` when staging is acceptable.

## What not to do

- Do not create `feature/<name>` in every repo.
- Do not abandon a feature unless the user wants that work discarded.
- Do not merge PRs through git-convoy (approve is OK in Full mode).
- Do not query CodeArtifact or invent unpublished pins.
- In Full mode, default `adopt` self-heals failed publishes to git SHAs; use `--require-verify` when the BOM must not be written until CI is green.
- Do not adopt with `--no-verify` on a real train unless you checked Actions manually.
- Do not increment semver again at publish; drop the rc suffix only.
- Do not skip merging a hotfix back to `develop`; in-process feature branches need that patch.

To put a train onto a running system, two golden paths:

```bash
git convoy --json adopt --bom ops/<system>-bom
```

That is the **release** path. Run it after each `train tag-rc`. The first adopt for a train drafts a new system version (patch bump). Later adopts for the same train refresh pins in that same BOM file — the CLI prints `(refresh)`. If staging fails, go back to cycle 2, tag-rc again, and adopt again. Many attempts are fine.

After `train publish`, either run `adopt` alone (optional staging smoke-test pause) or go straight to production adopt:

```bash
git convoy --json adopt --production --bom ops/<system>-bom
```

That is the **production** path. Run it only after `train publish` (which also runs `train mergeback` into `develop`). If develop is still behind the stable tag, run `git convoy --json train mergeback` and retry. Refreshes stable pins and enables production in one step. Refuses while the train is still stabilizing. After push, CI deploys staging, verifies it, then production — production is blocked if staging fails (watch GitHub Actions or failure notifications).
"""
