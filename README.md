# git-convoy

## Cross Repository Feature LifeCycle Management

`git-convoy` is a CLI that runs the [cross-repo feature manual](cross-repo-feature-manual.md) for you. It only uses `git` (and optionally `gh` if you already have it). Approvals stay in the GitHub UI.

State lives in `.gitconvoy/state.json` at the workspace root. That directory is gitignored. It is local to your machine.

---

## Install

From a clone of this repository (or from a Renglo Installation that vendors it at `ops/git-convoy`):

```bash
cd git-convoy   # or: cd ops/git-convoy
./setup_venv.sh
source gitconvoy-venv/bin/activate
```

That creates `gitconvoy-venv`, installs the CLI in editable mode (plus dev deps for tests), and puts `git-convoy` on your `PATH` while the venv is active. Git then treats that binary as a subcommand, so `git convoy status` is the same as `git-convoy status`. `gitconvoy` is installed as a second name for the same program.

`git convoy --help` asks Git for a man page. Use `git-convoy --help` or `gitconvoy --help`.

Or manually:

```bash
cd git-convoy   # or: cd ops/git-convoy
python3 -m venv gitconvoy-venv
source gitconvoy-venv/bin/activate
pip install -e ".[dev]"
```

Alternatively, install globally with pipx (no venv to activate):

```bash
pipx install -e /path/to/git-convoy
```

You need `git` on `PATH`. `gh` is optional (used only by `feature prs`).

---



## One-time setup

Run this once per workspace (root, or your own multi-repo folder):

```bash
cd /path/to/installation_root
git convoy init
```

That command:

- Discovers git repos under `console/`, `dev/`, `extensions/`, and `ops/`
- Writes `.gitconvoy/state.json`
- Adds `.gitconvoy/` to the workspace `.gitignore`
- Writes `.cursor/skills/gitconvoy/SKILL.md` so Cursor agents know to call `git convoy`

```bash
git convoy status
git convoy --json status
```

`--workspace` overrides discovery if you are not in the workspace root.

---



## Daily feature work



### 1. Start a feature

```bash
git convoy feature start blast-radius
```

Creates an empty feature sheet, sets it current, and checks out `develop` in every clean product repo. It does **not** create `feature/blast-radius` yet.

### 2. Implement

Edit code (or let an agent edit). Work happens on `develop`. That is expected.

### 3. Adopt changed repos

```bash
git convoy feature adopt
```

For each product repo that is dirty or has local commits on `develop` that are not on `origin/develop`:

- Creates or checks out `feature/<name>`
- If you committed on `develop` (and did not push it), resets local `develop` to `origin/develop`
- Adds the repo to the feature sheet

Repos you did not touch are left alone.

To throw away a test or abandoned feature (**deletes the branch and that work**):

```bash
git convoy feature abandon
git convoy feature abandon blast-radius --yes
```

Checks out `develop` and deletes local `feature/<name>`. Does not touch origin unless you pass `--remote`. `--json` requires `--yes`.

### 4. Commit

Dirty work stays uncommitted until you say so. `feature prs` does not commit.

On a terminal, a colored diff (green add, red remove), then a double rule asking what changed in that repo. Empty body = header only. `.` reuses the previous body. `e` edits the header. Before each `git commit`: `This is going to commit to the repo. Continue? :` (`yes` / `no`). `no` skips that repo.

```bash
git convoy feature commit
```

Agents use the same JSON document twice: plan, fill `header` and each `body`, apply. `--json` without `--from` / `--header-only` is always a plan (never a prompt). Every dirty participant must be listed. Extra or missing ids refuse the whole batch before the first `git commit`.

```bash
git convoy --json feature commit
git convoy --json feature commit --from -          # stdin: filled plan
git convoy --json feature commit --from plan.json
git convoy --json feature commit --header "feat: …" --header-only
```

`--header` alone still prints a plan (header prefilled). `--diff` adds patches to the plan. Only participant repos on `feature/<name>` are committed (`git add -A`). Dirty product repos not on the sheet: run `feature adopt` first.

### 5. Push the feature branch (no PRs)

End of day, or anytime you want the commits on GitHub without asking for review:

```bash
git convoy feature push
```

Pushes `feature/<name>` to `origin` for every participant. Does **not** open PRs. Uncommitted files stay local (commit first if you need them on the remote). `feature prs` also pushes; use `push` when the feature is not ready.

### 6. Switch to another feature

Commit or stash first. Then:

```bash
git convoy feature switch payload
```

Checks out `feature/payload` in that feature’s repos and `develop` everywhere else. Refuses if any product repo is dirty.

Come back with `git convoy feature switch blast-radius`.

