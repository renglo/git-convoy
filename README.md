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



## Three cycles

git-convoy is three cycles. They run at different times and they do not substitute for each other.


| Cycle                     | What you move                                         | What you get                 | What you do not get        |
| ------------------------- | ----------------------------------------------------- | ---------------------------- | -------------------------- |
| **1. Daily feature work** | Code on `feature/<name>` → `develop`                  | Merged features on `develop` | Packages, a running system |
| **2. Release trains**     | That `develop` → git tags that the registry publishes | Packages you can install     | A running system           |
| **3. Adoption**           | Those package pins → a BOM (release, then production) | A running system             | New package versions       |


Same shape twice, on purpose. Cycle 2 publishes to the **registry** first as a candidate (`tag-rc`), then as stable (`train publish`). Cycle 3 writes a BOM so a running system can install those packages — a release train onto staging, as many times as you try, and a production train only after the train is stable. Neither one deploys by tagging, and neither one publishes by editing the BOM.

Cycle 3 is not the epilogue of cycle 2. You leave cycle 2 to adopt an rc, go back to cut the next rc, adopt again, and only then — after `train publish` — take the production path. It is its own cycle because the same packages can be pointed at different BOMs, and you can be managing more than one train.

`publish` in this tool always means **the package registry**, never `main` and never production. Merging `main` during `train publish` is bookkeeping so the stable tag has a home. Production is only cycle 3.

---



## Cycle 1 — Daily feature work



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

When those PRs merge, the feature is on `develop`. Cycle 1 is done. Cycle 2 is what turns that `develop` into packages in the registry. Cycle 3 is what points a running system at those packages.

---



## Cycle 2 — Release trains

A **release train** is a coordinated cut of several repositories at the same moment. Features land on `develop` one at a time (cycle 1). A train is the later step that says: take whatever is already on `develop` in each repo, freeze it together, and publish packages to the registry. Repos that did not move since the last stable release stay off the train.

Until you cut, merged features only exist on `develop`. They are not in the registry, and they are not in production.

### Naming a train

The name is yours. git-convoy does not parse it and does not require a date format. It becomes the branch `release/<name>` and the label on the train sheet.

Pick something unique and sortable so humans can tell trains apart. Common choices:

- An ISO week, such as `2026-W34`
- A cutoff date, such as `2026-08-21`
- A milestone you already use, such as `q3-cutover`

Avoid a bare `week-34` (no year) and avoid using a package semver as the train name. The train name is **not** the version of any package. Each repo on the train keeps its own semver (`1.2.4`, `0.0.3`, …). The train name is only the shared trip those versions took together.

The examples below use `2026-W34` because ACME cuts weekly. You could call the same train `august-train` and the commands would work the same.

### Example — ACME, Friday of week 34

ACME used git-convoy all week. Three features, same commands as above:


| Feature                | How they started it                         | Repos on the feature sheet | Friday afternoon                                   |
| ---------------------- | ------------------------------------------- | -------------------------- | -------------------------------------------------- |
| **X** invoice rounding | `git convoy feature start invoice-rounding` | `renglo-lib`, `breakdown`  | Merged to `develop` on Tuesday                     |
| **Y** login timeout    | `git convoy feature start login-timeout`    | `renglo-api`, `console`    | Merged to `develop` on Thursday                    |
| **Z** export CSV       | `git convoy feature start export-csv`       | `schd`                     | Still on `feature/export-csv`. PR open, not merged |


`payload` and `blast-radius` from the earlier examples would look the same: after `feature prs` and a GitHub merge, they sit on `develop` until a train cut picks them up.

Nothing on `develop` this week in `wss`, `data`, or `schd` (Z has not merged). Those repos sit this train out. Their last stable pins stay in the BOM.

### 1. Cut the train

```bash
git convoy train cut 2026-W34
```

git-convoy looks at every product repo and asks: is `develop` ahead of the last stable `vX.Y.Z` tag?

For the ACME example, that means:

- **On the train:** `renglo-lib` and `breakdown` (feature X), `renglo-api` and `console` (feature Y)
- **Not on the train:** `schd` (feature Z is still on `feature/export-csv`), and every other repo that did not move

In each repo that is on the train it creates a`release/2026-W34 branch`, bumps the package one **patch** (override with `--bump minor|major` or `--no-bump`), and writes the rc version (`1.2.4rc1` in Python, `1.2.4-rc.1` in npm). One bump per repo for the whole train — not one bump per feature.

If you need to force a set instead of discovery:

