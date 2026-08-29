# Cross-repository feature manual

How to take a feature from an idea to packages in the registry, and how a running system adopts those packages. This is the procedure to follow **by hand**. The CLI that performs these steps is [git-convoy](README.md).

Design notes that led here: [cross-repo-feature-lifecycle.md](cross-repo-feature-lifecycle.md). Branch and tag mechanics that still say `release/X.Y` in [gitflow-and-releases.md](gitflow-and-releases.md) are outdated; this manual uses **train-named** release branches.

---

## What this process is

A feature in Renglo usually spans more than one repository. An idea often starts in an extension. If the same idea is useful to others, the reusable part is neutralized and offered to core. Core admins accept that the way an open-source project accepts a contribution. Extensions are also composable (an agent uses other extensions as tools and channels), so a single feature touching several repos is normal.

The lifecycle has two halves. They are decoupled on purpose.

| Half | Result | Does not do |
| ---- | ------ | ----------- |
| **Development and release** | New package versions in the registry | Change any business system |
| **Adoption** | A system version (BOM) running in staging, then production | Publish packages |

Every business system chooses its own cadence. A train can sit in the registry unused.

**Extension publishers** (`*` in this manual) have no write access to core repos. They follow the same steps on the repos they own. They still need a full local environment, including read-only core.

---

## Roles

| You are… | You may edit | You may only read |
| -------- | ------------ | ----------------- |
| Core developer | `renglo-lib`, `renglo-api`, `console`, and any extension you own | Other extensions as needed |
| Extension publisher | Your extension repo(s) | Core and everyone else’s extensions |
| Release engineer | Release branches, tags, `<name>-bom` BOM | Feature branches you did not cut |
| Reviewer | Comments and GitHub approvals | Do not merge a sibling PR unless the whole set is approved |

---

## State you keep by hand

Git does not remember “which repos belong to feature X” or “which repos are on train week-34.” You do. A spreadsheet or a text file is enough. Keep these files in the Stanley workspace (or any shared place the next laptop can see). Commit them if more than one person will run the process.

### Feature sheet

One sheet (or one text file) **per feature**. Create it **before** the first line of code, even though you do not yet know which repos will change.

```text
feature:     blast-radius
branch:      feature/blast-radius
status:      in-progress          # in-progress | in-review | merged

repo            path                         pr
renglo-lib      dev/renglo-lib               https://github.com/renglo/renglo-lib/pull/…
arbitiumlab     extensions/arbitiumlab       …
schd            extensions/schd              …
arbitiumtriage  extensions/arbitiumtriage    …
```

Rules:

- Start with an empty repo list.
- Add a row the first time that repo actually changes. Do not pre-list every repo in the workspace.
- The `pr` column stays empty until you open PRs.
- This sheet is what you read when you switch features, refresh from `develop`, or open PRs. Do not reconstruct the list by looking for dirty directories.

Also keep a one-line **current feature** note (a cell, or a file `CURRENT_FEATURE`) so you know which sheet adopt-after-edit writes into.

```text
current: blast-radius
```

### Train sheet

One sheet **per release train**. Create it when you cut the train.

```text
train:       2026-W34
branch:      release/2026-W34
cutoff:      2026-08-18
status:      cut | stabilizing | published

repo            path                  from     to        rc-tag           stable-tag
renglo-lib      dev/renglo-lib        1.2.3    1.2.4     v1.2.4-rc.1      (empty until publish)
breakdown       extensions/breakdown  0.0.2    0.0.3     v0.0.3-rc.2
```

Repos that did not change do **not** get a row and do **not** get a `release/…` branch.

### Adoption is already a file

The next system version **is** the `<name>-bom` version object. You do not need a second sheet for pins. You may keep a short note of “what this draft is taking” (train id, or “hotfix renglo-lib only”) in the version object’s description field.

---

## Merge order (fixed)

When several PRs or several release-to-`main` merges belong together, merge in this order. Later rows depend on earlier ones. Merging a consumer first makes its CI red.

1. `renglo-lib`
2. `renglo-api`
3. `console` and every extension (any order among themselves, unless one extension clearly depends on another — then the depended-on one first)

---

# Part 1 — Development and release

## 1. Multi-repo environment

You already have a workspace with the product repos checked out and the stack pointing at a real database, auth, and so on. The environment must run.

`*` Extension publishers need that same running stack. Core clones in their workspace are read-only.

---

## 2. Start the feature on `develop`