### 7. Refresh from `develop`

```bash
git convoy feature refresh
```

Merges `origin/develop` into each participant. Stops if a conflict appears; you resolve it, then run refresh again.

### 8. Open PRs

```bash
git convoy feature prs
```

Pushes each participant branch (same as `feature push`). If `gh` is logged in, opens PRs onto `develop` and stores the URLs. Otherwise it prints compare links.

Approve and merge **in GitHub**. Merge only when every sibling PR is approved, in this order: `renglo-lib` → `renglo-api` → console and extensions. `git-convoy` does not approve or merge.

```bash
git convoy feature show
```

---



## Release trains

A train name is a label (`2026-W34`), not a package version.

```bash
git convoy train cut 2026-W34
```

Includes only product repos whose `develop` is ahead of the last stable `vX.Y.Z` tag. Creates `release/2026-W34`, bumps each package one **patch** (override with `--bump minor|major` or `--no-bump`), and writes the rc version (`1.2.4rc1` / `1.2.4-rc.1`).

Force a set:

```bash
git convoy train cut 2026-W34 --repos renglo-lib,breakdown
```

Tag and push release candidates:

```bash
git convoy train tag-rc
```

Creates `v1.2.4-rc.1` and pushes the release branch plus the tag. That tag is what publishes to the registry.

When the train is stable:

```bash
git convoy train publish
```

Drops the rc (same number — it does not increment), merges `release/<train>` into `main` in merge order, tags `v1.2.4`, and pushes. Use `--no-push` to do everything locally first.

```bash
git convoy train show
```

---



## Adoption (BOM)

These commands only edit files in a `*-bom` repo. They do **not** push. You commit and push that repo yourself so CI deploys.

```bash
git convoy adopt draft --from 1.4.0 --to 1.5.0 --train 2026-W34
git convoy adopt pin 1.5.0 renglo-lib 1.2.4
git convoy adopt point 1.5.0
```

`point` writes `bom: 1.5.0` in `deploy_targets.yml` and sets `production.enabled: false`. When staging is green:

```bash
git convoy adopt point 1.5.0 --production
```

Then commit and push `*-bom`. Rollback is `git convoy adopt point 1.4.0 --production` (or edit `bom:` by hand). The previous JSON file stays on disk.

If the workspace has more than one `ops/*-bom` folder, pass `--bom ops/stanley-bom`.

---



## Commands


| Command                        | What it does                             |
| ------------------------------ | ---------------------------------------- |
| `git convoy init`                | State file, gitignore, Cursor skill      |
| `git convoy status`              | Current feature, train, dirty repos      |
| `git convoy feature start NAME`  | Empty sheet; checkout `develop`          |
| `git convoy feature adopt`       | Branch changed repos onto `feature/NAME` |
| `git convoy feature abandon`     | Delete local `feature/<name>` (lossy)    |
| `git convoy feature commit`      | Commit dirty participants                |
| `git convoy feature push`        | Push `feature/<name>` to origin (no PRs) |
| `git convoy feature switch NAME` | Checkout that feature’s repos            |
| `git convoy feature refresh`     | Merge `origin/develop` into participants |
| `git convoy feature prs`         | Push and open PRs                        |
| `git convoy feature show [NAME]` | Feature sheet                            |
| `git convoy train cut NAME`      | Cut `release/NAME` on changed repos      |
| `git convoy train tag-rc`        | Tag `vX.Y.Z-rc.N`                        |
| `git convoy train publish`       | Drop rc, merge `main`, stable tag        |
| `git convoy train show [NAME]`   | Train sheet                              |
| `git convoy adopt draft`         | Copy a version object                    |
| `git convoy adopt pin`           | Set one pin                              |
| `git convoy adopt point`         | Point `deploy_targets.yml`               |


Global flags: `--json`, `--workspace PATH`.

---



## For coding agents

Add `--json` to every command you need to read.

```bash
git convoy --json status
git convoy --json feature show
git convoy --json train show
git convoy --json feature commit
git convoy --json feature push
```

`init` installs a Cursor skill (`.cursor/skills/gitconvoy/SKILL.md`) that tells the agent to do this. After editing code, run `git convoy --json feature adopt`, then `git convoy --json feature commit` (plan) and `--from` (apply). Use `feature push` to back up branches without PRs. Do not commit feature work on `develop`.

---



## What this tool will not do

- Approve or merge GitHub PRs
- Talk to CodeArtifact or invent unpublished pins
- Create a `feature/*` branch in every repo
- Replace staging as the compatibility check

Those steps stay human (or a later tool). The process authority remains [cross-repo-feature-manual.md](cross-repo-feature-manual.md).