```bash
git convoy train cut 2026-W34 --repos renglo-lib,breakdown
```

Monday, ACME merges feature Z. Too late for `2026-W34`. `schd` will have to wait for the next train (e.g: `2026-W35)`.

### 2. Publish release candidates to the registry

In a single repo you would usually run `git tag`, then `git push origin <tag>`. `tag-rc` does both, in every train participant:

```bash
git convoy train tag-rc
```

For each repo on the train it creates the candidate tag (`v1.2.4-rc.1`, each repo its own number), then pushes the `release/<name>` branch **and** that tag to origin. The pushed tag is what CI publishes to the registry. There is no separate “now push the tags” step.

`--no-push` tags locally and does not push. Use that only if you want to inspect first.

On the release branch after this: bugfixes only. No new features.

This is the candidate half of cycle 2. To try those rcs on a running system, leave this cycle and take the **release** golden path in cycle 3. If staging is wrong, come back here: fix on the release branch, merge the fix back to `develop`, run `tag-rc` again (`v1.2.4-rc.2`), and adopt again. That loop can run as many times as you need. Feature Z is not in these packages.

### Looking at the train sheet

```bash
git convoy train show
```

Read-only. It prints the current train sheet (or `train show NAME`). It does not tag, push, or publish. Run it whenever you want — before `tag-rc`, after, or after `train publish`. After `tag-rc` you should see an `rc_tag` per repo; after `train publish` you should see a `stable_tag`.

### 3. Publish stable packages to the registry

When the last rc of every participant is acceptable, publish the **same numbers** without the rc suffix. This is still the registry, not production.

```bash
git convoy train publish
```

For each participant it drops the rc (`1.2.4rc1` → `1.2.4`), merges `release/<name>` into `main` (so the stable line has a home), tags `v1.2.4`, and pushes `main` plus that tag. The pushed **stable tag** is what CI publishes to the registry as the installable release.

`--no-push` does the local commits, merge, and tag, and does not push.

Both “publishes” in cycle 2 are registry publishes. Production is cycle 3, and only after this command.

Cycle 2 is done when the stable tags are in the registry. A running system is unchanged until you take cycle 3’s **production** golden path.

---



## Cycle 3 — Adoption

After a train ships, the registry has new versions across many repositories. Those packages are not yet in a testing or production system. Adoption is the step that puts them there.

Every target system has its own **BOM** repository (bill of materials) that holds the list of dependencies it installs. That repo can be named anything and live anywhere. Pass `--bom` with a path relative to the workspace, or an absolute path. The examples below use `ops/acme-bom` because that is where this instance keeps it.

If you omit `--bom`, git-convoy scans the workspace for a folder whose name ends in `-bom` (any depth; it skips `node_modules`, venvs, and similar). One match is enough. Several matches (or none) refuse until you pass `--bom`.

The BOM holds:

- One JSON file per **system version** under `bom/` (example: `bom/v1.4.0.json`). That file lists every dependency the system installs: package versions under `python` / `npm`, and (today) git commit SHAs under `repos`. Packages that did not move keep the version they already had.
- `deploy_targets.yml`, which says which of those JSON files staging and production should use.

Example: The system version (`1.4.1`) is not any package’s semver. `renglo-lib` can be `1.2.4` and `schd` can be `2.3.4` inside the same system `1.4.1`.

Without this cycle you would open the current BOM, copy it, and type every new version and SHA from the train into the copy. Miss one and the system installs a mix that never rode the train together. That is a defective release. Cycle 3 writes the BOM so you do not do that by hand.

git-convoy only edits those files. It does not publish packages and it does not `git push` the BOM. After each command, commit and push the BOM repo yourself so CI deploys.

This is its own cycle, not the last page of cycle 2. The same train can be adopted onto more than one BOM, and you can be managing more than one train. You will also leave cycle 3 and go back to cycle 2 more than once.

There are two golden paths. They are not two steps of the same sitting.

### Golden path — Adopt a release train

1. Run this after `git convoy train tag-rc`. The registry has candidates. They are not on any running system until you adopt them.

```bash
git convoy adopt --bom ops/acme-bom
```

Takes the current train and writes the next system version. Staging will install it. Production stays on the previous BOM.

2. Commit and push the BOM repo. CI deploys staging.

```bash
cd ops/acme-bom
git add bom/ deploy_targets.yml
git commit -m "Adopt release train"
git push origin HEAD
```

3. Test staging, look for errors and repeat if needed. If staging shows an error or a bug, go back to cycle 2: fix on the release branch, run `train tag-rc` again, then come back here and `adopt` again. Many attempts are fine. Each adopt writes a new system version from whatever the train sheet now has.

### Golden path — Adopt a production train

1. Run this only after `git convoy train publish` (the release branch is stable). That command is what makes the train stable. Do not use `--production` on a release train (rc).

```bash
git convoy adopt --production --bom ops/acme-bom
```

Aims production at the **same** BOM staging is already running. It does not write a new file and it does not take the train again.

2. Commit and push the BOM again.

```bash
cd ops/acme-bom
git add deploy_targets.yml
git commit -m "Adopt production train"
git push origin HEAD
```

3. Test production, look for errors and open a fix branch if there is something wrong. 



### Optional reading : Internals — draft, pin, and point

You do not need these words to adopt a train. `adopt` and `adopt --production` run them for you.


| Word      | What it changes          | What it means                                                                                           |
| --------- | ------------------------ | ------------------------------------------------------------------------------------------------------- |
| **Draft** | A new `bom/vX.Y.Z.json`  | Copy the current BOM to a new system version. Nothing is deployed. Every version starts as a copy.      |
| **Pin**   | Entries inside that JSON | Set a package to an exact version. “Install this, not latest.” `adopt` pins every package on the train. |
| **Point** | `deploy_targets.yml`     | Tell staging (then production) which BOM file to install. This is what aims the running system.         |


The release path drafts the next system version (patch bump of whatever `deploy_targets.yml` already points at), pins every repo on the current train, and points staging at the new file. The production path points production at that same file — only after `train publish`.

The primitives stay available when you are not taking a whole train — one package, a pin-back, or a system version you want to name yourself:

```bash
git convoy adopt draft --from 1.4.0 --to 1.4.1 --bom ops/acme-bom
git convoy adopt pin 1.4.1 renglo-lib 1.2.5 --bom ops/acme-bom
git convoy adopt point 1.4.1 --bom ops/acme-bom
```

Pass `--train NAME` to `adopt` if the train you want is not the current one. `--from` / `--to` override the automatic system-version bump.

Rollback is `adopt point` at the previous system version, then commit and push. The newer file stays on disk.

---



## Commands


| Command                          | What it does                               |
| -------------------------------- | ------------------------------------------ |
| `git convoy init`                | State file, gitignore, Cursor skill        |
| `git convoy status`              | Current feature, train, dirty repos        |
| `git convoy feature start NAME`  | Empty sheet; checkout `develop`            |
| `git convoy feature adopt`       | Branch changed repos onto `feature/NAME`   |
| `git convoy feature abandon`     | Delete local `feature/<name>` (lossy)      |
| `git convoy feature commit`      | Commit dirty participants                  |
| `git convoy feature push`        | Push `feature/<name>` to origin (no PRs)   |
| `git convoy feature switch NAME` | Checkout that feature’s repos              |
| `git convoy feature refresh`     | Merge `origin/develop` into participants   |
| `git convoy feature prs`         | Push and open PRs                          |
| `git convoy feature show [NAME]` | Feature sheet                              |
| `git convoy train cut NAME`      | Cut `release/NAME` on changed repos        |
| `git convoy train tag-rc`        | Tag `vX.Y.Z-rc.N` and push (registry rc)   |
| `git convoy train publish`       | Stable tag + push (registry release)       |
| `git convoy train show [NAME]`   | Read the train sheet (no git writes)       |
| `git convoy adopt`               | Adopt a release train onto a BOM (staging) |
| `git convoy adopt --production`  | Adopt a production train (after publish)   |
| `git convoy adopt draft`         | Copy last good BOM to a new system version |
| `git convoy adopt pin`           | Set one package version in that draft      |
| `git convoy adopt point`         | Aim staging (or production) at a BOM file  |


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
git convoy --json adopt --bom ops/<system>-bom
git convoy --json adopt --production --bom ops/<system>-bom
```

`init` installs a Cursor skill (`.cursor/skills/gitconvoy/SKILL.md`) that tells the agent to do this. After editing code, run `git convoy --json feature adopt`, then `git convoy --json feature commit` (plan) and `--from` (apply). Use `feature push` to back up branches without PRs. Do not commit feature work on `develop`.

---



## What this tool will not do

- Approve or merge GitHub PRs
- Talk to CodeArtifact or invent unpublished pins
- Create a `feature/*` branch in every repo
- Replace staging as the compatibility check

Those steps stay human (or a later tool). The process authority remains [cross-repo-feature-manual.md](cross-repo-feature-manual.md).