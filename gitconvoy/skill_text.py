SKILL_MARKDOWN = """---
name: gitconvoy
description: >-
  Operate the git-convoy CLI for cross-repo features, release trains, and
  BOM adoption. Use when the user mentions git convoy, git-convoy, gitconvoy,
  a feature sheet, a release train, which repos a feature touches, what is on
  the current train, adopt onto a feature branch, commit participant repos,
  refresh from develop, or staging/production pins.
---

# git-convoy

Authority process: `ops/docs/cross-repo-feature-manual.md`.
CLI manual: `ops/git-convoy/README.md`.

Prefer `git convoy` over raw git for any step that spans more than one repo.

## Ask the CLI first

Run from the workspace root (or pass `--workspace`). Always add `--json` when you need to answer a question.

```bash
git convoy --json status
git convoy --json feature show
git convoy --json train show
git convoy --json feature commit
```

- "What's on the current train?" → `git convoy --json train show`
- "How many repos is this feature touching?" → `git convoy --json feature show` (`repo_count`)
- "Which feature am I on?" → `git convoy --json status`

Do not guess membership by scanning dirty directories. The state file is `.gitconvoy/state.json` (gitignored).

## After editing code

Agents start on `develop`. After you change files:

```bash
git convoy --json feature adopt
```

That creates `feature/<name>` only in repos that changed and resets local `develop` if you committed there. Do not commit feature work onto `develop`.

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
git convoy --json feature prs
```

Opens PRs (or prints compare URLs). Approve and merge in the GitHub UI. Merge order is `renglo-lib` → `renglo-api` → console/extensions. Do not merge a subset.

After merges, check status and close the feature:

```bash
git convoy --json feature show
git convoy --json feature close --yes
```

`feature show` reports `pending` vs `merged` per repo. `feature close` checks out `develop` and removes feature branches once every participant is merged.

## What not to do

- Do not create `feature/<name>` in every repo.
- Do not abandon a feature unless the user wants that work discarded.
- Do not approve or merge PRs through git-convoy.
- Do not query CodeArtifact or invent unpublished pins.
- Do not increment semver again at publish; drop the rc suffix only.

To put a train onto a running system, two golden paths:

```bash
git convoy --json adopt --bom ops/<system>-bom
```

That is the **release** path. Run it after each `train tag-rc`. If staging fails, go back to cycle 2, tag-rc again, and adopt again. Many attempts are fine.

```bash
git convoy --json adopt --production --bom ops/<system>-bom
```

That is the **production** path. Run it only after `train publish`. Do not invent pins; do not push the BOM (the operator commits and pushes).
"""
