# git-convoy

## Cross Repository Feature LifeCycle Management

`git-convoy` is a CLI that runs the [cross-repo feature manual](cross-repo-feature-manual.md) for you. It works in two modes — **Simple** (git only) or **Full** (git + GitHub via `gh`) — see below. Cycles 3 and 4 also need your tenant’s **publisher** (CodeArtifact) and **BOM** repos configured.

State lives in `.gitconvoy/state.json` at the workspace root. That directory is gitignored. It is local to your machine.

---

## Simple vs Full mode

| | **Simple** | **Full** |
| --- | --- | --- |
| **Requires** | `git` on `PATH` | `git` + [`gh`](https://cli.github.com/) logged in (or `GH_TOKEN`) |
| **Cycle 1 — push feature branch** | `feature push` | same |
| **Cycle 1 — open PRs** | `feature prs --no-gh` prints compare URLs; you open PRs in the browser | `feature prs` opens PRs and stores URLs on the feature sheet |
| **Cycle 1 — merge status** | `feature show` uses git (tip in `develop`, tree clean); dirty → `uncommitted` | `feature show` uses `gh` — accurate with squash merges |
| **Cycle 1 — approve PRs** | GitHub UI | `feature approve` (Full; uses the same `gh` connection) |
| **Cycles 3–4 — publish CI** | Watch Actions on each repo manually | `train verify` checks publish workflow status per participant (Full) |

**Simple mode** is enough for cycles 1–2 (features and local release trains). No GitHub token, no `gh` install.

**Full mode** is for release managers who live in GitHub: open and approve sibling PRs from the terminal, and confirm publish workflows succeeded after `tag-rc` / `train publish` before adopting. Full mode does **not** require an AWS profile — publish verification goes through GitHub Actions (the same path CI uses to reach CodeArtifact). That scales to trains with repos from many publishers: each repo’s workflow is on GitHub; AWS stays inside each publish job.

Cycles 1–2 never need CodeArtifact or a BOM. Full mode is optional there too — it only adds convenience.

### Setting up Full mode

1. **Install `gh`** — [cli.github.com](https://cli.github.com/) or `brew install gh` on macOS.

2. **Log in** (interactive, on your laptop):

   ```bash
   gh auth login
   ```

   Choose GitHub.com, HTTPS, and authenticate in the browser. Pick the account that can reach every org on your trains (e.g. `renglo/*` plus extension vendors).

3. **Verify**:

   ```bash
   gh auth status
   ```

   You should see `Logged in to github.com`. Optionally smoke-test a train repo:

   ```bash
   gh run list --repo renglo/renglo-lib --limit 3
   ```

4. **Non-interactive use** (agents, scripts, CI) — set a token `gh` will pick up:

   ```bash
   export GH_TOKEN=ghp_...   # or GITHUB_TOKEN
   ```

   Use a [fine-grained PAT](https://github.com/settings/tokens?type=beta) or classic PAT with access to every participant repo. Suggested scopes:

   | Scope | Used for |
   | ----- | -------- |
   | **Contents** (read) | clone metadata, tags |
   | **Pull requests** (read + write) | open PRs, approve (`feature approve`) |
   | **Actions** (read) | `train verify` — workflow conclusions after tag push |
   | **Metadata** (read) | always required on fine-grained tokens |

   For classic PATs, `repo` covers private repos (broader than ideal but common for release managers).

5. **Multi-org trains** — one login must see **all** participant repos (core, console, extensions, vendor orgs). If `gh run list --repo vendor/acme-ext` fails with “Not Found”, fix org membership or token scope before relying on Full mode.

6. **Force Simple behavior** even when `gh` is installed:

   ```bash
   git convoy feature prs --no-gh
   ```

Merge stays in GitHub (or your policy): Full mode approves and verifies CI; it does **not** merge PRs.

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

For command sequences by cycle (reduced README, no concepts):

```bash
git convoy help
git convoy --json help
```

Or manually:

```bash
cd git-convoy   # or: cd ops/git-convoy
python3 -m venv gitconvoy-venv
source gitconvoy-venv/bin/activate
pip install --isolated --index-url https://pypi.org/simple -e ".[dev]"
```

Alternatively, install globally with pipx (no venv to activate):

```bash
pipx install --pip-args '--isolated --index-url https://pypi.org/simple' -e /path/to/git-convoy
```

You need `git` on `PATH`. For **Full mode**, install and log in to `gh` (see [Simple vs Full mode](#simple-vs-full-mode)).

---

## One-time setup (Cycle 1)

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

### Start of a work session (`git convoy sync`)

After a few days away, before you start a feature: fetch every clone, put product repos on **`develop`** (not `main`), create `develop` from `main` if the clone has none, fast-forward `origin/develop` (other people’s merged features), and merge the latest stable tag / `main` (hotfixes). BOM repos stay on `main`.

The workspace must be **idle**. The command refuses if anything is dirty, if a feature/hotfix/aux sheet still has in-progress work, if a train is still `cut`/`stabilizing`, or if you are sitting on a `feature/*` / `hotfix/*` / `aux/*` / `release/*` branch that has commits not in `develop`.

```bash
git convoy sync
git convoy sync --no-push    # local only; do not push develop
```

You end on `develop`, ready for `feature start` / implement. Do not `git pull` on `main` to “get latest” for product work.

If you already have an in-progress feature, this is the wrong command: `git convoy feature refresh` instead.

### Heal `develop` from `main` (any time)

When `develop` has fallen behind tagged `main` — for example a repo was not on the last train, or you added a new extension after publish — merge stable back into `develop` without requiring an idle workspace:

```bash
git convoy sync develop
git convoy sync develop --repos data,console
git convoy sync develop --no-push    # local merge only
```

For each product repo: fetch, create ``develop`` from ``main`` if it is missing, fast-forward local `main` **without checking it out**, check out `develop`, fast-forward `origin/develop`, merge the latest `v*` stable tag (or `origin/main` if none), push `origin/develop` when the remote exists. BOM repos stay on `main`. Continues past per-repo failures; re-run after resolving conflicts. Same logic used automatically by `feature prs`, `train tag-rc`, and `train publish` / `train mergeback`. Bare `git convoy sync` uses this after the idle check.

No AWS, CodeArtifact, or BOM setup is required for Cycles 1–2.

---

## Four cycles

git-convoy is four cycles. They run at different times and they do not substitute for each other. **Stop when you have what you need** — you do not have to run all four.


| Cycle | What you move | What you get | Requires registry / BOM? |
| ----- | ------------- | ------------ | ------------------------ |
| **1. Daily feature work** | Code on `feature/<name>` → `develop` | Merged features on `develop` | No |
| **2. Release trains (local)** | `develop` → `release/<name>` branches; stabilize in git | A coherent release branch set, rc versions in git | No |
| **3. Staging adoption** | Pushed rc tags → registry; train → staging BOM | Packages in CodeArtifact; staging runs the train | Yes |
| **4. Production release** | Stable tags → registry; BOM → production | Production runs the stable train | Yes |

**Boundaries**

- **Cycle 2 → 3:** the first **`train tag-rc` that pushes** tags to origin. That triggers CI publish workflows. In **Simple** mode, watch GitHub Actions manually before adopting. In **Full** mode, run `train verify` (same `gh` connection as PRs).
- **Cycle 3 → 4:** **`train publish`** (stable registry) then **`adopt --production`**. Production is never enabled by `adopt` alone until you run the production adopt path in cycle 4.

`train publish` in this tool means **stable packages in the registry** (git merge to `main` + stable tag + merge tagged `main` back to `develop` + CI). It is **not** the same as enabling production on the BOM — that is cycle 4.

**Hotfix** is a parallel path, not a fifth cycle. Use it when production is already on a stable train and you need a PATCH in one or more repos without waiting for the next cut. See [Hotfix](#hotfix--production-emergency).

---

## Cycle 1 — Daily feature work

At the beginning of cycle 1, run `git convoy sync` so every product repo is on current `develop` (other people’s merged features and hotfixes). The workspace must be idle. If a feature is already in progress, use `git convoy feature refresh` instead. Details: [Start of a work session](#start-of-a-work-session-git-convoy-sync).

```bash
git convoy sync
```

### 1. Start a feature

```bash
git convoy feature start blast-radius
```

Creates an empty feature sheet, sets it current, and checks out the integration branch (`develop`, or `main` when a repo has no `develop`) in every clean feature repo that does **not** already have `feature/blast-radius`.

If `feature/blast-radius` already exists locally or on origin (you created it yourself, another machine, or a previous `start`/`adopt`), `feature start` checks that branch out and adds the repo to the sheet **only when it has work**: uncommitted files on that branch, or commits not already in `develop`. Empty leftover branches (created and then emptied) are left off the sheet; a clean checkout is returned to `develop`. Dirty work already on `feature/blast-radius` is kept. Dirty work on another branch is skipped (the existing feature branch is left as-is). It does **not** create `feature/blast-radius` in repos that have no such branch yet — that is `feature adopt`.

Feature repos are `console/`, `dev/*`, `extensions/*`, and tenant ops under `ops/` (`bootstrap`, `<tenant>-wl`, …). **`*-bom` is not a feature repo** — BOM pins land via `git convoy adopt` / `hotfix adopt` on `main` (that push deploys). Platform tooling in `ops/` (`publisher`, `launcher`, `extensions-service`, `git-convoy`) is also excluded. Release trains still only cut product repos.

### 2. Implement

Edit code (or let an agent edit). Work happens on `develop`. That is expected.

### 3. Adopt changed repos

```bash
git convoy feature adopt
```

For each feature repo that is dirty, has local commits on its integration branch that are not on `origin/<integration>`, or already has `feature/<name>` with unique commits:

- Creates or checks out `feature/<name>`
- If you committed on `develop` (and did not push it), resets local `develop` to `origin/develop`
- Adds the repo to the feature sheet

Empty `feature/<name>` branches (no unique commits, clean tree) are not added. If they were already on the sheet, `adopt` drops them and checks out `develop`. Repos you did not touch are left alone.

### 4. Commit

Dirty work stays uncommitted until you say so. `feature prs` does not commit.

On a terminal, a colored diff (green add, red remove), then a double rule asking what changed in that repo. Large diffs are shown one page at a time (~terminal height); press Enter for the next page or `s` to skip the rest and continue. Empty body = header only. `.` reuses the previous body. `e` edits the header. Before each `git commit`: `This is going to commit to the repo. Continue? :` (`yes` / `no`). `no` skips that repo.

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

### 5. Open PRs

```bash
git convoy feature prs          # Full: opens PRs via gh
git convoy feature prs --no-gh  # Simple: compare URLs only
```

Pushes each participant branch (same as `feature push` in the [annex](#annex--optional-cycle-1-commands)). **Before opening PRs**, merges each participant’s latest stable tag (or `main`) into `develop` so hotfix tags and repos that sat out of the last train are absorbed — conflicts surface here, not on the train. With **Full** mode (`gh` logged in, no `--no-gh`), opens PRs onto `develop` and stores the URLs. In **Simple** mode, prints compare links for you to open in the browser.

### 6. Approve PRs (Full mode)

When every sibling PR is ready and CI is green, approve the whole set from the terminal:

```bash
git convoy feature approve
```

Uses the same `gh` login as `feature prs`. Merge only when **every** sibling PR is approved, in this order: `renglo-lib` → `renglo-api` → console and extensions. `git-convoy` does not merge — merge in GitHub (or your org’s policy) after approval.

In **Simple** mode, approve in the GitHub UI instead.

```bash
git convoy feature show
```

Each participant shows `committed`, `pending`, `uncommitted`, or `merged`. `committed` means the feature branch has commits not yet in `develop` and no PR yet — next step is usually `feature prs`. `uncommitted` means the feature branch has local changes that are not commits — the tip may still equal `develop`, so git would otherwise look merged. `pending` means a PR is open (or recorded on the sheet). When every participant is merged, status becomes `merged` (`N/N merged` in the header). **Full** mode uses `gh` (works with squash merges). **Simple** mode checks whether the feature branch tip is contained in `develop`, and only after the tree is clean.

### 7. Close the feature

After every PR is merged:

```bash
git convoy feature close
git convoy feature close console-whitelabel-v1 --yes
```

Checks out `develop`, pulls `origin/develop`, deletes local `feature/<name>`, and removes the feature sheet. Refuses if any participant is still `committed`, `pending`, or `uncommitted`. Pass `--remote` to delete `origin/feature/<name>` too. `--keep-branch` leaves local feature branches in place. `--json` requires `--yes`.

To throw away the sheet without touching git, run `feature abandon`. It does not delete branches or files.

When those PRs merge, the feature is on `develop`. Cycle 2 turns that `develop` into release branches.

### Annex — Optional Cycle 1 commands

These are useful but not on the golden path. Skip them until you need them.

#### Push the feature branch (no PRs)

End of day, or anytime you want the commits on GitHub without asking for review:

```bash
git convoy feature push
```

Pushes `feature/<name>` to `origin` for every participant. Does **not** open PRs. Uncommitted files stay local (commit first if you need them on the remote). `feature prs` also pushes; use `push` when the feature is not ready.

#### Switch to another feature

Commit or stash first. Then:

```bash
git convoy feature switch payload
```

Checks out `feature/payload` in that feature’s repos and `develop` everywhere else. Refuses if any product repo is dirty.

Come back with `git convoy feature switch blast-radius`.

#### Refresh from `develop`

```bash
git convoy feature refresh
```

Merges `origin/develop` into each participant. Stops if a conflict appears; you resolve it, then run refresh again.

#### Abandon (sheet only)

Drops the feature sheet. **Does not delete git branches or uncommitted files.** `--json` requires `--yes`.

```bash
git convoy feature abandon
git convoy feature abandon blast-radius --yes
```

You stay on `feature/<name>` with your files. The only command that deletes git branches is `git convoy train delete --yes`.

---

## Cycle 2 — Release trains (local)

A **release train** is a coordinated cut of several repositories at the same moment. Features land on `develop` one at a time (cycle 1). Cycle 2 freezes whatever is on `develop` in each repo onto **`release/<name>`** and lets the release manager stabilize **in git only**.

Until you cut, merged features only exist on `develop`. Nothing is in a registry or a running system.

**This cycle is universal.** It does not need CodeArtifact, a BOM, or Full mode. You can repeat cut → fix → recut many times before you ever enter cycle 3.

### Naming a train

The name is yours. git-convoy does not parse it and does not require a date format. It becomes the branch `release/<name>` and the label on the train sheet.

Pick something unique and sortable. Common choices: `2026-W34`, `2026-08-21`, `q3-cutover`. Avoid a bare `week-34` (no year). The train name is **not** any package’s semver.

The examples below use `2026-W34`.

### Example — ACME, Friday of week 34

| Feature | Repos on the feature sheet | Friday afternoon |
| ------- | -------------------------- | ---------------- |
| **X** invoice rounding | `renglo-lib`, `breakdown` | Merged to `develop` |
| **Y** login timeout | `renglo-api`, `console` | Merged to `develop` |
| **Z** export CSV | `schd` | Still on `feature/export-csv` |

Nothing on `develop` for `schd` (Z has not merged). That repo sits this train out.

### 1. Cut the train

```bash
git convoy train cut 2026-W34
```

For each product repo whose integration branch (`develop`, or `main` when there is no `develop`) is ahead of its last stable tag, creates `release/2026-W34`, bumps one **patch** (override with `--bump minor|major` or `--no-bump`), and writes rc versions (`1.2.4rc1` / `1.2.4-rc.1`). Repos without `pyproject.toml` or `package.json` are skipped automatically.

```bash
git convoy train cut 2026-W34 --repos renglo-lib,breakdown
```

### 2. Stabilize on the release branch

Fix bugs on `release/<name>`. Bugfixes only — no new features. Commit in each participant repo as usual (`git commit`). Merge fixes back to `develop` when appropriate so the next train does not lose them.

To add a product repo that was left off the cut (dirty work on `develop`/`main`, or a named clean repo), without bumping versions:

```bash
git convoy train adopt
git convoy train adopt --repos console,lab
```

Creates or checks out `release/<name>` from the current integration branch and adds the repo to the train sheet. Refuses dirty work on `feature/*` (or any other branch). Ignores aux and BOM.

Commit stabilize work through convoy — do not leave the tool to guess which repos are dirty:

```bash
git convoy train commit
git convoy train commit --header "fix: …" --header-only
```

`train tag-rc` still sets the rc version later. It **refuses** if any train participant is dirty and tells you to run `train commit`.

Repeat **`train cut`** only after **`train delete`** if you need to abandon the cut entirely.

You can inspect the sheet at any time:

```bash
git convoy train show
```

To throw away a botched or abandoned cut:

```bash
git convoy train delete
git convoy train delete 2026-08-29 --yes
```

Deletes local `release/<name>` **only if every commit is already on develop or main**. Refuses if the tree is dirty or the branch has unique commits. Never `reset --hard` / `clean`. Pass `--remote` to delete `origin/release/<name>` too, and only after that same merge check on the origin tip. `--json` requires `--yes`.

### 3. Optional — git-only tags (stay in cycle 2)

If you want version tags and even a local merge to `main` **without** touching the registry:

```bash
git convoy train tag-rc --no-push
git convoy train publish --no-push
```

These update git and the train sheet locally (including merging tagged `main` into `develop`). They do **not** push tags or trigger CI. Use them when you never plan to run cycles 3–4.

### End of cycle 2

When the release branch set is ready, stop here — or continue to **cycle 3** to push rc tags, publish to CodeArtifact, and test on staging.

---

## Setup for cycles 3 and 4 (tenant)

Cycles 3 and 4 need infrastructure git-convoy does not configure. Do this once per installation (or extend it when a **new repo** joins the train).

Full detail: [`ops/publisher/README.md`](../publisher/README.md) and your `*-bom` repo README (example: `ops/example-bom/README.md`).

### A. Publisher stack (CodeArtifact + OIDC publish role)

Deploy the publisher CDK stack once in the publisher AWS account:

```bash
cd ops/publisher/cdk
# Edit publisher-config.json — see below
cdk deploy <publisher-name>-publisher --app "python app.py" --profile <aws-profile>
```

In `ops/publisher/cdk/publisher-config.json`:

- **`publisher_name`** — short id for this registry (e.g. `arbitium`). Drives stack name `<publisher-name>-publisher` and role `GitHubActionsPublishRole-<publisher-name>`.
- **`github_org`** — GitHub org **exactly as shown in URLs** (OIDC is case-sensitive: `Arbitium`, not `arbitium`).
- **`github_publish_repos`** — list every GitHub repo **by short name** that may publish when a tag is pushed (e.g. `claw`, `pes`, `console`, `example-wl`). Add a new name here whenever a new package repo joins the train, then **redeploy** the stack. Do not use `["*"]` unless you intentionally trust the whole org. The stack trusts both classic (`repo:org/name`) and GitHub's immutable (`repo:org@id/name@id`) OIDC subjects.
- **`reader_aws_accounts`** — AWS account IDs allowed to **read** from CodeArtifact (your tenant deploy account).

**Verify the stack is configured** (there is no `git convoy` command for this — use AWS; substitute your `publisher_name`):

```bash
aws cloudformation describe-stacks \
  --stack-name <publisher-name>-publisher \
  --profile <aws-profile> \
  --region <aws-region> \
  --query 'Stacks[0].{Status:StackStatus,Outputs:Outputs}' \
  --output json
```

Expect `CREATE_COMPLETE` or `UPDATE_COMPLETE`, and outputs such as `OidcPublishRoleArn`. If the stack is missing, deploy it first. `UPDATE_ROLLBACK_COMPLETE` means the last deploy failed — fix config and redeploy.

Then verify the live OIDC trust (org casing must match GitHub; immutable subjects need the `@*` patterns):

```bash
aws iam get-role \
  --role-name GitHubActionsPublishRole-<publisher-name> \
  --profile <aws-profile> \
  --query 'Role.AssumeRolePolicyDocument' \
  --output json
```

Look for both `repo:<github_org>/*:*` and `repo:<github_org>@*/*:*` under `token.actions.githubusercontent.com:sub`.

### B. Each train participant repo (GitHub)

For **every repo** on the train that publishes packages, on **that GitHub repo**:

**1. Publish workflow** (copy from `ops/publisher/workflows/`):

| Repo layout | Workflow file |
| ----------- | ------------- |
| Python only (`pyproject.toml` at root) | `publish-python.yml` → `.github/workflows/publish.yml` |
| npm only (`package.json` at root, e.g. `example-wl`) | `publish-npm.yml` → `.github/workflows/publish.yml` |
| Extension (`package/` and/or `ui/`) | `publish-extension.yml` → `.github/workflows/publish.yml` (skips a missing tree) |

Workflows run on **`v*` tag push** (what `train tag-rc` and `train publish` push).

**2. Repository variables** (Settings → Actions → Variables):

| Variable | Value |
| -------- | ----- |
| `AWS_PUBLISH_ROLE_ARN` | `OidcPublishRoleArn` from the publisher stack output |
| `PUBLISHER_NAME` | e.g. `renglo` |
| `AWS_REGION` | Region where the publisher stack was deployed |

**3. Confirm publish succeeded** after each `tag-rc` / `publish` push — GitHub Actions on that repo must succeed. git-convoy only pushes tags. In **Full** mode, `train verify` polls workflow conclusions via `gh`. In **Simple** mode, watch Actions manually. A failed publish workflow means the BOM must not assume that version exists.

Optional: pin by package in the BOM (`python` / `npm` sections) instead of cloning private git SHAs — see your BOM README for `@<tenant>/wl` and extension packages.

**Console** is special today: it is a Vite app deployed from a **git clone** (`repos.renglo/console`), not from CodeArtifact. Until console has a working tag-publish workflow, `adopt` keeps **repos-only** pins and **removes** any stale `npm.@renglo/console` entry. A starter workflow lives at `console/.github/workflows/publish-npm.yml`; enabling it requires renaming the package to `@renglo/console`, adding `console` to `github_publish_repos`, redeploying the publisher stack, and setting the repo Actions variables above. After the first green `train verify`, `adopt` will write the npm pin instead.

Do not leave `npm` pins in the BOM for packages that failed publish CI — deploy will try CodeArtifact and fail. In **Full** mode, `git convoy adopt` runs `train verify` automatically and **self-heals**: failed publishes drop registry pins and fall back to `repos.*.commit` git SHAs. Use `--require-verify` when you want adopt to **refuse** instead of self-heal (no BOM written until every publishable repo is green). Use `--no-verify` to skip gh and use the local workflow heuristic only (Simple-mode behavior).

### C. BOM repo (staging / production deploy)

Your tenant BOM repo (e.g. `ops/example-bom`) needs:

- `bom/vX.Y.Z.json` — system versions and pins
- `deploy_targets.yml` — which BOM file staging and production use (`production.enabled: false` until cycle 4); optional `registries:` list for foreign CodeArtifact publishers (same-account internal works with no list); optional `packages:` catalog is system membership (adopt keeps only those python / npm / repo pins)
- GitHub Actions workflows that deploy when `bom/` or `deploy_targets.yml` changes on `main`
- CodeArtifact **read** access: publisher `reader_aws_accounts` must include the tenant account; tenant launcher `package_registry.domain_owners` lists each foreign publisher AWS account (omit / `[]` for internal-only)

git-convoy edits the BOM files locally; **you** commit and push the BOM repo so CI deploys.

---

## Cycle 3 — Staging adoption (registry + cloud test)

Cycle 3 starts when you push **rc** tags and adopt onto staging. Prerequisites: **Setup for cycles 3 and 4** (sections A–C).

### Golden path — Adopt a release train to staging

**1. Publish release candidates to the registry**

```bash
git convoy train tag-rc
```

For each train participant: merges latest stable/main into `develop` (catches hotfixes since the last rc), then candidate tag (`v1.2.4-rc.1`), push `release/<name>` and the tag. **CI publishes rc packages to CodeArtifact.** Develop sync failures are reported but tagging still proceeds — resolve conflicts during stabilization.

`tag-rc` will not reuse a `v*` tag that already exists locally or on origin (unless it already points at HEAD). It walks `rc.N` until it finds a free tag. If `vX.Y.Z` was already released, it starts at `vX.Y.Z+1-rc.1` instead of minting another `X.Y.Z-rc.N`.

Use `--no-push` to stay in cycle 2 (local tags only).

Before adopting, confirm publish CI:

```bash
git convoy train verify              # Full: check publish workflows now
git convoy train verify --wait       # poll until success or timeout
git convoy adopt --bom ops/acme-bom  # Full: verify + self-heal (default)
git convoy adopt --require-verify --bom ops/acme-bom   # strict: refuse if any publish failed
git convoy adopt --no-verify --bom ops/acme-bom        # Simple: local heuristic only
```

`train verify` scans each repo’s `.github/workflows/` for files that trigger on **`v*` tag push** (same trigger publisher templates use). It does not guess a single workflow filename — `publish-python.yml`, `publish-extension.yml`, and `publish-npm.yml` all work. Repos with **no** tag-publish workflow (e.g. **console**, which deploys via git clone today) are **skipped**, not failed. If a repo has **multiple** tag-publish workflows, **all** must succeed.

### Adopt pin strategy (Full mode, default)

When `gh` is logged in, **`adopt` runs verify automatically** and picks pins per repo:

| Verify result | BOM pins |
| ------------- | -------- |
| **success** | `python` / `npm` registry versions; redundant `repos` SHAs removed |
| **skip** (git-clone participant) | `repos.*.commit` only — same as console today |
| **failure** (or pending / no tag) | **Self-heal:** clear registry pins, fall back to `repos.*.commit` |

CLI output lists the BOM files it wrote (hub, console, peers) with a pin summary. A **publish CI** line names which train repos succeeded vs are still pending (pending still gets heuristic registry pins unless you pass `--require-verify`).

**Simple mode** (no `gh`, or `--no-verify`): uses a local heuristic — workflow file present → registry pin; otherwise git SHA only. Optimistic; use Full mode for real trains.

`--require-verify` is the strict gate: adopt **aborts** if any publishable repo is not green (no self-heal). Use before production when you refuse any git-clone fallbacks.

`adopt` only writes **`python` / `npm` pins** for repos whose publish CI succeeded (or heuristic says they publish). Others get **`repos.*.commit` only**.

In **Simple** mode, watch Actions on each participant instead. If OIDC or publish failed, fix setup (section B) and re-tag. When `release/<name>` has new commits past the current rc tag, `tag-rc` bumps the rc suffix for that repo (e.g. `rc.1` → `rc.2`) and leaves unchanged repos on their existing rc.

**2. Write the staging BOM**

```bash
git convoy adopt --bom ops/acme-bom
```

First adopt for a train: new system version (patch bump), rc pins, staging pointed, `production.enabled: false`. CLI prints `(draft)`. Later adopts for the **same train** refresh the same file — `(refresh)`.

**3. Deploy staging**

```bash
cd ops/acme-bom
git add bom/ deploy_targets.yml
git commit -m "Adopt release train (staging)"
git push origin HEAD
```

CI deploys **staging** from the new BOM.

**4. Test and iterate**

If staging fails, go back to **cycle 2** (fix on `release/<name>`), then **cycle 3** again:

```bash
git convoy train tag-rc
git convoy adopt --bom ops/acme-bom
# commit and push BOM
```

Many attempts are fine. Train stays **`stabilizing`** until cycle 4’s `train publish`.

| When | Command | System version | Pins |
| ---- | ------- | -------------- | ---- |
| First adopt after `tag-rc` | `git convoy adopt` | New file (e.g. `v0.1.4` → `v0.1.5`) | rc from train |
| Later adopt, same train | `git convoy adopt` | **Same file** (refresh) | Updated from train sheet |

**End of cycle 3:** staging runs the train; production is unchanged (`production.enabled: false`). Stop here if you do not want production yet.

---

## Cycle 4 — Production release

Cycle 4 ships **stable** packages to the registry and enables production on the same BOM file staging already uses.

Prerequisites: cycle 3 complete and staging acceptable; setup sections A–C still apply.

### Golden path — Production

**1. Publish stable packages to the registry**

```bash
git convoy train publish
```

Drops rc suffix (`1.2.4rc1` → `1.2.4`), merges `release/<name>` into `main`, tags `v1.2.4`, pushes `main` and the tag, then runs **`train mergeback` automatically**: merge tagged `main` into `develop` for **every product repo** (train participants use the sheet’s stable tag; others use their latest stable tag or `main`) and push `develop`. Repos with no `develop` branch are left on `main`. **CI publishes stable packages.** Train status → **`published`** as soon as the stable tags exist, even if mergeback later fails.

The develop merge is what lets the next **`train cut`** see new work. Cut includes a repo only when its integration branch (`develop`, or `main` when there is no `develop`) is ahead of the last stable tag **and** that tag is an ancestor of the tip. If `develop` never receives the tagged `main`, the next cut reports nothing to ship even after you merge features.

If mergeback hits a conflict, a dirty `develop`, or a failed push, `train publish` still leaves the stable tags on `main` (and the train sheet `published`). Fix the failed repos and retry:

```bash
git convoy train mergeback
git convoy train mergeback 2026-08-30
```

Mergeback is idempotent: already-synced repos are skipped (`already`). A conflict aborts the merge so the repo is not left mid-merge. It continues past per-repo failures so the rest of the set can still sync. Re-run manually any time after publish to heal repos that were not on the train.

Again:

```bash
git convoy train verify
git convoy train verify --wait
```

In **Simple** mode, confirm publish workflows succeeded in GitHub before adopting.

**2. Enable production on the BOM**

Fast path (one command):

```bash
git convoy adopt --production --bom ops/acme-bom
```

Refreshes **stable** pins in the current BOM file, sets `Production. Release <train>.`, and sets `production.enabled: true`. Refuses if the train is not **published** or pins are still rc.

```bash
cd ops/acme-bom
git add bom/ deploy_targets.yml
git commit -m "Adopt production train"
git push origin HEAD
```

CI runs **staging deploy → smoke check → production deploy** in one workflow. Production is blocked if staging fails. Watch GitHub Actions (or failure notifications).

**3. Return to a neutral workspace**

Once production is up, the published train is finished. Do not `tag-rc` or `adopt` it again. Clear the sheet and leftover `release/<name>` branches:

```bash
git convoy train delete --yes
```

That unsets `current_train`, removes the train sheet, and checks participants out to `develop`/`main`. It does **not** unpublish packages or disable production. Pass `--remote` if `origin/release/<name>` is still present. The next ship starts with a new `train cut`.

#### Optional safe path

A manual staging check on **stable** pins before enabling production is recommended, not required:

1. `git convoy adopt` — refresh stable pins; description `Staging. Release <train>.`
2. Commit and push — staging runs stable build
3. `git convoy adopt --production` — enable production on the same file
4. Commit and push

---

## Aux — Platform tooling (parallel to features)

Use **`git convoy aux`** for platform/tooling repos that must not ride product trains (launcher, bom-helper, git-convoy, publisher, bootstrap, extensions-service, etc.).

Membership:

1. Each aux repo commits `gitconvoy.toml` with `role = "aux"` (BOM repos use `role = "bom"`). Unmarked repos are **product**.
2. `git convoy init` writes local `.gitconvoy/aux.toml` from those markers (workspace-local, not versioned).
3. `git convoy adopt` (and hotfix adopt) defaults to the single repo listed under `[bom]` in that file — any directory name is fine. Pass `--bom PATH` only to override. If `[bom]` is empty, discovery falls back to a `*-bom` directory name.

Lifecycle is hotfix-style on **aux repos only**. Branch prefix `aux/<name>`. PRs target **`main`** (one review). `aux close` merges **`main` → `develop`** so develop stays current — no second PR. Missing `develop` branches are created from `main`. Independent of the current feature/train/hotfix. `aux promote` is recovery only when develop is already ahead of main.

```bash
git convoy aux start codeartifact-mosaic
git convoy aux adopt
git convoy aux adopt --repos bom-helper,git-convoy
git convoy aux commit --header "fix: …" --header-only
git convoy aux prs
# merge PRs to main in GitHub
git convoy aux show
git convoy aux close --yes      # main → develop; remove aux branches
```

`aux prs` moves leftover local-`main` commits onto `aux/<name>`, then resets local `main` to `origin/main`. A cherry-pick conflict leaves the repo in the cherry-pick: resolve, `git add`, `git cherry-pick --continue`, then re-run `aux prs`.

`feature adopt` ignores dirty aux repos; `aux adopt` ignores dirty product repos. Pass `--repos` to force-include named aux ids even when they are clean.

---

## Hotfix — Production emergency

Do not wait for the next train. A hotfix can touch **more than one product repo**. PRs go to **`main`**. After tags land, the patch is merged into **`develop`** and absorbed into local in-progress **`feature/*`** branches so every branch in process gets it.

```bash
git convoy hotfix start fetch-file                 # dirty product repos, existing hotfix/<name>, or --repos a,b
git convoy hotfix commit --header "fix: …" --header-only
git convoy hotfix push
git convoy hotfix prs                              # PRs into main
# merge those PRs in GitHub (merge order)
git convoy hotfix publish                          # tag vX.Y.Z; merge main → develop; absorb feature/*
git convoy hotfix adopt --bom ops/acme-bom         # next BOM patch; pin only hotfix packages; staging only
```

`hotfix start` branches `hotfix/<name>` from `main` and bumps **PATCH** only. You must be on `main`, `develop`, or the hotfix branch (not a dirty `feature/*`). If `hotfix/<name>` already exists locally or on origin, start checks it out, puts those repos on the sheet, and does **not** bump PATCH again — even when the tree is clean and the sheet was empty. It does **not** convert `feature/<name>` into a hotfix; create a new hotfix from `main` or `develop`, or be clean so start can switch onto an existing `hotfix/<name>`.

`hotfix publish` refuses until each participant’s hotfix branch is on `main` (or `main` already has the expected PATCH — squash-safe). It tags `vX.Y.Z`, pushes `main` and the tag when origin exists, merges tagged `main` into `develop` (and pushes `develop`), then merges that `develop` into every **local** `feature/*`. Conflicts abort that merge and are listed; resolve and run `git convoy feature refresh`. Use `--no-push` to keep tags and merges local.

`hotfix adopt` drafts the next system PATCH, pins **only** the hotfix packages, and points **staging**. It does **not** enable production. Commit and push the BOM yourself; then `git convoy adopt --production` when staging is acceptable.

```bash
git convoy hotfix show
git convoy hotfix abandon --yes                    # drop sheet; keep branches and files
```

git-convoy does not merge the GitHub PRs and does not push `*-bom`.

---

## Optional reading — Adoption internals

You do not need these words to adopt. `adopt` and `adopt --production` run them for you.


| Word | What it changes | What it means |
| ---- | --------------- | ------------- |
| **Draft** | A new `bom/vX.Y.Z.json` | Copy the current BOM to a new system version. CLI: `(draft)`. |
| **Refresh** | Same `bom/vX.Y.Z.json` | Re-pin from the train sheet in place. CLI: `(refresh)`. |
| **Pin** | Entries inside that JSON | Exact package or repo SHA versions from the train. |
| **Point** | `deploy_targets.yml` | Which BOM file staging / production install. |

Manual primitives:

```bash
git convoy adopt draft --from 1.4.0 --to 1.4.1 --bom ops/acme-bom
git convoy adopt pin 1.4.1 renglo-lib 1.2.5 --bom ops/acme-bom
git convoy adopt point 1.4.1 --bom ops/acme-bom
```

Pass `--train NAME` if the train you want is not current. Rollback: `adopt point` at the previous system version, commit and push.

---

## Commands

| Command | Cycle | What it does |
| ------- | ----- | ------------ |
| `git convoy init` | 1 | State file, membership (`aux.toml`), gitignore, Cursor skill |
| `git convoy status` | * | Current feature, aux, train, hotfix, dirty repos |
| `git convoy sync` | * | Idle workspace: fetch all, check out `develop`, pull features + hotfixes |
| `git convoy sync develop` | * | Merge stable/`main` into `develop` for product repos (no idle check) |
| `git convoy feature start NAME` | 1 | Sheet; pick up existing `feature/NAME`; else checkout `develop` |
| `git convoy feature adopt` | 1 | Branch changed repos onto `feature/NAME`; drop empty leftover branches |
| `git convoy feature abandon` | 1 | Drop the feature sheet (no branch or file deletes) |
| `git convoy feature commit` | 1 | Commit dirty participants |
| `git convoy feature push` | 1 | Push `feature/<name>` (no PRs) |
| `git convoy feature switch NAME` | 1 | Checkout that feature’s repos |
| `git convoy feature refresh` | 1 | Merge `origin/develop` into participants |
| `git convoy feature prs` | 1 | Push and open PRs (Full); `--no-gh` for compare URLs |
| `git convoy feature approve` | 1 | Approve sibling PRs (Full; requires `gh`) |
| `git convoy feature show [NAME]` | 1 | Feature sheet + merge status |
| `git convoy feature close` | 1 | After all PRs merged |
| `git convoy aux start NAME` | * | Aux sheet; pick up existing `aux/NAME`; else checkout integration |
| `git convoy aux adopt [--repos …]` | * | Branch changed **aux** repos onto `aux/NAME` (from develop or main); `--repos` force-includes |
| `git convoy aux abandon` | * | Drop the aux sheet (no branch or file deletes) |
| `git convoy aux commit` | * | Commit dirty aux participants |
| `git convoy aux push` | * | Push `aux/<name>` (no PRs) |
| `git convoy aux switch NAME` | * | Checkout that aux’s repos |
| `git convoy aux refresh` | * | Merge `origin/main` into aux participants |
| `git convoy aux prs` | * | Push and open PRs into **main** (Full); `--no-gh` for compare URLs. Absorbs leftover local-`main` commits onto `aux/<name>` |
| `git convoy aux approve` | * | Approve sibling PRs (Full) |
| `git convoy aux promote` | * | Recovery: develop→main when develop is already ahead |
| `git convoy aux show [NAME]` | * | Aux sheet + merge status |
| `git convoy aux close` | * | After merge to main: main→develop; remove aux branches |
| `git convoy train cut NAME` | 2 | Cut `release/NAME` on changed repos |
| `git convoy train adopt [--repos …]` | 2 | Late-join dirty (or named) product repos; no version bump |
| `git convoy train commit` | 2 | Commit dirty train participants (same plan as feature/aux commit) |
| `git convoy train show [NAME]` | 2 | Read train sheet |
| `git convoy train delete` | 2, 4 | Delete merged `release/<train>` branches only; refuse dirty or unique commits |
| `git convoy train tag-rc` | 3 | Sync develop from stable, push rc tags → registry (`--no-push` for cycle 2 only) |
| `git convoy train verify` | 3–4 | Tag-publish workflows via gh (skips git-clone-only repos; `--wait` to poll) |
| `git convoy adopt` | 3 | Staging BOM from `.gitconvoy/aux.toml` `[bom]` (or `*-bom` / `--bom`); `(draft)` or `(refresh)` |
| `git convoy adopt --require-verify` | 3–4 | Strict: refuse adopt when any publish workflow failed |
| `git convoy adopt --no-verify` | 3–4 | Skip verify; local workflow heuristic only (Simple mode) |
| `git convoy train publish` | 4 | Stable tags → registry; then mergeback into `develop` |
| `git convoy train mergeback` | 4 | Retry develop sync for all product repos (participants + non-participants) |
| `git convoy adopt --production` | 4 | Stable pins + `production.enabled: true` (same BOM default as `adopt`) |
| `git convoy hotfix start NAME` | * | Branch or pick up `hotfix/<name>`; bump PATCH unless already bumped |
| `git convoy hotfix commit` | * | Commit dirty hotfix participants |
| `git convoy hotfix push` | * | Push `hotfix/<name>` (no PRs) |
| `git convoy hotfix prs` | * | PRs into **main** (Full); `--no-gh` for compare URLs |
| `git convoy hotfix publish` | * | Tag on `main`; merge into `develop`; absorb local `feature/*` |
| `git convoy hotfix adopt` | * | Next BOM patch; pin only hotfix packages; staging only |
| `git convoy hotfix show [NAME]` | * | Hotfix sheet + merge status |
| `git convoy hotfix abandon` | * | Drop the hotfix sheet (no branch or file deletes) |
| `git convoy adopt draft` | * | Copy BOM to new system version |
| `git convoy adopt pin` | * | Set one package version |
| `git convoy adopt point` | * | Aim staging or production at a BOM file |

Global flags: `--json`, `--workspace PATH`.

---

## For coding agents

Add `--json` to every command you need to read.

```bash
git convoy --json status
git convoy --json sync
git convoy --json feature show
git convoy --json train show
git convoy --json feature commit
git convoy --json feature push
git convoy --json adopt --bom ops/<system>-bom              # cycle 3: staging
git convoy --json adopt --production --bom ops/<system>-bom  # cycle 4: production
git convoy --json hotfix show
git convoy --json hotfix adopt --bom ops/<system>-bom
```

Cycles 1–2 only: no `--bom`, no registry. Do not invent package pins. In cycle 3–4 with Full mode, `adopt` verifies publish CI and self-heals failed repos to git SHAs. Use `--require-verify` when every publish must be green before writing the BOM.

`init` installs a Cursor skill (`.cursor/skills/gitconvoy/SKILL.md`). After time away, with a clean workspace: `git convoy --json sync` (ends on `develop`). After editing code: `feature adopt`, then `feature commit`. Do not commit feature work on `develop`. Do not `git pull` on `main` to start product work.

---

## What this tool will not do

- **Merge** GitHub PRs (approve via `feature approve` in Full mode; merge stays in GitHub)
- Query CodeArtifact directly (Full mode checks **publish workflow** outcome via `gh`)
- Create a `feature/*` branch in every repo
- Push the BOM repo for you

In **Simple** mode, PR approval and publish verification stay manual in the GitHub UI. Process authority: [cross-repo-feature-manual.md](cross-repo-feature-manual.md).
