# Cross-repository feature manual

How to take a feature from an idea to packages in the registry, and how a running system adopts those packages. This is the procedure to follow **by hand** with git (and GitHub). The CLI that performs these steps is [git-convoy](README.md).

You do not have to run every cycle. Stop when you have what you need. Cycles 1–2 are git only. Cycles 3–4 also need the tenant publisher (CodeArtifact) and a `<name>-bom` repo — see the README section “Setup for cycles 3 and 4”.

---

## What this process is

A feature in Renglo usually spans more than one repository. An idea often starts in an extension. If the same idea is useful to others, the reusable part is neutralized and offered to core. Extensions are also composable, so a single feature touching several repos is normal.

The work is four cycles plus two parallel paths. They run at different times and they do not substitute for each other.

| Cycle | What you move | What you get | Registry / BOM? |
| ----- | ------------- | ------------ | --------------- |
| **1. Daily feature work** | Code on `feature/<name>` → `develop` | Merged features on `develop` | No |
| **2. Release trains (local)** | `develop` → `release/<name>`; stabilize in git | A coherent release branch set, rc versions in git | No |
| **3. Staging adoption** | Pushed **rc** tags → registry; train → staging BOM | Packages in CodeArtifact; staging runs the train | Yes |
| **4. Production release** | **Stable** tags → registry; same BOM → production | Production runs the stable train | Yes |

The two halves stay decoupled on purpose. A train can sit in the registry unused. **Publishing packages is not enabling production.** Production is cycle 4, after staging has accepted the train.

| Half | Result | Does not do |
| ---- | ------ | ----------- |
| **Development and release** (cycles 1–2, then tags in 3–4) | New package versions in the registry | Change any business system |
| **Adoption** (BOM in cycles 3–4) | A system version running in staging, then production | Publish packages |

**Boundaries**

- **Cycle 2 → 3:** the first **rc tags you push** to origin. That triggers CI publish workflows. Watch GitHub Actions on each participant before you write registry pins into a BOM.
- **Cycle 3 → 4:** merge to `main`, push **stable** tags, merge tagged `main` back into `develop`, then enable production on the BOM. Production stays off until that last step.

**Hotfix** is a parallel path, not a fifth cycle: a production PATCH without a new train. **Aux** is a parallel path for platform tooling that must not ride product trains.

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

## Which repos

Treat workspace clones as three kinds. Do not mix them on one sheet.

| Kind | Where | Rides trains / hotfixes / feature PRs onto `develop`? |
| ---- | ----- | ----------------------------------------------------- |
| **Product** | `console/`, `dev/*`, `extensions/*`, tenant ops such as `bootstrap` or `<tenant>-wl` | Yes |
| **Aux** | Platform tooling: `publisher`, `launcher`, `git-convoy`, `bom-helper`, … | No. Own lifecycle: `aux/<name>` PRs into **`main`**. |
| **BOM** | `<name>-bom` | No. Pins land on `main` of that repo. **That push deploys.** Never put `*-bom` on a feature, train, or hotfix branch. |

A repo with no `develop` branch uses `main` as its integration branch for feature work. Release trains still only cut **product** repos that have a version file (`pyproject.toml` and/or `package.json`).

---

## State you keep by hand

Git does not remember “which repos belong to feature X” or “which repos are on train 2026-W34.” You do. A spreadsheet or a text file is enough. Keep these files where the next laptop can see them.

Do not reconstruct membership by scanning dirty directories.

### Feature sheet

One sheet **per feature**. Create it **before** the first line of code, even though you do not yet know which repos will change.

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
- Do not add aux or `*-bom` rows.
- The `pr` column stays empty until you open PRs.
- If `feature/<name>` already exists but has **no work** (clean tree, no commits beyond `develop`), leave that repo **off** the sheet and check out `develop`.

Also keep a one-line **current feature** note so you know which sheet adopt-after-edit writes into.

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

### Hotfix sheet / aux sheet

Same idea: one sheet per name, sparse membership, PR URLs when you open them. Hotfix branches are `hotfix/<name>` (PRs into `main`). Aux branches are `aux/<name>` (PRs into `main`).

### Adoption is already a file

