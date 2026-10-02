# The process: flying a TYPO3 upgrade with the pilot

This guide walks through a complete upgrade with the `fly-the-upgrade` plugin:
what happens in each phase, which commands run in which order and how often,
what gets written along the way, and where a person has to look, decide or
correct something. Claude runs the commands for you. Knowing them lets you
follow along, step in, or run a single step yourself.

All commands are `upgrade-pilot <command>`. `upgrade-pilot <command> --help`
shows every option.

---

## Contents

1. [Overview](#1-overview)
2. [Before you start](#2-before-you-start)
3. [Initialization](#3-initialization)
4. [Pre-analysis: the assessment](#4-pre-analysis-the-assessment)
5. [Working rules: branches, commits, composer, issues](#5-working-rules-branches-commits-composer-issues)
6. [Phase 1: Pre-flight](#6-phase-1-pre-flight)
7. [Phase 2: Flight](#7-phase-2-flight)
8. [Phase 3: Post-flight](#8-phase-3-post-flight)
9. [The rule-by-rule loop](#9-the-rule-by-rule-loop)
10. [Reports and summaries](#10-reports-and-summaries)
11. [Manual investigations and corrections](#11-manual-investigations-and-corrections)
12. [What ends up where](#12-what-ends-up-where)
13. [Resuming, re-running, starting over](#13-resuming-re-running-starting-over)

---

## 1. Overview

| Phase | Goal | Branch | Ends with |
|---|---|---|---|
| **Pre-flight** | Know the aircraft and the route, build the instruments, clean up on the **current** version | `<prefix>/preflight-<source>` from your base branch | Gate *Go / No-Go* |
| **Flight** | Raise the core, migrate code and data, get every test green on the **target** version | `<prefix>/<target>` from the pre-flight branch | Gate *Cleared to hand over* |
| **Post-flight** | Sweep with the new rules, remove what only the upgrade needed, record everything | same flight branch | Gate *Debriefed* |

Three things run through all phases:

- **The checklist** (the 68 lines of the talk, plus ten about third-party
  packages, security, patches, deployment and go-live blockers). Every line is answered: `done`,
  `no` (an accepted risk, with the reason), `na`, or `handoff` (a person has to
  do or confirm it). Open lines block the gate.
- **The instruments.** Every claim is measured: test suites (`measure`),
  Extension Scanner (`scan`), TCA migrations (`tca`), schema (`schema`).
- **The reports.** At every gate a developer report and a PM/customer report
  (English and German).

Who does what:

| The pilot (Claude with the CLI) | You and your team |
|---|---|
| detection, measurements, scans, dry runs | choosing the runtime, commit style, issue handling at init |
| reading changelogs and upgrade notes of core and dependencies | reviewing the QRH, MEL and briefing |
| writing missing tests, applying and reviewing rules, fixing code | gate decisions (unless you chose automatic gates) |
| commits on the pilot branches, in your style | production backup, freeze, staging, editor acceptance |
| reports with facts, summaries in plain language | merging, pushing, deploying |

Updating or only checking selected third-party packages, without a core
upgrade, uses the same phases with its own checklist:
**[Scenario: updating or checking selected packages](SCENARIO-PACKAGES.md)**.

---

## 2. Before you start

- Clean working tree on the branch the upgrade starts from.
- The instance runs locally (ddev, direnv or local PHP) with an installed
  database. Test suites can be started with one command each.
- Tooling as dev dependencies (the pre-flight tells you what is missing):
  `ssch/typo3-rector`, `a9f/typo3-fractor`, `typo3/testing-framework`,
  `netresearch/extension-scanner-cli`.
- Collect what you already know: pre-analysis issues, customer requirements,
  notes from an earlier attempt. They become the flight's context.

---

## 3. Initialization

Start with `/fly-the-upgrade:upgrade <target>` or ask Claude to upgrade the
project. Claude first looks at the project:

```bash
upgrade-pilot init --detect
```

It reports:

- **ddev**: `.ddev/config.yaml` and the `ddev` binary.
- **direnv**: an `.envrc` in the project folder or one folder above, whether
  direnv is installed, the state of the `.envrc` (`allowed`, `not allowed yet`,
  `denied`, read from `direnv status`), and whether `php` and `composer` work
  inside it. The pilot never runs `direnv allow`: an `.envrc` executes code, you
  review and allow it yourself.
- **local** PHP and composer on the host.
- **commit style evidence** from `git log`: TYPO3 tags, issue keys in subjects
  (`[TASK] PRJ-123: ...`), footers (`Resolves:`, `Related:`).

Then Claude asks you:

| Question | Options | Stored as |
|---|---|---|
| Runtime | ddev, direnv, local PHP, custom exec template | `--runtime`, `--exec`, `--composer` |
| Commit style | TYPO3 Core (`[TAG] Subject`, 52/72, no Resolves/Releases, refs as `Related:`), YouTrack (`[TAG] PRJ-123: Subject` + `Related:`), custom template | `--commit-style`, `--commit-template` |
| Issue references | none, one reference for everything, parent + one issue per step (needs tracker access in the session), placeholders + `ISSUES.md` | `--issue-mode`, `--issue`, `--tracker`, `--project-key` |
| Gates | human (default) or automatic by the written criteria | `--gates` |
| Extras | PHP level set as extra Rector campaign, pre-collected context, pushing (blocked by default) | `--php-set`, `--context`, `--allow-push` |

Example, ddev project in a YouTrack team that creates the issues later:

```bash
upgrade-pilot init --target 13.4 --runtime ddev --gates human \
    --commit-style youtrack --tracker youtrack --project-key PRJ \
    --issue-mode placeholder --issue PRJ-100 \
    --context PRJ-87 --context ./docs/customer-requirements.md
```

Example, direnv, TYPO3 Core style, one issue for everything:

```bash
upgrade-pilot init --target 14.3 --runtime direnv --commit-style typo3 \
    --issue-mode single --issue PRJ-240
```

`init` writes `.upgrade-pilot/` (excluded from git through
`.git/info/exclude`), detects your own extensions and test commands, and
records the platform.

**Check by hand:** the detected test commands and own extensions (correct
`.upgrade-pilot/config.json` if needed), then run each suite once.

**Context.** Every `--context` reference is read before planning: Claude reads
issues with the tools the session has (a YouTrack MCP server, `gh`, `glab`),
files are copied. Each gets a digest:

```bash
upgrade-pilot context list
upgrade-pilot context add PRJ-87 --title "Pre-analysis" --file digest.md
```

---

## 4. Pre-analysis: the assessment

Right after initialization, before any branch exists and before anything
changes, the pilot writes a pre-analysis. It answers whether the upgrade can
start, what has to be decided first, and how big the work is:

```bash
upgrade-pilot assess              # complete, a few minutes (reads dependency sources)
upgrade-pilot assess --quick      # without dependency documentation and the core changelog
upgrade-pilot assess --render     # render the reports again after writing the summaries
```

Every step is read-only. The composer probe changes `composer.json` and the
lock file for a moment and restores them byte for byte.

| Step | What it does |
|---|---|
| Versions | support dates, PHP range and the newest patch of the target core (`versions`) |
| Release check | every third-party TYPO3 extension and every direct requirement, see below |
| Security | `composer audit` of the installed lock file and of the target lock file the probe writes, plus abandoned packages |
| Probe | `bump probe --audit`: does the target graph resolve |
| Dependency documentation | `deps docs` for what moves, or per package at the version the release check found when the graph does not resolve as a whole |
| Touchpoints | `deps touchpoints --verify --coverage`: where your code modifies the packages, and whether a test mentions each place |
| Core changelog | `changelog fetch`, `changelog match` |
| Patches | `patches`: every composer patch against the target version, see below |
| Deployment and CI | `delivery`: CI and deployment files against the target, see below |

**The release check.** The pilot only plans with released versions. For each
package it asks Packagist (or, for packages from other repositories, composer
itself with the project's credentials), the TYPO3 Extension Repository by
extension key (its REST API), and the development branches:

| Status | Meaning | What happens |
|---|---|---|
| `released` | a stable release supports the target | the flight raises the constraint, the report says if the current constraint does not allow it |
| `released-ter` | only the TER has such a release | ask the maintainers, or install it differently |
| `dev-only` | only a development line (`dev-main`, `v14.x-dev`, a branch alias) requires the target | **decision**: use it meanwhile as a go-live blocker, or hold |
| `claimed` | no version requires the target, but the documentation of a development line mentions it (`ext_emconf.php` range, README, manual) | read the claim, it may point to a version elsewhere (an early access program, a fork), then decide |
| `none` | nothing supports the target | **decision**: replace, drop, fork, or hold |
| `independent` | no TYPO3 requirement | left to composer |

Abandoned packages, the date of the latest release and the PHP requirement of
the release are reported as well.

**Decisions.** Claude asks you for every `dev-only`, `claimed` and `none`
package:

- **Use the development version meanwhile, as a go-live blocker.** The flight
  continues with it and can land, but nothing is releasable until the blocker
  is resolved:

  ```bash
  upgrade-pilot blockers add --package acme/shop --use dev-main \
      --reason "no release supports TYPO3 14.3 yet" --waits-for "release 3.0.0"
  upgrade-pilot blockers list
  upgrade-pilot blockers check --package acme/shop
  upgrade-pilot blockers resolve --package acme/shop --note "3.0.0 released and verified"
  upgrade-pilot blockers drop --package acme/shop --note "replaced by acme/shop-ng"
  ```

  `resolve` refuses until every check passes: a stable version is installed,
  it supports the target core, `composer.lock` with it is committed, every
  configured test suite was measured green after that commit, and the
  package's touchpoints were verified after it with nothing left that needs
  attention. Open blockers appear in `status`, at every gate, in every report,
  and the final status reads "not releasable".
- **Hold the upgrade.** The pre-flight gate is closed with a No-Go and the
  reason (`gate preflight nogo --note "..."`). Running `assess` again later
  shows what changed.

**Re-check.** Every assessment is kept in `.upgrade-pilot/assessments/`. Each
new run compares itself with the previous one (or with `--since <file>`):
packages whose status or version changed, new and resolved advisories, a
probe that resolves now, and go-live blockers that can be resolved because a
release has appeared.

**Patches.** Both composer patch plugins are read with their own rules:

| Plugin | Where patches are defined | Strip level | Version constraints |
|---|---|---|---|
| `cweagans/composer-patches` 1.x | root `extra.patches`, or `extra.patches-file` when `patches` is not set, dependencies when patching is enabled | `-p1`, `-p0`, `-p2`, `-p4` tried, `extra.patchLevel` forces one | none |
| `cweagans/composer-patches` 2.x | root `extra.patches` (compact or expanded), `patches.json`, dependencies. `patches.lock.json` wins when it exists | one `depth` per patch, package or default | none |
| `vaimo/composer-patches` | `extra.patches`, `patches-file`, `patches-search` directories with `@package`/`@version`/`@level` header tags, the same under `extra.patcher`, in the root and in dependencies (paths relative to the defining package) | `0`, `1`, `2` tried, `level` forces one | `version`, or `{"<constraint>": "file"}` |

Each patch is checked with `git apply --check` against the package's source
at the target version: `applies`, `fails` (rebase it), `contained` (the change
is upstream, remove the patch), `retired` (its version constraint excludes the
target and the change is upstream), `out of range` (excluded by its
constraint, and the change would be lost).

**Deployment and CI.** `delivery` reads CI configurations (GitHub, GitLab,
Bitbucket, Jenkins and others), deployment recipes (Deployer, Surf,
Magallanes), Dockerfiles, compose files, ddev and platform configuration and
shell scripts. It reports PHP versions outside the target core's range, calls
of `typo3cms` (gone with TYPO3 Console 8, checked against what is installed),
`typo3` commands the instance does not know (`typo3 list` of the source in the
pre-flight, of the target after the upgrade), and composer calls that switch
platform checks off.

The assessment reports are `reports/assessment-dev.en.md`,
`reports/assessment-pm.en.md` and `reports/assessment-pm.de.md`, with
summaries Claude writes into `notes/assessment-*.md`. The PM reports list the
decisions, the go-live blockers, security and the size of the work in counted
numbers, never in estimated hours.

---

## 5. Working rules: branches, commits, composer, issues

**Branches.** Nothing lands on your base branch while the flight is open.
The plugin's hook blocks merges, commits, rebases, resets and pushes onto
it. Unless you chose `--allow-push`, **every push** and every pull or merge
request creation is blocked as well. The flight commits locally, you decide
what to push.

**Commits.** Every commit goes through the CLI, in small logical units, each
with a step name:

```bash
upgrade-pilot commit --tag TASK --subject "Cover the booking plugin with a frontend test" \
    --body-file body.txt --step instruments
upgrade-pilot commit ... --dry-run          # show the message only
```

The CLI renders the style chosen at init, adds the issue reference for the
step, `Related:` lines, and the commands behind composer changes. It warns
when the subject exceeds 52 characters.

**Composer.** `composer.json` and `composer.lock` change only through
commands, which are recorded and listed in the commit:

```bash
upgrade-pilot composer require 'helhum/typo3-console:^9.0'
upgrade-pilot composer update -W
upgrade-pilot run -- "jq --indent 4 '.config.platform.php = \"8.2.0\"' composer.json > c.tmp && mv c.tmp composer.json"
upgrade-pilot composer --no-record show 'typo3/*'      # read-only, not recorded
```

A commit with changed composer files and no recorded command is refused.
Prefer composer's own commands (`require`, `remove`, `config`). If `jq` is
needed, use `--indent 4`, otherwise the whole file is re-indented. The commit
message gets:

````text
Used command(s):

```bash
composer require --no-update \
    'typo3/cms-core:^13.4' \
    'typo3/cms-backend:^13.4'
composer update -W --no-interaction
```
````

**Composer changes first.** Aim for the composer change to be the first
commit of a branch. A later composer-only change is folded into it:

```bash
upgrade-pilot commit --tag TASK --subject "..." --step bump --into-composer-commit
```

The fold rewrites the local branch through git plumbing: authors and dates
stay, later commits are recreated on top. It falls back to a normal commit
when a later commit touched composer files, or the composer commit is part of
another pilot branch. It is a preference, not a rule.

**Issue references.**

| Mode | What happens |
|---|---|
| `none` | no references |
| `single` | every commit references `--issue` |
| `per-step` | `--issue` is the parent. Before the first commit of a step, an issue is created in the tracker (by Claude, when the session can) and registered: `upgrade-pilot issues set --step bump --number PRJ-311 --title "..."`. Commits reference it, `Related:` names the parent |
| `placeholder` | commits get `{ISSUE-01}`, `{ISSUE-02}`, ... per step. `.upgrade-pilot/ISSUES.md` lists them with title, description and commits. You create the issues, write the numbers into the "Issue" column, then `upgrade-pilot issues apply` replaces the placeholders in the history of both pilot branches |

`issues apply` rewrites local, unpushed history only. Run it before anything
is pushed.

---

## 6. Phase 1: Pre-flight

Nothing here touches the target version. Everything committed runs on the
current version and could be deployed before the upgrade.

| # | Step | Commands | Produces | Look at by hand |
|---|---|---|---|---|
| pre | Pre-analysis | `assess`, then a decision per unreleased package: `blockers add` or `gate preflight nogo` (hold) | `reports/assessment-*`, `assessments/<time>.json` | decisions, the PM report before you send it |
| 0 | Branch | `git switch -c <prefix>/preflight-<source>` | | |
| 1 | Context | `context list`, `context add` | `context/*.md` | contradictions between context and tools |
| 2 | Aircraft | `composer outdated "typo3/cms-*" --direct --patch-only`, `versions` | platform facts | owners of own extensions |
| 3 | Bump probe | `bump probe` | probe log (`composer require --no-update` + `update -W --dry-run`, files restored) | every "Problem N" |
| 4 | Dependencies | `deps list`, `deps docs` | `deps/<package>-<from>-<to>.md` per package | breaking entries, new wizards, "nothing documented" |
| 4b | Modifications, patches, deployment | `deps touchpoints --verify --coverage`, `patches`, `delivery --label preflight` | `touchpoints.json`, `patches.json`, `delivery.json` | `attention` entries, untested touchpoints, failing patches, broken scripts |
| 5 | Core changelog | `changelog fetch`, `changelog match` | `changelog-<from>-<to>.json` | every strong entry's rst |
| 6 | Instruments | `contacts`, write tests, `commit --step instruments` | tests, `contacts.json` | untested contact points, dead code |
| 7 | Baseline | `measure --label baseline` | the reference for the whole flight | unexplained failures |
| 8 | Scan + TCA | `scan --label preflight`, `tca --label preflight` | counts and messages | strong findings |
| 9 | Rector/Fractor, current rules | `rules config --tool rector --level <source>`, then the [loop](#9-the-rule-by-rule-loop), same for Fractor | one commit per rule | every diff, generated code |
| 10 | Hand fixes | code changes, `measure`, `commit --step preflight-hand-fixes` | one commit per topic | replacement must exist on the source **and** the target |
| 11 | Schema tooling | `schema check` (and `schema plan` with TYPO3 Console) | tooling decision | whether to add TYPO3 Console (your decision) |
| 12 | Crew | write `QRH.md`, `MEL.md`, `BRIEFING.md`, `snapshot take/restore` | the flight plan | rollback criteria, window, people |
| 13 | Gate | `gate preflight show`, `gate preflight go|nogo --note` | decision | the evidence |
| 14 | Reports | `report --phase preflight`, notes, `report --phase preflight` | `reports/preflight-*` | the PM summary before you send it |

Rounds: steps 9 and 10 repeat until the rule plans are empty and the suite
reports no deprecations on the current version, or what remains is on the
MEL.

---

## 7. Phase 2: Flight

| # | Step | Commands | Produces | Look at by hand |
|---|---|---|---|---|
| 0 | Before the roll | `snapshot take --name before-flight` | local backup | production backup and freeze (yours) |
| 1 | Branch | `git switch -c <prefix>/<target>` | | |
| 2 | Platform | `versions` | PHP check | PHP must already be right |
| 3 | Packages | `bump apply`, `composer update -W`, `deps list --from-lock <preflight branch>`, `deps docs`, `commit --step bump` | the bump commit with all commands | "Problem 1" when composer refuses |
| 3a | Go-live blockers | in the same transaction, for each blocker: `composer config minimum-stability dev`, `composer config prefer-stable true`, `composer require --no-update '<package>:<branch>'` (all through `upgrade-pilot composer`) | the development versions, recorded in the bump commit | that every one has a blocker |
| 3b | Measure | `measure --label "after bump"` | the real worklist | |
| 3c | Patches and modifications | `patches --label flight`, `deps touchpoints --verify --label flight` | rebased or removed patches, adapted code | contained patches are removed, failing ones rebased |
| 4 | Rector | `rules config --tool rector --level <target>`, [loop](#9-the-rule-by-rule-loop), optional PHP set: `rules config --tool rector --set php` and a `*-rector-php` campaign | one commit per rule | generated wizards, data consequences |
| 5 | Fractor | same with `--tool fractor` | one commit per rule | re-indented TypoScript |
| 6 | Scan | `scan --label flight`, `tca --label flight` | new findings of the target rules | |
| 7 | Failures | fix, `measure --label "<fix>"`, `commit --step <slug>` | one commit per fix | broken by the upgrade or broken already |
| 8 | Schema | `schema check`, `schema plan`, `schema apply` | converged schema, statement counts | non-convergence, destructive changes (never now) |
| 9 | Wizards | `cache:flush`, `upgrade:list --all`, `upgrade:run`, query before/after | verified data migrations | wizards of dependencies, rehearsal rows |
| 10 | Caches | `cache:flush`, frontend request | | the site itself |
| 11 | Gate | `measure --label cleared`, `gate flight show`, decision | | acceptance tasks for your team |
| 12 | Reports | `report --phase flight` + notes | `reports/flight-*` | |

Rounds: step 7 repeats until every suite is green without skipped or weakened
tests. `schema apply` repeats plan and apply until the dry run is empty
(on a real 12.4 to 13.4 project that took two passes).

---

## 8. Phase 3: Post-flight

| # | Step | Commands | Produces | Look at by hand |
|---|---|---|---|---|
| 1 | Landing | frontend requests, scheduler check | | frontend, backend, logs (your team) |
| 2 | Sweep | `scan --label postflight`, `tca --label postflight`, local deprecation-log crawl | the next upgrade's work list | instance configuration (settings.php) |
| 2b | Deployment and CI | `delivery --label postflight`: commands checked against the target instance | `delivery.json` | scripts and CI images to change |
| 3 | Destructive schema | `schema plan --destructive` | drops and renames for the MEL | the date after the rollback window |
| 4 | Ferry equipment | grep for shims and TODOs, `composer remove` of what only the upgrade needed | commits | whether tooling stays for CI |
| 4b | Go-live blockers | `blockers check`, and once a release exists: require it, measure, verify touchpoints, `blockers resolve`. Otherwise `handoff` with what it waits for | resolved blockers, or a result marked not releasable | the release date the team waits for |
| 5 | Record | `versions --target <next>`, `DEBRIEF.md` | next flight date, debrief | |
| 6 | Issues | `issues list`, then `issues apply` once numbers are filled in | final history | before anything is pushed |
| 7 | Gate | `gate postflight show`, decision | phase `landed`, guard released | |
| 8 | Reports | `report --phase postflight`, `report --phase final`, notes | `reports/postflight-*`, `reports/final-*`, `UPGRADE-REPORT.md` | the customer summary |

---

## 9. The rule-by-rule loop

Every Rector and Fractor campaign, in every phase:

```bash
upgrade-pilot rules plan  --tool rector [--campaign <name>] [--config <file>]
# repeat until the plan reports 0 open rules:
upgrade-pilot rules apply                      # exactly one rule
git diff                                       # review, complete generated code, restore layout
upgrade-pilot measure --label "rector: <Rule>"
upgrade-pilot rules commit --tag TASK --subject "<what changed>" --body-file body.txt
upgrade-pilot rules plan                       # rules interact: plan again
```

- `apply` uses the tool's `--only`, or a generated single-rule configuration
  for older Rector.
- New files and `TODO` markers are printed: complete them or skip the rule.
- `rules skip --reason "..."` reverts and records a rule you decline.
- Sets: the TYPO3 level set first. The PHP level set (`--php-set`) runs as its
  own campaign with `rector-php.php`, still one rule per commit.
- One campaign is one step, so in per-step and placeholder mode one issue per
  campaign. `--step` overrides it.

---

## 10. Reports and summaries

At every gate and at the end:

```bash
upgrade-pilot report --phase preflight      # or flight, postflight, final, all
```

| File | Audience | Language | Content |
|---|---|---|---|
| `reports/<phase>-dev.en.md` | developers | English | gate, checklist with notes and evidence, measurements, scans, campaigns, commits, dependencies, schema, issues, context |
| `reports/<phase>-pm.en.md` | project managers, customers | English | status, what was done, results in plain numbers, accepted risks, what your team has to do, next steps |
| `reports/<phase>-pm.de.md` | project managers, customers | German | the same in German, checklist titles in German |
| `reports/final-*` | all | as above | the whole flight, timeline, next upgrade date |
| `reports/assessment-*` | developers, project managers | as above | the pre-analysis: release status, decisions, go-live blockers, security, size of the work |
| `UPGRADE-REPORT.md` | developers | English | the complete technical record with the debrief |

Facts come from the flight log. The prose summaries are written by Claude into
`.upgrade-pilot/notes/<phase>-<audience>.<lang>.md` and embedded on the next
render: a short technical one for developers, five to ten plain sentences for
project managers, in real German for the German report. Read the PM summaries
before you forward them.

---

## 11. Manual investigations and corrections

| Situation | What to do |
|---|---|
| `.envrc` not allowed or denied | review it, `direnv allow` yourself, run `init` again |
| Wrong test command detected | edit `config.json -> tests`, run the suite, set `"confirmed": true` |
| Composer refuses the bump ("Problem 1") | read it fully: own path package pinned, dev tooling pinning a shared dependency, third-party without a release. Never `--ignore-platform-reqs`. Third-party gaps are team decisions (update, patch, fork, replace) |
| Composer refuses on an unmaintained source version (advisories) | do not bypass the block. Add what you need together with the bump instead |
| A rule changes more than it should | fix the extra hunks in the same commit, or `rules skip --reason` |
| A rule generates code with a `TODO` | complete it from the real data (mappings from registrations and fixtures), or skip and put it on the QRH |
| A rule changes how records are read (CType, FlexForm) | upgrade wizard for production data plus the same migration for fixtures, in the same commit |
| Tools reformat code | restore the original layout in the same commit |
| A hand fix uses API removed in the target | check replacements against the target's changelog too (`changelog match`) |
| Tests red after the bump | one at a time. Removed API: fix now. Deprecation: fix or MEL. Compare with the baseline: broken by the upgrade or broken already |
| A dependency has "nothing documented" | read the maintainer's project page, releases or issues by hand |
| A package has no release for the target | decide: development version as go-live blocker, replace, drop, fork, or hold. Never ship a development version silently |
| A package is `claimed` | read the claim in the assessment report: a supported branch, a planned version, or a version that is not public (early access, paid) |
| A patch `fails` on the target | rebase it on the target source, or drop it if the fix landed upstream differently |
| A patch is `contained` or `retired` | remove it in the flight, the change is upstream |
| A deployment script calls `typo3cms` | replace it with `typo3` in the same change that raises TYPO3 Console |
| `blockers resolve` refuses | read `blockers check`: every check names what is missing |
| Schema does not converge | stop. Charset/collation drift, conflicting definitions. It would fail on every environment the same way |
| A wizard is missing from the list | `cache:flush`, the container was built before the class existed |
| The local database has no rows for a wizard | rehearse with a row inserted the way the old version stored it, on the local database only |
| Dead code with findings | not deleted during the flight: MEL, human decision |
| Placeholders still in commits | fill `ISSUES.md`, `issues apply`, before pushing |
| A commit message needs a correction | before pushing: amend the last commit yourself, or tell Claude. Pushed history is never rewritten |

---

## 12. What ends up where

```text
.upgrade-pilot/                    excluded from git
├── config.json                    runtime, tests, extensions, branches, commit policy, facts
├── flightlog.json                 checklist, gates, measurements, scans, campaigns, commits, issues, context, assessments, blockers
├── FLIGHT-LOG.md                  rendered view of the flight log
├── QRH.md  MEL.md  BRIEFING.md    written during the pre-flight
├── DEBRIEF.md                     written after landing
├── ISSUES.md                      per-step issues or placeholders with their commits
├── context/                       digests of pre-collected information
├── assessments/                   every pre-analysis (JSON), compared with the previous one
├── assess/                        composer audit results, the probed target lock file
├── deps/                          one report per dependency that moves
├── touchpoints.json               where own code modifies third-party packages, verified
├── patches.json                   composer patches and their state on the target
├── delivery.json                  deployment and CI findings
├── changelog-<from>-<to>.json     core changelog entries matched against your code
├── contacts.json                  core contact points and their test coverage
├── notes/                         summaries written for the reports
├── reports/                       <phase>-dev.en.md, <phase>-pm.en.md, <phase>-pm.de.md, final-*
├── UPGRADE-REPORT.md              final technical record
├── logs/                          raw output of every tool run
├── cache/                         core changelog and dependency sources
├── bin/                           PHP helpers copied into the project
└── tmp/                           commit messages, single-rule configurations
```

In git, on the pilot branches: your code changes, tests, `rector.php`,
`fractor.php` (and `rector-php.php`), composer files, all as reviewable
commits.

---

## 13. Resuming, re-running, starting over

- Resume any time: `/fly-the-upgrade:upgrade` or `upgrade-pilot status -v`.
- Any measurement, scan or report can be re-run, every run is recorded with
  its label, branch and commit.
- Start over: `upgrade-pilot init --force ...` replaces the flight. The old
  state (flight log, reports, notes, logs, dependency reports) moves to
  `.upgrade-pilot/archive/<time>-<title>/`, the download cache stays. Your
  branches stay, delete them yourself if wanted.
- Throw a rehearsal away: switch back to the base branch, delete the pilot
  branches, `composer install`, restore the database snapshot, remove
  `.upgrade-pilot/`.