1. Write the feature name on a new **feature sheet**. Set `CURRENT_FEATURE` to that name. Repo list empty.
2. In **every** product repo you might touch, start from current `develop`:

   ```bash
   git checkout develop
   git pull origin develop
   ```

   You do not create `feature/<name>` yet. You do not know which repos will change. Coding agents will edit whatever is checked out; that is expected.

3. Implement. Example: a Blast Radius handler in `arbitiumtriage` that uses the graph controller in `renglo-lib`, blueprints in `arbitiumlab`, and a modal in `schd`. If a change in `renglo-lib` is truly general, offer it to core rather than overfitting the controller. Core admins decide.

4. `*` You only commit in extension repos you own. You may still change several of your own extensions in one feature.

`develop` is the **base**. It is not where feature commits are allowed to stay. After each working session (or after an agent stops), do §3.

---

## 3. Adopt changes onto the feature branch

For **each** repo that now has uncommitted files, or commits that are not on `origin/develop`:

**Uncommitted changes only**

```bash
git checkout -b feature/blast-radius
# if that branch already exists:
# git checkout feature/blast-radius
```

Add the repo to the feature sheet if it is not already there.

**The work was committed on `develop`**

```bash
git checkout -b feature/blast-radius
git checkout develop
git reset --hard origin/develop
git checkout feature/blast-radius
```

Add the repo to the feature sheet.

If `develop` was **pushed** with those commits, stop. Do not reset a shared `develop`. Move the work with a revert or a follow-up PR. Treat that as an incident, not a normal adopt.

Do **not** create `feature/<name>` in repos that did not change.

Then commit on the feature branch (`git convoy feature commit`, or `git commit` in each repo). Do not commit on `develop`. Agents: `git convoy --json feature commit` (plan) then `--from` (apply).

To back up commits on GitHub without a PR: `git convoy feature push` (`git push -u origin feature/<name>` in each participant). Uncommitted files stay on the laptop.

---

## 3b. Leave a feature and come back

This is ordinary branch switching. Worktrees are not required.

**Leave**

1. In every repo on the feature sheet, commit or stash. If anything is dirty, do not switch.
2. Set `CURRENT_FEATURE` to the next name (or empty).
3. To start something else from a clean base:

   ```bash
   git checkout develop
   git pull origin develop
   ```

   Do that in every repo, or at least in every repo that was on the sheet. Then §2 for the new feature.

**Return**

1. Set `CURRENT_FEATURE` to the feature you want.
2. Read **that** feature sheet. In every listed repo:

   ```bash
   git checkout feature/blast-radius
   ```

3. In workspace repos **not** on that sheet, stay on (or return to) `develop`.

If you skip a listed repo, the feature is incomplete and will not run. The sheet is how you avoid that.

---

## 4. Refresh from `develop`

Other features land on `develop` while you work. Refresh often. A long-lived feature branch that never takes `develop` is painful to merge later.

For each repo on the feature sheet:

```bash
git checkout feature/blast-radius
git fetch origin
git merge origin/develop
# or: git rebase origin/develop
```

Resolve conflicts yourself. Re-run the local stack. Do not leave a conflicted repo “for later” while you refresh the others.

`*` Merging `develop` into **your** extension does not update core. To see whether you still work against latest core, pull `develop` on your read-only core clones (or install the latest core packages) and run the stack again. That is a separate action from refreshing your feature branches.

---

## 5. Open PRs onto `develop`

When the feature is stable on your machine:

1. Refresh from `develop` one last time (§4). Commit.
2. Push every branch on the feature sheet:

   ```bash
   git push -u origin feature/blast-radius
   ```

3. Open one pull request per listed repo: `feature/<name>` → `develop`. Put the PR URL in the sheet.
4. Open a tracking issue (or a row at the top of the sheet) that lists every PR. Reviewers use that list. GitHub has no cross-repo PR.

**Review**

- Comment on any PR. Approve on GitHub as usual (branch protection, CODEOWNERS, and CI stay real).
- Do **not** merge until every sibling PR is approved and its CI is green.
- If one PR is rejected, none of them merge. A half-landed feature on `develop` is the failure mode this step exists to prevent.

**Merge** (after the whole set is approved)