The next system version **is** the `<name>-bom` version object. You do not need a second sheet for pins. You may keep a short note of “what this draft is taking” (train id, or “hotfix renglo-lib only”) in the version object’s description field.

---

## Merge order (fixed)

When several PRs or several release-to-`main` merges belong together, merge in this order. Later rows depend on earlier ones. Merging a consumer first makes its CI red.

1. `renglo-lib`
2. `renglo-api`
3. `console` and every extension (any order among themselves, unless one extension clearly depends on another — then the depended-on one first)

Do not merge a subset. If a later merge fails, stop. Fix that PR or revert what already landed.

You never merge GitHub PRs from a script. Approve in GitHub (or `gh`); merge in GitHub after the whole set is approved.

---

## Catch up the workspace (start of a work session)

After time away, before you write code: every product clone should be on **`develop`**, with other people’s merged features **and** any hotfix that landed on `main`. Do not `git pull` on `main` for this. Fetching while `main` is checked out is how local `develop` and `origin/develop` drift apart.

The workspace must be idle: no dirty files, no in-progress feature/hotfix/aux sheet with participant repos, no train still `cut`/`stabilizing`, and no checkout of `feature/*` / `hotfix/*` / `aux/*` / `release/*` that still has unique commits.

For **each product repo** (and each aux repo that has `develop`):

```bash
git fetch origin --tags --prune
git checkout develop
git merge --ff-only origin/develop
# latest vX.Y.Z stable tag, or origin/main if the repo has none
git merge v1.2.4
git push origin develop
```

Stay on `develop`. Fast-forward local `main` from `origin/main` **without checking it out** (`git fetch origin main:main` when that is a fast-forward) so you are not left on `main` if a step fails.

If a product repo has no `develop` yet (new white-label clone, first checkout), create it from `main` and push it:

```bash
git checkout main
git pull --ff-only origin main
git checkout -b develop
git push -u origin develop
```

Then continue the catch-up on `develop`. BOM repos always stay on `main`.

If `develop` is dirty, or has local commits `origin/develop` does not, stop. Adopt onto a feature branch, or reset, before catching up. On a merge conflict: abort (`git merge --abort`), resolve on a clean `develop`, then retry that repo.

If you already have an in-progress feature, merge `origin/develop` into `feature/<name>` instead (refresh). Do not catch up the whole workspace onto `develop` while that work is unmerged.

---

## Heal `develop` from `main` (any time)

When `develop` has fallen behind tagged `main` — a repo sat out of the last train, a new extension, post-hotfix drift — merge stable back into `develop` even if you are not starting a new feature. Same git as the catch-up above, per product repo. The same merge is required **automatically** before feature PRs, before pushing rc tags, and after publishing stable tags.

---

# Cycle 1 — Daily feature work

## 1. Start the feature on `develop`

1. Write the feature name on a new **feature sheet**. Set `CURRENT_FEATURE` to that name. Repo list empty.
2. In every **product** repo, fetch. Then:

   - If `feature/<name>` **already exists** (this laptop, another checkout, leftover from a previous start): check it out. Put the repo on the sheet **only when it has work** — uncommitted files on that branch, or commits not already in `develop`. If the leftover branch is empty, check out `develop` and leave the repo off the sheet. Keep dirty work already on `feature/<name>`. If you are dirty on some **other** branch, skip that repo (leave the existing feature branch as-is).
   - If there is no `feature/<name>` yet and the tree is clean: check out `develop` (or `main` when the repo has no `develop`) and pull. **Do not create `feature/<name>` yet.** You do not know which repos will change.

   ```bash
   git checkout develop
   git pull origin develop
   ```

3. Implement. Work on `develop` is expected. Example: a Blast Radius handler in `arbitiumtriage` that uses the graph controller in `renglo-lib`, blueprints in `arbitiumlab`, and a modal in `schd`. If a change in `renglo-lib` is truly general, offer it to core rather than overfitting the controller.

4. `*` You only commit in extension repos you own. You may still change several of your own extensions in one feature.

`develop` is the **base**. It is not where feature commits are allowed to stay. After each working session (or after an agent stops), do §2.

---

## 2. Adopt changes onto the feature branch

For **each product repo** that now has uncommitted files, or commits on `develop`/`main` that are not on `origin`, or that already has `feature/<name>` with unique commits:

**Uncommitted changes only**

```bash
git checkout -b feature/blast-radius
# if that branch already exists:
# git checkout feature/blast-radius
```

Add the repo to the feature sheet if it is not already there.

**The work was committed on `develop`** (and not pushed)

```bash
git checkout -b feature/blast-radius
git checkout develop
git reset --hard origin/develop
git checkout feature/blast-radius
```

Add the repo to the feature sheet.

If `develop` was **pushed** with those commits, stop. Do not reset a shared `develop`. Move the work with a revert or a follow-up PR. Treat that as an incident, not a normal adopt.

Empty `feature/<name>` branches (no unique commits, clean tree) stay off the sheet. If they were already listed, drop them and check out `develop`.

Do **not** create `feature/<name>` in repos that did not change. Do **not** adopt aux or `*-bom`.

Then commit **on the feature branch**. Do not commit on `develop`.

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat: blast-radius graph in lib and triage UI

EOF
)"
```

To back up commits on GitHub without a PR:

```bash
git push -u origin feature/blast-radius
```

Uncommitted files stay on the laptop. Status stays `in-progress`.

---

## 2b. Leave a feature and come back

This is ordinary branch switching. Worktrees are not required. If any product repo is dirty, commit or stash first. Do not switch dirty.

**Leave / switch to another feature**

1. Read the **other** feature’s sheet (or start a new empty one).
2. In every repo on **that** sheet: `git checkout feature/<other-name>`.
3. In every other product repo: `git checkout develop` (and pull if you need a clean base).
4. Set `CURRENT_FEATURE` to the name you are on.

**Return** is the same: read **that** sheet, check out listed branches, stay on `develop` everywhere else. If you skip a listed repo, the feature is incomplete and will not run.

To drop a feature sheet: `feature abandon` removes convoy’s table only. It never deletes git branches or uncommitted files. The only command that deletes git branches is `git convoy train delete --yes`, and that refuses dirty trees and unmerged unique commits.

---

## 3. Refresh from `develop`

Other features land on `develop` while you work. Refresh often.

For each repo on the feature sheet:

```bash
git checkout feature/blast-radius
git fetch origin
git merge origin/develop
```

Resolve conflicts yourself, then continue the rest of the sheet. Do not leave a conflicted repo “for later.” Re-run the local stack.

`*` Merging `develop` into **your** extension does not update core. Pull `develop` on read-only core clones (or install the latest core packages) separately.

---

## 4. Open PRs onto `develop`

When the feature is stable on your machine:

1. Refresh from `develop` one last time (§3). Commit.
2. **Heal `develop` from the latest stable tag (or `main`)** in every participant — same commands as [Heal develop from main](#heal-develop-from-main-any-time). This absorbs hotfixes and repos that sat out of the last train **before** the PR, not on the train. Conflicts **block** PR creation. Resolve on `develop`, then retry. After a successful sync, check the feature branch out again.
3. Push every branch on the feature sheet:

   ```bash
   git push -u origin feature/blast-radius
   ```

4. Open one pull request per listed repo: `feature/<name>` → `develop` (`main` if that repo has no `develop`). Put the PR URL on the sheet. If you use `gh`:

   ```bash
   gh pr create --base develop --head feature/blast-radius --title "feat: blast-radius" --body "…"
   ```

   Without `gh`, open the compare URL in the browser:

   `https://github.com/<org>/<repo>/compare/develop...feature/blast-radius`

5. Keep a tracking list of every sibling PR (the sheet is enough). GitHub has no cross-repo PR. Mark the sheet `in-review`.

**Review**

- Comment on any PR. Approve on GitHub as usual (branch protection, CODEOWNERS, and CI stay real). `gh pr review --approve` is the same action.
- Do **not** merge until every sibling PR is approved and its CI is green.
- If one PR is rejected, none of them merge.

**Merge status by hand:** a participant is `uncommitted` if the feature branch has a dirty tree; `pending` if a PR is open; `merged` when the feature-branch tip is contained in `develop` (squash merges need the GitHub PR state, not git ancestry alone). When every participant is merged, mark the sheet `merged`.