Merge in the [fixed order](#merge-order-fixed). If a later merge fails, stop. Fix that PR or revert what already landed. Do not keep merging the rest.

Then mark the feature sheet `merged`.

`*` Same process; the set never includes core repos.

---

## 6. Cut a release train

A **train** is a coordination label, not a version. `renglo-lib` may be `1.2.4` while `renglo-api` is `2.3.1` and `breakdown` is `0.0.3`. They can still share `release/2026-W34`.

Prefer a sortable train id: `2026-W34` (ISO week) or the cutoff date. Avoid `week-34` without a year.

**Who is on the train**

A repo is on the train only if `develop` has commits that are not in its last **stable** tag. Unchanged repos sit out. Their BOM pins stay as they are.

**Cut**

For each participating repo, after the cutoff:

```bash
git checkout develop
git pull origin develop
git checkout -b release/2026-W34
```

Write a row on the **train sheet**. Decide the **intended stable** version for that package (semver: PATCH / MINOR / MAJOR for what actually changed). Do not bump every commit; bump once when you cut.

On the release branch, write that number **with an rc suffix** in the version files. Python and the extension UI stay on the same number.

| Kind | File | Example |
| ---- | ---- | ------- |
| Python | `pyproject.toml` / `setup.py` | `1.2.4rc1` |
| npm (extension UI) | `ui/package.json` | `1.2.4-rc.1` |

```bash
git add -A
git commit -m "Set 1.2.4rc1 for train 2026-W34"
git push -u origin release/2026-W34
git tag v1.2.4-rc.1
git push origin v1.2.4-rc.1
```

The tag publishes that package to the registry. Repeat per participant (each has its own semver).

**Stabilize**

On `release/<train>` only: bugfixes and release prep. No new features.

- If a fix is needed: commit on the release branch, merge that fix **back to `develop`**, tag `vX.Y.Z-rc.2`, update the train sheet.
- Test locally. For cloud: pin the **rc** versions in a staging BOM of a `<name>-bom` repo and deploy staging (Part 2, using rc pins). That is how you learn whether incoming packages break existing features.

The train is stabilized when the last rc of every participant is acceptable.

---

## 7. Publish the train

Publishing puts **stable** packages on `main` and in the registry. It still does not deploy a business system.

For each repo on the train sheet, on the release branch:

1. Edit the version files: **drop the rc**. `1.2.4rc1` → `1.2.4`. Same number. Do not increment.
2. Merge to `main`:

   ```bash
   git checkout main
   git pull origin main
   git merge release/2026-W34
   git push origin main
   git tag v1.2.4
   git push origin v1.2.4
   ```

3. Write the stable tag on the train sheet.

Merge participants in the [fixed order](#merge-order-fixed) if their publishes must land together.

`*` Your extension may publish on the same Sunday as the official train, or later, using the same steps on your own repos.

On the train sheet (or a short notes file next to it), record **which features** this train carried. That is the release manifest for humans. Package tags do not list features.

Status → `published`.

---

# Part 2 — Adoption

A **Renglo Implementation** is a running system that installs these packages. It has a `<name>-bom` repo (example: `stanley-bom`). That repo holds one **version object** per system version.

The system version (`v0.0.9`, `2026-W34`, …) is not any package’s semver. The version object is the bill of materials: every dependency and the exact pin. You can rebuild that system by installing only those pins. A package that did not move keeps the previous pin.

Compatibility is not computed from version numbers. It is whatever **staging** accepts.

---

## A1. Draft the next version object

1. Copy the last system version that is known good in **production** (or the last good staging draft, if you are still iterating). That copy is the new draft.
2. Decide what this adoption is taking:

   - A published train: pin every package that train shipped, at the versions on the train sheet. Leave everything else.
   - One package (or a small set) because you need that fix. Leave everything else.
   - Nothing new — documentation only. Rare.

3. Do not “always bump core first.” Core moves when the train or hotfix moved core.
4. Put a sentence in the draft’s description: train id, or “hotfix `renglo-lib` only,” plus anything you pinned back last time.
5. Point the deploy config at this draft. Turn **production off** so a push cannot skip staging. Do **not** deploy production.

Work in the `<name>-bom` repo (example: `stanley-bom`). Today that repo still pins git commits under `repos`. The target shape is package pins under `python` / `npm` (see [package-registry-migration.md](package-registry-migration.md)). The git steps are the same either way; the examples below use package pins.

### Example — take train `2026-W34`

Production is on system version `v1.4.0`. The train sheet says `renglo-lib`, `renglo-api`, and `breakdown` published; nothing else moved.

```bash
cd ops/stanley-bom
git checkout main
git pull origin main

cp bom/v1.4.0.json bom/v1.5.0.json
```

Last good BOM (`bom/v1.4.0.json`):

```json
{
  "version": "v1.4.0",
  "train": "2026-W33",
  "description": "Production. Train 2026-W33.",
  "python": {
    "renglo-lib": "1.2.3",
    "renglo-api": "2.3.0",
    "renglo-breakdown": "0.0.2",
    "renglo-schd": "1.1.0"
  },
  "npm": {
    "@renglo/console": "0.8.0",
    "@renglo/breakdown": "0.0.2",
    "@renglo/schd": "1.1.0"
  }
}
```

Edit the copy. Bump only what the train shipped. Keep `renglo-schd` and `@renglo/console` as they were.

`bom/v1.5.0.json`:

```json
{
  "version": "v1.5.0",
  "train": "2026-W34",
  "description": "Draft. Taking train 2026-W34 (renglo-lib, renglo-api, breakdown). Not production.",
  "python": {
    "renglo-lib": "1.2.4",
    "renglo-api": "2.3.1",
    "renglo-breakdown": "0.0.3",
    "renglo-schd": "1.1.0"
  },
  "npm": {
    "@renglo/console": "0.8.0",
    "@renglo/breakdown": "0.0.3",
    "@renglo/schd": "1.1.0"
  }
}
```

Point deploy at the draft and disable production. `deploy_targets.yml`:

```yaml
bom: 1.5.0

handlers_bom: 0.0.3
handlers_compute: lambda_only

tenants:
  stanley:
    id: stanley0731
    aws_account: "339713094352"
    aws_region: us-east-1
    stages:
      staging:
        enabled: true
      production:
        enabled: false
```

`bom: 1.5.0` means CI reads `bom/v1.5.0.json`. Leave the old file on disk. That is the rollback pin list.

Do not commit yet if you want a last look. Committing without pushing is fine; **push** is what deploys (A2).

### Example — take one hotfix only

Production stays on `v1.4.0`. You only need `renglo-lib 1.2.5` (a PATCH published from Part 3).

```bash
cp bom/v1.4.0.json bom/v1.4.1.json
```

Change `"version"` to `v1.4.1`, set `"description"` to `Draft. Hotfix renglo-lib 1.2.5 only.`, set `"renglo-lib": "1.2.5"`, leave every other pin. Set `bom: 1.4.1` and `production.enabled: false`.

---

## A2. Prove it on staging

Push the version object and the deploy config. That push is what deploys. Do not tag `<name>-bom` to trigger staging.

Staging installs those pins, boots, and runs the tests you already trust. The combination is stable when staging stays up and those tests pass.

If staging breaks, do **one** of the following. Do not walk a dependency graph and guess:

1. **Pin back** the package that broke the combination. Adopt less, or wait for the next train.
2. **Fix forward**: `hotfix/*` from `main` (or a new feature), publish a new package, put that pin in the draft, stage again.
3. **Take the rest of the set.** If `renglo-lib` now requires an app id on every API call, you cannot take that lib pin until the extensions you run have been updated and published. That work is Part 1. Adopt the whole set, or none of it. A blueprint field rename in `schd` is the same problem: pin `schd` back, or adopt the extensions that write the new field in the same system version.

Repeat: edit draft → stage → pin-back or fix → stage. The draft is not stable until staging says so.

### Example — first staging deploy

```bash
cd ops/stanley-bom
git checkout main

git add bom/v1.5.0.json deploy_targets.yml
git commit -m "$(cat <<'EOF'
Draft system v1.5.0 from train 2026-W34; staging only.

EOF
)"
git push origin main
```

Watch the deploy workflow. Confirm `production.enabled` is still `false` (or re-run the workflow with `skip_production=true` if your repo supports that input). When the staging URL is up, run the tester checks you already use.

### Example — pin back `breakdown`

Staging boots, but Breakdown screens fail. You decide not to take `0.0.3` in this system version.

Edit `bom/v1.5.0.json` (same file — this draft has not gone to production, so you may still change it):

```json
{
  "version": "v1.5.0",
  "train": "2026-W34",
  "description": "Draft. Train 2026-W34 except breakdown pinned back to 0.0.2 (staging failure).",
  "python": {
    "renglo-lib": "1.2.4",
    "renglo-api": "2.3.1",
    "renglo-breakdown": "0.0.2",
    "renglo-schd": "1.1.0"
  },
  "npm": {
    "@renglo/console": "0.8.0",
    "@renglo/breakdown": "0.0.2",
    "@renglo/schd": "1.1.0"
  }
}
```

```bash
git add bom/v1.5.0.json
git commit -m "$(cat <<'EOF'
Pin breakdown back to 0.0.2 after staging failure.

EOF
)"
git push origin main
```

Stage again. If it holds, this pin list is the candidate for A3.

### Example — take the rest of the set

`renglo-lib 1.2.4` requires an app id on API calls. Staging fails because `schd` still calls the old way. Pin-back of lib would drop the train’s point. Instead you wait until `renglo-schd 1.2.0` is published (a Part 1 feature), then add it to the **same** draft:

```json
"renglo-schd": "1.2.0",
```

```json
"@renglo/schd": "1.2.0"
```

```bash
git add bom/v1.5.0.json
git commit -m "$(cat <<'EOF'
Take schd 1.2.0 with renglo-lib 1.2.4 (app id).

EOF
)"
git push origin main
```

If those packages are not published yet, stop adoption. Go back to Part 1. Do not invent a pin that is not in the registry.

---

## A3. Production

Deploy the **same** pin list that passed staging. If you need another change, it is a new system version; go back to A1.

Smoke-test production. Write release notes: train (if any), pins that moved, pins that were held back.

If production misbehaves, point deploy at the **previous** version object. That is why every system version is immutable.

### Example — promote `v1.5.0`

Do not copy the JSON to a new version. Do not change pins. Only turn production on and say so in the description.

`bom/v1.5.0.json` — same pins as the last green staging. Only the description changes:

```json
{
  "version": "v1.5.0",
  "train": "2026-W34",
  "description": "Production. Train 2026-W34; breakdown held at 0.0.2. Staging 2026-08-24.",
  "python": {
    "renglo-lib": "1.2.4",
    "renglo-api": "2.3.1",
    "renglo-breakdown": "0.0.2",
    "renglo-schd": "1.1.0"
  },
  "npm": {
    "@renglo/console": "0.8.0",
    "@renglo/breakdown": "0.0.2",
    "@renglo/schd": "1.1.0"
  }
}
```

`deploy_targets.yml`:

```yaml
bom: 1.5.0

handlers_bom: 0.0.3
handlers_compute: lambda_only

tenants:
  stanley:
    id: stanley0731
    aws_account: "339713094352"
    aws_region: us-east-1
    stages:
      staging:
        enabled: true
      production:
        enabled: true
```

```bash
git add bom/v1.5.0.json deploy_targets.yml
git commit -m "$(cat <<'EOF'
Promote system v1.5.0 to production.

EOF
)"
git push origin main
```

Smoke-test production. Leave `bom/v1.4.0.json` in the repo.

### Example — roll back to `v1.4.0`

Do not edit `v1.5.0.json`. Point deploy at the previous file.

```yaml
bom: 1.4.0
```

Keep `production.enabled: true` if you want production to run the old pins immediately.

```bash
git add deploy_targets.yml
git commit -m "$(cat <<'EOF'
Roll back production to system v1.4.0.

EOF
)"
git push origin main
```

The next attempt is a **new** system version (`v1.5.1` or `v1.6.0`): copy from whichever object you trust, and start at A1.

---

# Part 3 — Hotfix (production emergency)

Do not wait for the next train.

1. From `main` in the affected repo(s): `git checkout -b hotfix/<patch-version>`.
2. Fix. Bump **PATCH** only (`1.2.4` → `1.2.5`). If several repos must change, use a feature sheet the same way as Part 1, with branch name `hotfix/…`.
3. Merge to `main` in merge order, tag `v1.2.5`, push the tag (registry publish). Merge the hotfix back to `develop`.
4. Adopt with A1–A3, taking only those new pins.

---

## Checklist (one pass)

**Feature**

- [ ] Feature sheet created; `CURRENT_FEATURE` set
- [ ] Workspace on `develop`
- [ ] After each session: changed repos adopted onto `feature/<name>`; `develop` reset if you committed there; sheet updated
- [ ] Refreshed from `develop`; conflicts resolved
- [ ] PRs open for every sheet row; tracking list filled
- [ ] All PRs approved; merged in lib → api → consumers; sheet marked `merged`

**Train**

- [ ] Train sheet: only repos ahead of last stable tag
- [ ] `release/<train-id>` cut; intended version written as rc; `vX.Y.Z-rc.N` pushed
- [ ] Fixes on the release branch copied back to `develop`
- [ ] rc acceptable locally and, if you use cloud, on staging pins
- [ ] rc dropped (same number); merged to `main`; `vX.Y.Z` pushed; features listed on the train sheet

**Adoption**

- [ ] Draft copied from last good system version; only intended pins changed
- [ ] Staging green on that exact list
- [ ] Same list in production; previous version object left untouched for rollback