**Merge** (after the whole set is approved) in the [fixed order](#merge-order-fixed). Merge stays in GitHub.

`*` Same process; the set never includes core repos.

---

## 5. Close the feature

After every PR is merged:

```bash
git checkout develop
git pull origin develop
git branch -d feature/blast-radius
# optional: git push origin --delete feature/blast-radius
```

Do that in every listed repo. Remove the feature sheet. Do not close while any participant still has uncommitted work, an open PR, or commits not in `develop`.

When those PRs merge, the feature is on `develop`. Cycle 2 turns that `develop` into release branches.

---

# Cycle 2 — Release trains (local)

A **train** is a coordination label, not a version. `renglo-lib` may be `1.2.4` while `renglo-api` is `2.3.1` and `breakdown` is `0.0.3`. They can still share `release/2026-W34`.

Prefer a sortable train id: `2026-W34` (ISO week) or the cutoff date. Avoid `week-34` without a year. The name is **not** any package’s semver.

Until you cut, merged features only exist on `develop`. This cycle does **not** push tags and does **not** touch the registry. You can cut → fix → recut (after deleting a botched cut) many times before cycle 3.

**Who is on the train**

A product repo is on the train only if its integration branch (`develop`, or `main` when there is no `develop`) has commits that are not in its last **stable** `v*` tag, **and** that tag is an ancestor of the tip. Unchanged repos sit out. Repos with no version file sit out.

If `develop` never received the last tagged `main` (you skipped [mergeback](#10-merge-tagged-main-back-into-develop)), the next cut looks empty even after features merged. Heal develop first.

### Example — Friday of week 34

| Feature | Repos | Friday afternoon |
| ------- | ----- | ---------------- |
| **X** invoice rounding | `renglo-lib`, `breakdown` | Merged to `develop` |
| **Y** login timeout | `renglo-api`, `console` | Merged to `develop` |
| **Z** export CSV | `schd` | Still on `feature/export-csv` |

Nothing on `develop` for `schd` (Z has not merged). That repo sits this train out.

---

## 6. Cut the train

For each participating repo, after the cutoff:

```bash
git checkout develop
git pull origin develop
git checkout -b release/2026-W34
```

Write a row on the **train sheet**. Default bump is **PATCH** for what is on `develop` since the last stable tag (`1.2.3` → `1.2.4`). Use MINOR or MAJOR only when the change really needs it. Do not bump every commit; bump once when you cut.

On the release branch, write that number **with an rc suffix** in the version files. Python and the extension UI stay on the same number.

| Kind | File | Example |
| ---- | ---- | ------- |
| Python | `pyproject.toml` / `setup.py` | `1.2.4rc1` |
| npm (extension UI) | `ui/package.json` | `1.2.4-rc.1` |

```bash
git add -A
git commit -m "Set 1.2.4rc1 for train 2026-W34"
```

Do **not** push a `v*` tag yet. That is cycle 3. You may push `release/2026-W34` if you want the branch on origin; tagging is what publishes.

Status → `cut`.

To add a product repo that was left off the cut (dirty work on `develop`/`main`, or a named clean repo), check out or create `release/<train>` from the current integration branch, add a sheet row, and **do not bump versions**. Refuse dirty work on `feature/*`. Ignore aux and BOM.

---

## 7. Stabilize on the release branch

Bugfixes and release prep only. No new features.

Commit on `release/<train>` in each participant:

```bash
git add -A
git commit -m "fix: …"
```

Merge those fixes **back to `develop`** so the next train does not lose them.

Do not push rc tags while any participant is dirty — commit first.

To throw away a botched cut: check out `develop` in each participant, delete local `release/<name>` (and origin if you pushed it), remove the train sheet. Recut only after that.

**Optional — stay in cycle 2:** you may create rc (or even stable) tags **locally** and merge to `main` **without pushing**. That updates git only. Do not do that if you plan to run cycles 3–4; pushed tags are what CI publishes, and you must not reuse a `v*` tag that already exists.

The train is ready for cycle 3 when the release branch set is coherent on your machine.

---

# Cycle 3 — Staging adoption (registry + cloud test)

Prerequisites: publisher stack, per-repo tag-publish workflows, BOM repo. Full detail is in the README.

**Console** is special today: it deploys from a **git clone**, not CodeArtifact. Until it has a working workflow on `v*` tag push, pin console by `repos.*.commit` only. Do not leave a stale `npm.@renglo/console` pin.

---

## 8. Push rc tags (publish release candidates)

For each train participant:

1. Heal that repo’s `develop` from its latest stable tag (or `main`). Sync failures should be resolved during stabilization; you may still tag from the release branch, but do not ignore a broken `develop`.
2. Check out `release/<train>`. If the version files are not already an rc, write `X.Y.ZrcN` / `X.Y.Z-rc.N`.
3. Choose a **free** tag. Do not reuse a `v*` tag that already exists locally or on origin unless it already points at HEAD. Walk `rc.N` until one is free. If `vX.Y.Z` was already released, start at `vX.Y.Z+1-rc.1` instead of minting another `X.Y.Z-rc.N`.
4. Commit version files if they changed, then:

   ```bash
   git push -u origin release/2026-W34
   git tag v1.2.4-rc.1
   git push origin v1.2.4-rc.1
   ```

Write `rc-tag` on the train sheet. Status → `stabilizing`. Repeat per participant (each has its own semver). **CI publishes rc packages to CodeArtifact.**

When `release/<name>` has new commits past the current rc tag, bump the rc suffix for that repo (`rc.1` → `rc.2`) and leave unchanged repos on their existing rc.

---

## 9. Confirm publish CI, then draft the staging BOM

Watch GitHub Actions on **each** participant for workflows that trigger on **`v*` tag push** (any filename: `publish.yml`, `publish-python.yml`, `publish-extension.yml`, …). If a repo has several such workflows, **all** must succeed. Repos with **no** tag-publish workflow (console today) are not failures — they are git-clone participants.

Pin strategy for this system version:

| Publish CI | What to write in the BOM |
| ---------- | ------------------------ |
| **success** | `python` / `npm` registry versions (rc). Remove a redundant `repos` SHA for that package. |
| **skip** (no tag-publish workflow) | `repos.<org/repo>.commit` only (console today). |
| **failure** / pending / missing tag | **Do not invent a registry pin.** Clear `python`/`npm` for that package and fall back to `repos.*.commit`. |

Do not write an npm/python pin for a package that failed publish CI — deploy will try CodeArtifact and fail.

**First adopt for this train:** copy the last system version that is known good (usually production, or the last good staging draft). Patch-bump the **system** version (`v1.4.0` → `v1.4.1`). That copy is the new draft. Point `deploy_targets.yml` at it. Keep `production.enabled: false`.

**Later adopt, same train:** do **not** copy to a new file. Refresh pins **in the same** `bom/vX.Y.Z.json`.

Work in the `<name>-bom` repo on `main`. git-convoy does not push this repo. **You** commit and push; that push deploys.

### Example — first staging draft of train `2026-W34`

Production is on system version `v1.4.0`. The train sheet has rc tags for `renglo-lib`, `renglo-api`, and `breakdown`. Console has no tag-publish workflow.

```bash
cd ops/example-bom
git checkout main
git pull origin main
cp bom/v1.4.0.json bom/v1.4.1.json
```

Last good BOM (`bom/v1.4.0.json`):

```json
{
  "version": "v1.4.0",
  "train": "2026-W33",
  "description": "Production. Release 2026-W33.",
  "python": {
    "renglo-lib": "1.2.3",
    "renglo-api": "2.3.0",
    "renglo-breakdown": "0.0.2",
    "renglo-schd": "1.1.0"
  },
  "npm": {
    "@renglo/breakdown": "0.0.2",
    "@renglo/schd": "1.1.0"
  },
  "repos": {
    "renglo/console": {
      "url": "git@github.com:renglo/console.git",
      "branch": "main",
      "commit": "aaa111…"
    }
  }
}
```

Edit the copy. Bump only what the train shipped. Use **rc** versions for packages whose publish workflow succeeded. Keep `renglo-schd` as it was. Pin console by git SHA (HEAD of `release/2026-W34` or the rc tag).

`bom/v1.4.1.json`:

```json
{
  "version": "v1.4.1",
  "train": "2026-W34",
  "description": "Draft. Taking 2026-W34. Not production.",
  "python": {
    "renglo-lib": "1.2.4rc1",
    "renglo-api": "2.3.1rc1",
    "renglo-breakdown": "0.0.3rc1",
    "renglo-schd": "1.1.0"
  },
  "npm": {
    "@renglo/breakdown": "0.0.3-rc.1",
    "@renglo/schd": "1.1.0"
  },
  "repos": {
    "renglo/console": {
      "url": "git@github.com:renglo/console.git",
      "branch": "main",
      "commit": "bbb222…"
    }
  }
}
```

`deploy_targets.yml` — point at the draft, production off:

```yaml
bom: 1.4.1

tenants:
  example:
    stages:
      staging:
        enabled: true
      production:
        enabled: false
```

Leave the old `bom/v1.4.0.json` on disk. That is the rollback pin list.

```bash
git add bom/v1.4.1.json deploy_targets.yml
git commit -m "$(cat <<'EOF'
Draft system v1.4.1 from train 2026-W34; staging only.

EOF
)"
git push origin main
```

Watch the deploy workflow. Confirm `production.enabled` is still `false`. When staging is up, run the tester checks you already use.

**If staging fails**, do **one** of the following. Do not walk a dependency graph and guess:

1. **Fix forward on the train:** commit on `release/<name>`, merge that fix back to `develop`, push a new rc tag (§8), refresh **the same** BOM file (§9), push again. Many attempts are fine. Train stays `stabilizing` until cycle 4.
2. **Pin back** the package that broke the combination (edit the same draft; do not copy to a new version). Adopt less, or wait for the next train.
3. **Take the rest of the set.** If `renglo-lib` now requires an app id on every API call, you cannot take that lib pin until the extensions you run have been updated and published. That work is cycle 1. Adopt the whole set, or none of it.

Do not invent a pin that is not in the registry (or, for git-clone participants, a SHA that is not on the train).

**End of cycle 3:** staging runs the train; production is unchanged. Stop here if you do not want production yet.

---

# Cycle 4 — Production release

Cycle 4 ships **stable** packages to the registry and enables production on the **same** BOM file staging already uses. Prerequisites: cycle 3 complete and staging acceptable.

---

## 10. Publish stable packages

For each repo on the train sheet, on the release branch, in [merge order](#merge-order-fixed):

1. Edit the version files: **drop the rc**. `1.2.4rc1` → `1.2.4`. Same number. Do not increment.
2. Merge to `main`, tag, push:

   ```bash
   git add -A
   git commit -m "Release 1.2.4"

   git checkout main
   git pull --ff-only origin main
   git merge release/2026-W34
   git push origin main
   git tag v1.2.4
   git push origin v1.2.4
   ```

3. Write the stable tag on the train sheet.

If a merge to `main` fails, **stop**. Do not continue the set.

Status → `published` as soon as the stable tags exist. **CI publishes stable packages.** Confirm publish workflows the same way as §9.

`*` Your extension may publish on the same Sunday as the official train, or later, using the same steps on your own repos.

On the train sheet, record **which features** this train carried. Package tags do not list features.

---

## 11. Merge tagged `main` back into `develop`

This is required after every stable publish. It is what lets the **next** train cut see new work.

For **every product repo** (train participants **and** sit-outs):

- Participants: merge **that repo’s stable tag** from the train sheet into `develop`.
- Others: merge their latest `v*` stable tag, or `main` if they have none.

Same commands as [Heal develop from main](#heal-develop-from-main-any-time). Push `develop` when origin exists. Repos with no `develop` stay on `main`.

Already-synced repos are skipped. On conflict: abort the merge, leave the repo clean, fix, retry. Continue past per-repo failures so the rest of the set can still sync. Re-run this step any time `develop` is behind the stable tag.

If publish tagging succeeded but mergeback failed, the tags on `main` are still valid. Fix `develop` and retry mergeback. Do not re-tag.

---

## 12. Enable production on the BOM

Refresh **stable** pins in the **current** BOM file (the same `v1.4.1` staging used). Description like `Production. Release 2026-W34.`. Set `production.enabled: true`.

Refuse this step while the train is still `stabilizing`, or while the BOM still has rc pins. Run §10–§11 first, then rewrite rc → stable in that file.

```json
{
  "version": "v1.4.1",
  "train": "2026-W34",
  "description": "Production. Release 2026-W34.",
  "python": {
    "renglo-lib": "1.2.4",
    "renglo-api": "2.3.1",
    "renglo-breakdown": "0.0.3",
    "renglo-schd": "1.1.0"
  },
  "npm": {
    "@renglo/breakdown": "0.0.3",
    "@renglo/schd": "1.1.0"
  },
  "repos": {
    "renglo/console": {
      "url": "git@github.com:renglo/console.git",
      "branch": "main",
      "commit": "ccc333…"
    }
  }
}
```

Do not copy the JSON to a new version. Do not change pins except dropping rc and updating git-clone SHAs to the stable tag.

```bash
git add bom/v1.4.1.json deploy_targets.yml
git commit -m "$(cat <<'EOF'
Promote system v1.4.1 to production.

EOF
)"
git push origin main
```

CI runs **staging deploy → smoke check → production deploy** in one workflow. Production is blocked if staging fails. Watch GitHub Actions.

**Optional safe path:** first refresh stable pins with `production.enabled` still `false`, push, confirm staging on the stable build, then turn production on and push again.

Once production is up, the published train is finished. Do not push more rc tags or refresh this train’s BOM. Check participants out to `develop`/`main` and delete local `release/<name>` (and origin if it is still there). That does **not** unpublish packages or disable production. The next ship starts with a new cut.

### Roll back to the previous system version

Do not edit `v1.4.1.json`. Point deploy at the previous file.

```yaml
bom: 1.4.0
```

Keep `production.enabled: true` if you want production to run the old pins immediately. Commit and push. The next attempt is a **new** system version: copy from whichever object you trust, and start at cycle 3.

---

# Aux — Platform tooling

Use this for repos that must not ride product trains (launcher, bom-helper, git-convoy, publisher, bootstrap, …). Each such repo should mark itself aux (`gitconvoy.toml` with `role = "aux"`; BOM repos use `role = "bom"`). Unmarked repos are product.

Lifecycle is hotfix-style on **aux repos only**. Branch prefix `aux/<name>`. PRs target **`main`**. After those PRs merge, merge **`main` → `develop`** so develop stays current — no second PR. If `develop` is missing, create it from `main`. Independent of the current feature/train/hotfix.

1. Empty aux sheet. Check out the integration branch in clean aux repos that do not already have `aux/<name>`. Pick up existing `aux/<name>` only when it has work (same rules as feature start).
2. Edit. Then for each dirty aux repo (or one with unique commits): create or check out `aux/<name>`. If you committed on `develop`/`main` and did not push, reset that local integration branch to origin. Do not adopt dirty **product** repos onto an aux sheet.
3. Commit on `aux/<name>`. Push if you want a backup without a PR.
4. Before opening PRs: if local `main` has commits origin does not, move them onto `aux/<name>` (cherry-pick), then reset local `main` to `origin/main`. A cherry-pick conflict leaves the repo in the cherry-pick: resolve, `git add`, `git cherry-pick --continue`, then continue.
5. Open PRs: `aux/<name>` → `main`. Approve the set. Merge in GitHub (merge order if several).
6. After every PR is merged: merge `main` into `develop` in each participant, push `develop`, check out `develop`, delete local `aux/<name>`. Remove the sheet.

Do not use this path to change BOM pins. That is cycle 3–4 / hotfix adopt on the BOM repo’s `main`.

---

# Hotfix — Production emergency

Do not wait for the next train. A hotfix may change **more than one product repository**. PRs go to **`main`**. After tags land, send the patch back to `develop` and into local in-progress `feature/*` so every branch in process gets it.

1. **Start.** You must be on `main`, `develop`, or an existing `hotfix/<name>` — not a dirty `feature/*`. Do not convert `feature/<name>` into a hotfix.

   Take dirty product repos, or name the repos. For each:

   ```bash
   git fetch origin
   git checkout main
   git pull --ff-only origin main
   git checkout -b hotfix/fetch-file
   ```

   Bump **PATCH** only in the version files (`1.2.4` → `1.2.5`) and commit that bump on the hotfix branch. If `hotfix/<name>` **already exists**, check it out, put those repos on the sheet, and **do not bump PATCH again**.

2. **Fix** (if the work is not already in the tree). Commit on `hotfix/<name>`.

   ```bash
   git push -u origin hotfix/fetch-file
   ```

3. **PRs into `main`** (not `develop`):

   `https://github.com/<org>/<repo>/compare/main...hotfix/fetch-file`

   Merge in [merge order](#merge-order-fixed) after the whole set is approved. You do not merge from a script.

4. **Publish.** Wait until each hotfix branch is on `main` (squash-safe: `main` already has the expected PATCH). Then on `main`:

   ```bash
   git checkout main
   git pull --ff-only origin main
   git tag v1.2.5
   git push origin main
   git push origin v1.2.5
   ```

   Merge tagged `main` into `develop` and push `develop` (same as heal-develop). Then, in that repo, merge that `develop` into every **local** `feature/*`:

   ```bash
   git checkout feature/blast-radius
   git merge develop
   ```

   On conflict, abort or resolve; then refresh the feature from `develop` (§3).

5. **Adopt onto staging.** Copy the last good system version to a new **PATCH** (`v1.4.0` → `v1.4.1`). Pin **only** the hotfix packages (stable versions, not rc). Leave every other pin. Point `bom:` at the new file. Keep `production.enabled: false`. Commit and push the BOM.

   When staging is acceptable, turn production on **for that same file** (description, `production.enabled: true`) and push. Do not enable production in the same push as the first staging draft.

---

## Checklist (one pass)

**Feature**

- [ ] After time away: workspace idle; every product repo on `develop` with `origin/develop` and latest stable/`main` absorbed
- [ ] Feature sheet created; current name set; repo list empty
- [ ] Product repos on `develop` (or existing `feature/<name>` only if it has work)
- [ ] After each session: changed repos adopted onto `feature/<name>`; `develop` reset if you committed there; empty leftover branches dropped from the sheet
- [ ] Refreshed from `develop`; conflicts resolved
- [ ] Latest stable/`main` merged into `develop` in each participant **before** PRs
- [ ] PRs open for every sheet row; tracking list filled
- [ ] All PRs approved; merged in lib → api → consumers; sheet marked `merged`
- [ ] Closed: `develop` checked out; local `feature/<name>` deleted

**Train (local, cycle 2)**

- [ ] Train sheet: only product repos ahead of last stable tag, with a version file
- [ ] `release/<train-id>` cut; PATCH (unless MINOR/MAJOR is required) written as rc; **no** `v*` tag pushed yet
- [ ] Fixes on the release branch copied back to `develop`

**Staging (cycle 3)**

- [ ] `develop` healed from stable in participants; free `vX.Y.Z-rc.N` pushed; CI publish green (or git-clone fallback)
- [ ] First adopt: new system PATCH, rc (or git SHA) pins, `production.enabled: false`
- [ ] Later adopts for the same train refresh **that same file**
- [ ] Staging green; iterate on `release/<name>` + new rc rather than guessing pins

**Production (cycle 4)**

- [ ] rc dropped (same number); merged to `main` in merge order; `vX.Y.Z` pushed
- [ ] Tagged `main` merged into `develop` for **all** product repos (and pushed)
- [ ] Same BOM file: stable pins, production enabled; previous version object left for rollback
- [ ] Local `release/<name>` deleted; next ship is a new cut

**Hotfix**

- [ ] `hotfix/<name>` from `main` on every repo that must change; PATCH only (no second bump if the branch already exists)
- [ ] PRs merged into `main` in merge order; tags pushed
- [ ] Tagged `main` merged into `develop` (and pushed); in-progress `feature/*` absorbed
- [ ] BOM patch pins only those packages; staging first, then production

**Aux**

- [ ] Only aux repos on the sheet; PRs into `main`
- [ ] After merge: `main` → `develop`; aux branches deleted

**Adoption invariants**

- [ ] Draft copied from last good system version (or refreshed in place for the same train)
- [ ] No registry pin for a failed publish; console stays on `repos.*.commit` until it publishes
- [ ] Staging green on that exact list before production
- [ ] Same list in production; previous version object left untouched for rollback
- [ ] You pushed `*-bom` yourself; nothing else deploys it
