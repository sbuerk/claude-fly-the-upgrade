# Fly the Upgrade: a TYPO3 upgrade pilot for Claude Code

A [Claude Code](https://code.claude.com/) plugin that flies a TYPO3 major
upgrade the way pilots fly an aircraft: three phases, a gate at the end of each,
a checklist that is answered out loud, and instruments instead of guesses.

It is the companion of the talk *"Fly the Upgrade: how pilots would fly a TYPO3
upgrade"*. The plugin does not replace the people who own the project. It does
the measurable work, records every step, and stops where a human has to decide.

| Phase | What the pilot does | Ends with |
|---|---|---|
| **0 Pre-analysis** | Before anything changes: **released version for the target of every third-party package** (Packagist, other composer repositories, TER, development branches and their documentation), probe, **security advisories** of the installed and the target graph, **composer patches** (cweagans and vaimo) against the target, **deployment and CI scripts**, modifications of third-party packages and their tests, the size of the work counted, a report for developers and project managers | Decisions: release, development version as **go-live blocker**, or hold |
| **1 Pre-flight** | Inventory, version facts, bump probe, changelog triage of the core **and of every third-party package that moves**, **tests for untested core contact points**, baseline, deprecations cleared on the *current* version with Rector and Fractor **one rule per commit**, Extension Scanner, TCA migration check, **schema tooling decision (TYPO3 Console)**, QRH / MEL / briefing, backup rehearsal | Go / No-Go |
| **2 Flight** | Branch, platform check, core and tooling raised in one composer transaction, Rector and Fractor for the *target* one rule per commit, scan again, red tests worked one at a time, **schema previewed and applied until it converges**, upgrade wizards verified on data, caches | Cleared to hand over |
| **3 Post-flight** | Sweep again with the new core's rules, local deprecation-log crawl, destructive schema changes listed for after the rollback window, ferry equipment removed, constraints re-pinned, upgrade report and debrief | Debriefed |

> **The complete process, step by step, with every command, what each step
> produces and where a person has to look: [docs/PROCESS.md](docs/PROCESS.md).**
>
> **Only third-party packages move, not the core? Update or just check selected
> packages (one, a list, or `vendor/prefix-*`), including every place where your
> sitepackage or local extensions modify them:
> [docs/SCENARIO-PACKAGES.md](docs/SCENARIO-PACKAGES.md).**

Every checklist answer, measurement, scan and refactoring rule lands in a flight
log inside the project. Nothing is estimated.

---

## Contents

- [The full process guide](docs/PROCESS.md)
- [Requirements](#requirements)
- [Installation](#installation)
- [Updating the plugin](#updating-the-plugin)
- [Prepare the project](#prepare-the-project)
- [Upgrade a project, step by step](#upgrade-a-project-step-by-step)
- [What you get: the flight log](#what-you-get-the-flight-log)
- [Third-party changelogs and upgrade notes](#third-party-changelogs-and-upgrade-notes)
- [Pre-analysis before anything changes](#pre-analysis-before-anything-changes)
- [Your modifications of third-party packages](#your-modifications-of-third-party-packages)
- [Selected packages only: update or check](#selected-packages-only-update-or-check)
- [Database schema and TYPO3 Console](#database-schema-and-typo3-console)
- [Using parts of the plugin on their own](#using-parts-of-the-plugin-on-their-own)
- [Configuration](#configuration)
- [The upgrade-pilot CLI](#the-upgrade-pilot-cli)
- [Safety](#safety)
- [Limits](#limits)
- [Verified on](#verified-on)
- [What is in this repository](#what-is-in-this-repository)
- [Contributing](#contributing)
- [License](#license)

---

## Requirements

On your machine:

- Claude Code with plugin support
- Python 3.9 or newer (standard library only, nothing to install)
- git

In the project you upgrade:

- a **composer-mode** TYPO3 project or TYPO3 extension (classic mode is not supported)
- git, with the upgrade starting from a clean working tree
- PHP and composer where the project runs them: [ddev](https://ddev.com/), [direnv](https://direnv.net/) (an allowed `.envrc` in the project or one folder above), local PHP, or any container. All are detected
  automatically, a local PHP works too, any other container can be described
  (see [Configuration](#configuration))
- a test suite that can be started with one command per suite, ideally the
  TYPO3 Core style `Build/Scripts/runTests.sh` (detected automatically)

## Installation

The repository is its own plugin marketplace. In a terminal:

```bash
claude plugin marketplace add sbuerk/claude-fly-the-upgrade
claude plugin install fly-the-upgrade@fly-the-upgrade
```

Or inside a Claude Code session:

```
/plugin marketplace add sbuerk/claude-fly-the-upgrade
/plugin install fly-the-upgrade@fly-the-upgrade
```

Restart Claude Code (or start a new session) afterwards. Check that it loaded:
typing `/fly-the-upgrade:` should offer the skills listed below.

**Install scope.** By default the plugin is installed for your user. To share it
with everybody who works on one project, install it with the project scope from
inside that project, which records it in the project's `.claude/settings.json`:

```bash
claude plugin install fly-the-upgrade@fly-the-upgrade --scope project
```

**Update and remove:** see [Updating the plugin](#updating-the-plugin).

**Try it without installing** (for example from a local clone):

```bash
git clone https://github.com/sbuerk/claude-fly-the-upgrade.git
claude --plugin-dir ./claude-fly-the-upgrade
```

## Updating the plugin

Updates arrive per release: a new version is only offered once the version in
`.claude-plugin/plugin.json` changes. Refresh the marketplace, then update the
plugin:

```bash
claude plugin marketplace update fly-the-upgrade
claude plugin update fly-the-upgrade@fly-the-upgrade
```

Start a new Claude Code session afterwards, so the updated skills are loaded.
Remove it with `claude plugin uninstall fly-the-upgrade@fly-the-upgrade`.

A flight lives in the project's `.upgrade-pilot/`, not in the plugin, so an
update never touches a running flight. What changes for it is listed per
version below and in [CHANGELOG.md](CHANGELOG.md).

### Upgrade notes

#### 0.4.x to 0.5.0

- **New checklist lines** appear as open in running flights: `pf.assessment`,
  `pf.release-status`, `pf.security`, `pf.patches`, `pf.delivery`,
  `fl.patches`, `pst.delivery`, `pst.blockers`. In a flight that is still in
  the pre-flight, run `upgrade-pilot assess` once: it answers most of them
  with evidence. In a flight that is further along, answer them with
  `upgrade-pilot patches`, `upgrade-pilot delivery --label <phase>` and, for
  any development version already in use, `upgrade-pilot blockers add`.
- **Patch touchpoints** are now read through the installed patch plugin
  (`cweagans/composer-patches` or `vaimo/composer-patches`) and verified with
  `git apply --check` against the target source, instead of comparing the
  patched files. A project without one of these plugins has no patch
  touchpoints.
- **Reports** show go-live blockers, and the final status says "not
  releasable" while one is open.

#### 0.3.x to 0.4.0

- **Nothing changes for a running flight unless you use the new parts.** A
  flight opened with 0.3.x has no scope and stays a core upgrade.
- **New checklist lines** in the core scope (`fl.third-party-modifications`,
  `pst.touchpoints`) appear as open in running flights. Answer them with
  `upgrade-pilot deps touchpoints --verify --label <phase>` before their gate.
  `pf.your-changes` now also points to `deps touchpoints`.
- **`init --force` archives** the previous flight to
  `.upgrade-pilot/archive/<time>-<title>/` instead of leaving its reports, logs
  and notes in place. Move anything you still need out of the archive, or
  delete it, it is not read again.
- **Development versions** (`2.x-dev`, `dev-main`) are compared through their
  branch alias. A `deps list` or `deps docs` re-run in a running flight can
  therefore classify such a move differently than before (a minor or major
  step instead of a downgrade or a plain change).
- **Selected packages without a core upgrade**: open a new flight with
  `init --scope packages`, see [docs/SCENARIO-PACKAGES.md](docs/SCENARIO-PACKAGES.md).

#### 0.2.x to 0.3.0

- **New questions at initialization** (runtime, commit style, issue handling,
  context, PHP set). They only apply to new flights. A flight opened with 0.2.x
  keeps working: without a commit policy it commits in TYPO3 Core style without
  issue references, and pushing stays allowed as before.
- **Adopting the new commit policy in a running flight**: add a `commit` block
  to `.upgrade-pilot/config.json` rather than re-running `init --force`, which
  would replace the flight log:

  ```json
  "commit": {
      "style": "youtrack",
      "template": null,
      "tracker": "youtrack",
      "project_key": "PRJ",
      "issue_mode": "placeholder",
      "issue": "PRJ-100",
      "subject_max": 52,
      "body_wrap": 72
  },
  "allow_push": false
  ```

- **`rules commit` changed**: it renders the message itself and takes
  `--subject`, `--body` or `--body-file` and `--step`. `--message-file` is
  gone. A rule that is applied but not yet committed is committed with the new
  options.
- **Composer changes need recorded commands**: `upgrade-pilot commit` refuses
  changed `composer.json` or `composer.lock` without a command recorded through
  `upgrade-pilot composer ...` or `upgrade-pilot run -- ...`. If composer files
  were changed by hand before the update, commit them with plain git once, or
  redo the change through the recorded commands.
- **`bump apply`** now changes constraints through `composer require --no-update`
  and records those commands for the bump commit.
- **Reports**: `report` writes per-phase reports (`--phase preflight|flight|postflight|final|all`),
  with a PM/customer variant in English and German. Without `--phase` it writes
  the final reports and, as before, `UPGRADE-REPORT.md`.
- **New checklist lines** (`pf.context`, `pf.dependency-docs`,
  `fl.dependency-migrations`) appear as open in running flights and have to be
  answered before their gate.

#### 0.1.x to 0.2.0

- **TYPO3 Console support**: `schema check|plan|apply` and new checklist lines
  (`pf.schema-tooling`, `pst.schema-destructive`), which appear as open in
  running flights.
- **`bump`** also raises TYPO3 Console and the testing framework when needed,
  so run `upgrade-pilot versions` again before the bump to refresh the facts.

## Prepare the project

The pilot tells you what is missing, but a flight goes smoother when these are
in place before you start:

1. **Commit or stash everything.** The pilot refuses to apply a refactoring rule
   on a dirty working tree, because the diff could not be attributed to one rule.
2. **Make the test suites runnable.** `Build/Scripts/runTests.sh -s unit` and
   `-s functional` are detected. Otherwise the pilot points at PHPUnit
   configuration files and asks you to confirm the command. Keep
   `failOnDeprecation="true"` in the PHPUnit configuration: deprecations are the
   first worklist of the upgrade.
3. **Install the tooling as dev dependencies**, if the project does not have it
   yet. Rector and Fractor are needed for the refactoring campaigns, the scanner
   CLI for the Extension Scanner runs:

   ```bash
   composer require --dev ssch/typo3-rector a9f/typo3-fractor typo3/testing-framework
   # the Extension Scanner CLI is not on Packagist, add its VCS repository first
   composer config repositories.extension-scanner-cli vcs https://github.com/netresearch/t3x-nr-extension-scanner-cli
   composer require --dev netresearch/extension-scanner-cli:@dev
   ```

   With ddev, prefix composer with `ddev`. The pilot creates `rector.php` and
   `fractor.php` for your own extensions if they do not exist.

   Optional but recommended: [TYPO3 Console](https://github.com/TYPO3-Console/TYPO3-Console)
   (`helhum/typo3-console`) as a regular dependency, for a schema update with a
   dry run. The pre-flight asks you about it and suggests a version, see
   [Database schema and TYPO3 Console](#database-schema-and-typo3-console).
4. **Have a working local instance** (installed, database set up). The TCA
   migration check, the schema step, the upgrade wizards and the frontend checks
   run against it.

## Upgrade a project, step by step

### 1. Start the flight

Open Claude Code in the project root and run:

```
/fly-the-upgrade:upgrade 13.4
```

(or just say *"upgrade this project to TYPO3 13.4"*). Claude first looks at the
project (`upgrade-pilot init --detect`: ddev, direnv, local PHP, how your commit
messages look) and then asks you:

- **Runtime**: ddev, direnv or local PHP. An `.envrc` that is not allowed is
  reported, never allowed on your behalf.
- **Commit style**: TYPO3 Core style (`[TAG] Subject`, issue references as
  `Related:` lines, no Resolves/Releases), YouTrack style
  (`[TAG] PRJ-123: Subject` with `Related:` lines), or your own template.
- **Issue references**: none, one reference for everything, a parent issue with
  one issue per step, or `{ISSUE-01}` placeholders collected in `ISSUES.md`
  that are replaced in the commits once the real issues exist.
- **Gates**: **human** (default, Claude stops at every gate and asks you for
  Go or No-Go) or **auto** (Claude decides by the written criteria, human-only
  lines are still handed over to you).
- **Extras**: the PHP level set as an extra Rector campaign, and pre-collected
  context: issues with a pre-analysis, customer requirements, notes. Claude reads
  them first (issues through whatever tracker access the session has) and keeps a
  digest in the flight.

It then runs `upgrade-pilot init` with your answers, which also detects the
installed TYPO3 version, your own extensions (path repositories, classic
extensions, or the repository itself when it is an extension) and the test
commands. **Check what it prints.** A wrong test command poisons every
measurement.

Every commit goes to local pilot branches, in your style, in small logical
units. Composer files change only through composer (or `jq`) commands, and the
commit lists them in a `Used command(s):` block. **Nothing is pushed**: the
plugin blocks pushes while the flight is open.

### 1b. Pre-analysis (nothing changes yet)

Before any branch, Claude runs `upgrade-pilot assess` and writes the
assessment reports (see [below](#pre-analysis-before-anything-changes)). For
every third-party package without a released version for the target you
decide: use a development version meanwhile as a **go-live blocker**, replace
or drop it, or **hold** the upgrade. A held upgrade is re-checked later with
another `assess`.

### 2. Pre-flight (on a branch, still on the current version)

Claude creates `upgrade/preflight-<current>` from your branch and works through
the pre-flight checklist:

- version facts, PHP overlap and support dates (`get.typo3.org`, Packagist)
- a **bump probe**: constraints raised, `composer update -W --dry-run`, files
  restored. Every "Problem N" is a blocker to solve before departure
- the core changelog of the target, matched against your code
- the changelogs, upgrade guides, release notes and new upgrade wizards of every
  third-party package the bump moves (see below)
- **instruments**: core contact points of your extensions (plugins, controllers,
  services using core API, hooks, listeners, middlewares, commands, TCA,
  TypoScript) and which of them any test executes. Claude writes the missing
  tests, committed one area at a time
- a **baseline** measurement of all suites
- Rector and Fractor with the *current* version's level set, **one rule per
  commit**: apply, review, measure, commit, plan again
- remaining deprecations fixed by hand, only with API the current version has
- Extension Scanner and TCA migration check before and after
- the schema tooling: TYPO3 Console detected, or offered to you (your decision)
- `QRH.md` (expected failures and answers), `MEL.md` (accepted open items with
  reason and date), `BRIEFING.md`, a local backup and restore rehearsal

Everything on this branch still runs on the current version and could be
deployed before the upgrade.

**Gate: Go / No-Go.** In human mode you get the evidence and decide.

### 3. Flight (on a second branch, on the target version)

Claude creates `upgrade/<target>` from the pre-flight branch and follows the
fixed sequence: platform check, then all `typo3/cms-*` constraints, your own
extensions' constraints, the testing framework and, if needed, TYPO3 Console
raised together and `composer update -W`, one commit. It measures straight after the bump (that
result is the real worklist), then runs the Rector and Fractor campaigns against
the *target* level set, scans again, and works the red tests one at a time.
Generated code, such as upgrade wizards that Rector scaffolds with a `TODO`, is
completed and verified, never committed blind. Schema, wizards and caches run
on the local instance. With TYPO3 Console the schema statements are previewed
first and applied until the dry run is empty, and the wizards are checked
against real rows.

**Gate: Cleared to hand over.** All suites green, without skipped or weakened
tests. Smoke tests by people, staging and editor testing are listed as your
tasks.

### 4. Post-flight

Scanner and TCA check again with the new core's rules, a local deprecation-log
crawl, the destructive schema changes (drops, renames) listed on the MEL for
after the rollback window, upgrade-only leftovers removed, constraints re-pinned, next upgrade dated
from the support calendar, then `UPGRADE-REPORT.md` with the debrief.

**Gate: Debriefed.** The flight is closed.

### 5. Land it yourself

The pilot never merges, rebases or pushes, and its hook blocks attempts to
while a flight is open. With placeholder issues, fill in the real numbers in
`ISSUES.md` and let the pilot run `upgrade-pilot issues apply` before anything
is pushed. Then review the two branches, push them, open merge or pull
requests and deploy the way your team does. The pre-flight branch can go out
first, on the current version.

At every gate and at the end you get reports: a developer report in English
and a project-manager/customer report in English and German
(`.upgrade-pilot/reports/`). See [Reports](docs/PROCESS.md#9-reports-and-summaries).

### Resuming, and asking where you are

A flight survives sessions and branch switches. Any time:

```
/fly-the-upgrade:upgrade
```

or ask *"where are we with the upgrade?"*. Claude reads the flight log and
continues with the first open item of the current phase.

## What you get: the flight log

State lives in `.upgrade-pilot/` at the project root. `init` adds the directory
to `.git/info/exclude`, so it never lands in a commit and survives branch
switches.

| File | What |
|---|---|
| `FLIGHT-LOG.md` | The checklist with every answer, gates, measurement table, scans, TCA checks, rule campaigns, journal. Re-rendered after every change |
| `reports/` | Per gate and final: `<phase>-dev.en.md`, `<phase>-pm.en.md`, `<phase>-pm.de.md` |
| `UPGRADE-REPORT.md` | Key stages, every measurement, campaigns (generated code, skipped rules), commits of both branches, gates, human handoffs, accepted risks, debrief |
| `ISSUES.md` | Per-step issues or placeholders with their commits |
| `context/` | Digests of pre-collected information |
| `QRH.md`, `MEL.md`, `BRIEFING.md`, `DEBRIEF.md` | Written during the flight, hand them to your team |
| `config.json` | How things run: runtime wrapper, test commands, own extensions, branches, gate mode, fetched version facts |
| `flightlog.json` | The machine-readable log the CLI keeps |
| `contacts.json`, `changelog-*.json` | Full reports of the contact-point inventory and the changelog match |
| `logs/` | Raw output of every tool run, cited as evidence |

Checklist answers use five states: done, **no** (answered no, with a reason: an
accepted risk), not applicable, **handoff** (a person has to do or confirm it),
open.

## Third-party changelogs and upgrade notes

The core is not the only thing that moves. A major bump also moves
extensions and libraries, and many of them document their changes as
carefully as the core does. `upgrade-pilot deps` finds and reads those notes,
by convention only, for any package.

**Which packages.** `deps list` takes them from the bump probe in the
pre-flight, or from the old and the new `composer.lock` after the bump
(`--from-lock <pre-flight branch>`), leaving out core packages and your own
extensions. `deps docs` reads by default:

- every TYPO3 extension that moves
- direct requirements (root or own-extension `composer.json`) that jump a
  major or are new
- packages your code actually uses (their PSR-4 namespaces appear in your
  extensions)

Anything else on request with `--package <name>` or `--all`.

**Where it reads.** From the package's source repository at the **target
release** and at the installed release, through the source URL composer knows.
Private repositories therefore work with the project's own credentials.
Notes that exist only on a branch do not count, they do not describe what you
install. Without a git source, the installed copy in `vendor/` is used.

**What it looks for, in any package:**

| Convention | Example |
|---|---|
| TYPO3-style changelog | `Documentation/Changelog/<version>/Breaking-*.rst` (also Deprecation, Feature, Important, Bugfix) |
| Note files | `CHANGELOG`, `CHANGES`, `UPGRADE`, `UPGRADING`, `MIGRATION`, `NEWS`, `RELEASE-NOTES` as `.md`, `.rst` or `.txt` |
| Upgrade guides | `Documentation/**/UpgradeFrom5To6.rst`, `docs/**/migration*.md` |
| Hosting release notes | GitHub releases (through `gh` when available), GitLab-style `/api/v4` releases |
| Breaking commits | subjects with `[!!!]`, `BREAKING` or `type!:` between the two releases |
| Upgrade wizards | `#[UpgradeWizard('…')]` classes that are new in the target release |

What is new is decided by comparing the two releases: changelog files that
only exist in the target, note sections that are new or changed. When the
installed release cannot be read, version headings decide instead.

Per package you get `.upgrade-pilot/deps/<package>-<from>-<to>.md` with the
full text of every relevant entry, hits of their code literals in your
extensions, and the new wizards. The pre-flight turns breaking entries and
wizards into QRH rows, the flight re-reads the notes for the versions really
installed and expects the wizards in step 8.

"Nothing documented found" is reported as such: the maintainer's project
page then becomes a task for a person.

For TYPO3 extensions, the **rendered manual on docs.typo3.org** is read as
well: pages of the target's manual that are new against the installed
version's manual, as Markdown where the host publishes it (found through
`toc.json` or `objects.inv.json`, as its `llms.txt` asks). New upgrade wizards
that their package keeps out of the service container are marked **opt-in**,
with their class documentation: the core never offers them, the project
decides.

## Pre-analysis before anything changes

`upgrade-pilot assess` (skill `fly-the-upgrade:assess`) runs right after
initialization, read-only, and writes `reports/assessment-dev.en.md`,
`reports/assessment-pm.en.md` and `reports/assessment-pm.de.md`:

- **Release status** of every third-party TYPO3 extension and direct
  requirement for the target core: `released`, `released-ter` (only the TER
  has one), `dev-only` (only a development line requires the target),
  `claimed` (only the documentation of a development line mentions it),
  `none`. Sources: Packagist, composer itself for other repositories, the TER
  REST API by extension key, the development branches with their
  `ext_emconf.php`, README and manual. Abandoned packages and release dates
  are reported too.
- **Security**: `composer audit` of the installed lock file and of the target
  lock file the probe writes without installing, plus abandoned packages.
- **Composer patches** of `cweagans/composer-patches` (1.x and 2.x) and
  `vaimo/composer-patches`, read in each plugin's own syntax and checked with
  `git apply --check` against the target source: applies, fails, already
  contained upstream, retired by its version constraint, or lost.
- **Deployment and CI**: PHP versions in CI images and recipes against the
  target core, `typo3cms` calls (checked against the installed TYPO3
  Console), `typo3` commands the instance does not know, composer calls that
  switch platform checks off.
- **Modifications of third-party packages** and whether a test mentions each
  of them, the dependencies' and the core's changes that touch your code,
  upgrade wizards. Counted, never estimated.

**Released versions only, unless you decide otherwise.** A package that only
has a development version for the target is a decision: use it meanwhile as a
**go-live blocker** (`upgrade-pilot blockers add`), or hold the upgrade. The
flight can land with an open blocker, but every report then says "not
releasable", and `blockers resolve` only succeeds once a release is installed
and committed, every test suite was green afterwards and the package's
touchpoints were verified on it.

**Re-check.** Every assessment is kept and compared with the previous one:
what changed per package, new or resolved advisories, and blockers that can be
resolved because a release appeared. The whole procedure is in
[docs/PROCESS.md](docs/PROCESS.md#4-pre-analysis-the-assessment).

## Your modifications of third-party packages

Sitepackages and local extensions replace classes of third-party extensions,
listen to their events, copy their templates and override their labels. None
of that appears in the package's changelog, and all of it can break when the
package moves. `upgrade-pilot deps touchpoints --verify` finds these places
from each package's own declarations (namespaces, extension key, tables,
plugins, templates, labels) in own extensions, sitepackages, `config/` and
composer patches, and checks each against the target version: XCLASS and
subclass signatures, final classes, removed classes and events, changed
original templates, removed label keys, missing ViewHelpers, patches that no
longer apply. Every entry ends as `ok`, `manual` or `attention`. With
`--coverage` it also lists the test files that mention each place, so
untested modifications become visible.

It runs in the pre-flight (entries become QRH rows), during the flight until
nothing needs attention, and again on the final state. The kinds and checks are
listed in [docs/SCENARIO-PACKAGES.md](docs/SCENARIO-PACKAGES.md#5-what-your-project-built-on-top-touchpoints).

## Selected packages only: update or check

A flight does not have to move the core. With `--scope packages` it moves
selected packages on an unchanged core, in the same three phases, or with
`--check-only` it only assesses them and changes nothing:

```bash
upgrade-pilot init --scope packages --package 'acme/shop-*' --to dev-main \
  --dev-stability minimum-stability --check-only
```

Globs are matched against `composer.lock`. Development targets (`dev-main`,
`2.x-dev`) are compared through their branch alias, a branch alias that
composer ignores is reported, and `bump probe --alias` bridges it with a
recorded inline alias when the team decides so. The whole scenario:
[docs/SCENARIO-PACKAGES.md](docs/SCENARIO-PACKAGES.md).

## Database schema and TYPO3 Console

The core's only command-line schema step is `extension:setup`: it applies the
safe changes (create and alter, never drop or rename) and has **no dry run**.
`database:updateschema` is not a core command, it comes from
[TYPO3 Console](https://github.com/TYPO3-Console/TYPO3-Console): through the
core's `typo3` binary since Console 8.0, through its own `typo3cms` binary
before.

`upgrade-pilot schema` detects which one the project has. It reads
`helhum/typo3-console` from `composer.lock` and confirms in the runtime which
binary really offers `database:updateschema`.

| | With TYPO3 Console | Core only |
|---|---|---|
| `schema check` | Reports the Console version and binary | Explains the gap and suggests a Console constraint that supports your current **and** your target version (from Packagist, filtered by your PHP version) |
| `schema plan` | Dry run: the exact SQL statements (`--destructive` for drops and renames) | Refuses, points to *Analyze Database Structure* in the backend |
| `schema apply` | Safe types only, plan and apply repeated until the dry run is empty (at most 3 passes), fails when it does not converge | `extension:setup`, run twice, result not verifiable |

Why passes: a major step does not always converge in one run. On the workshop
project 12.4 → 13.4 needed two, 181 and then 266 statements, with Console and
with `extension:setup` alike. A deployment that runs the update once leaves the
database half migrated without anybody noticing, a dry run after the update
shows it.

Destructive types are refused unless `--allow-destructive` is passed, which the
skills only do on a recorded human decision after the rollback window.

Adding TYPO3 Console is a production dependency and therefore **your decision**:
the pre-flight asks, suggests the constraint, and records a "no" with its reason.
When the bump raises Console across 8.0, the pilot warns that deployment scripts
calling `typo3cms` must switch to `typo3`.

## Using parts of the plugin on their own

The skills can also be used outside a full upgrade. They need a flight log, so
run `upgrade-pilot init --target <version>` once (or let Claude do it).

| Skill | Use it for |
|---|---|
| `/fly-the-upgrade:upgrade` | Start, resume, status of a whole upgrade |
| `/fly-the-upgrade:assess` | Pre-analysis: can we upgrade yet, what blocks it, how big is it. Also the re-check of a held upgrade |
| `/fly-the-upgrade:preflight` | Only the preparation: what would it take, and clean up on the current version |
| `/fly-the-upgrade:instruments` | Find untested core contact points and write tests for them |
| `/fly-the-upgrade:rule-by-rule` | Apply Rector or Fractor in reviewable steps, one rule per commit |
| `/fly-the-upgrade:flight` | The upgrade sequence after a Go |
| `/fly-the-upgrade:postflight` | Sweep, clean up, report |

The `rule-reviewer` agent reviews the uncommitted diff of one refactoring rule
and is used by `rule-by-rule` for long or unclear diffs.

## Configuration

`upgrade-pilot init` options (Claude passes them for you when you tell it):

| Option | Default | Use |
|---|---|---|
| `--target 13.4` | required | Target version, `major.minor` |
| `--detect` | | Only print what the project offers, as JSON |
| `--runtime ddev\|direnv\|local\|custom` | detected | Where PHP and composer run |
| `--commit-style typo3\|youtrack\|custom` | `typo3` | Commit message style, `--commit-template "[{tag}] {ref}: {subject}"` for custom |
| `--issue-mode none\|single\|per-step\|placeholder` | `none` | How commits reference issues, with `--issue <REF>` (the issue, or the parent), `--tracker`, `--project-key` |
| `--context <REF>` | | Pre-collected information: issue key, URL or file, repeatable |
| `--php-set` | off | Extra Rector campaign with the PHP level set |
| `--allow-push` | off | Do not block pushes during the flight |
| `--gates human\|auto` | `human` | Who decides the gates |
| `--branch-prefix` | `upgrade` | Branches `<prefix>/preflight-<source>` and `<prefix>/<target>` |
| `--ext <path>` | detected | Own extension paths, repeatable |
| `--exec '<wrapper with {cmd}>'` | detected | How to run PHP commands in a custom runtime |
| `--composer '<command>'` | detected | Composer on the host |

Example for docker compose:

```bash
upgrade-pilot init --target 13.4 \
  --exec 'docker compose exec -T php sh -c {cmd}' \
  --composer 'docker compose exec -T php composer'
```

After `init`, `.upgrade-pilot/config.json` can be edited: test commands
(`"where": "host"` runs as is, `"where": "runtime"` is wrapped into the exec
template), `"exclude_from_all": true` for suites that `measure --suite all`
should skip, `"guard": false` to switch the branch guard off for this flight.

## The upgrade-pilot CLI

The skills drive a small CLI that ships with the plugin (on `PATH` while the
plugin is enabled). You can use it directly as well:

| Command | Does |
|---|---|
| `init --target <v>` / `init --detect` | Detect project, runtime, own extensions, tests, commit style. Open the flight |
| `init --scope packages --package <name\|glob> --to <v> [--check-only]` | Open a flight for selected packages on an unchanged core, or only a check of them |
| `context list\|add` | Pre-collected context and its digests |
| `commit --tag --subject --step [--path]` | Commit all changes (or only those below `--path`) in the configured style, with issue reference and recorded commands. `--into-composer-commit` folds composer-only changes into the branch's composer commit |
| `composer <args>` / `run -- <cmd>` | Run composer (in the runtime) or a host command such as `jq`, recorded for the next commit |
| `issues list\|set\|apply` | Issue references: register per-step issues, replace placeholders in the pilot branches |
| `status [-v]` | Phase, gates, open items and how to answer them, last measurements, campaigns |
| `item <id> done\|no\|na\|handoff\|open --note --evidence` | Answer a checklist line. `no` and `na` need a reason |
| `gate <phase> show\|go\|nogo --note` | Gate criteria and blockers, or record the decision |
| `measure --label <stage> [--suite <name>\|all]` | Run the suites, parse PHPUnit, record, print failures |
| `scan --label` | Extension Scanner over own extensions, diffed against the last scan |
| `tca --label` | Headless *Check TCA Migrations* (the core has no CLI for it) |
| `contacts` | Core contact points and which ones the tests execute |
| `versions [--target]` | Support dates, PHP range, compatible testing framework and TYPO3 Console |
| `bump show\|probe\|apply [--alias <name>=<v>] [--audit]` | Raise core constraints and companion packages (testing framework, TYPO3 Console), or the packages of a packages flight. `probe` dry-runs composer and restores the files |
| `deps list [--from-lock <ref>]` / `deps docs [--package] [--all] [--no-rendered]` | Third-party packages that move, and their changelogs, upgrade notes, release notes, rendered manuals, breaking commits and new wizards |
| `deps touchpoints [--package] [--verify] [--coverage] --label` | Where own code, configuration and patches use or modify third-party packages, verified against the target, with the tests that mention them |
| `assess [--quick] [--since <file>] [--render]` | Pre-analysis: release status of third-party packages, probe, composer audit, patches, deployment, sizing, comparison with the previous assessment, reports |
| `blockers list\|add\|check\|resolve\|drop` | Go-live blockers: development versions used meanwhile, resolved only with evidence |
| `patches [--package] --label` | Composer patches (cweagans 1.x/2.x, vaimo) and whether they apply to the target versions |
| `delivery [--verbose] --label` | Deployment and CI files: PHP versions, `typo3cms`, `typo3` commands, platform flags |
| `schema check\|plan\|apply` | Detect schema tooling, dry run, apply safe changes until converged |
| `changelog fetch\|match` | Fetch the target's core changelog, match it against own code |
| `rules config\|plan\|next\|apply\|commit\|skip\|list` | Rector and Fractor campaigns, one rule at a time |
| `snapshot take\|restore\|list` | Local database snapshots (ddev) |
| `report --phase preflight\|flight\|postflight\|final\|all` | Developer (en) and PM/customer (en, de) reports |

`upgrade-pilot <command> --help` shows every option.

## Safety

- Gates default to a human decision.
- Human-only work (production backup, freeze, editor smoke test, staging) is
  recorded as a handoff with instructions, never marked done by the pilot.
- A hook blocks `git merge`, `commit`, `rebase`, `cherry-pick`, `pull` and
  `revert` on the base branch, moving or deleting it, `gh pr merge`, and, unless
  the flight was opened with `--allow-push`, every `git push` and pull or merge
  request creation, while a flight is open. It is a seatbelt, not a security
  boundary.
- History is only rewritten locally and before anything is pushed (issue
  placeholders, folding composer changes), with authors and dates kept.
- An `.envrc` is never allowed by the pilot.
- Tests are never deleted, skipped or weakened to reach green. Fixtures that
  model production data are only changed the way the upgrade wizard changes the
  production data, and the commit says so.
- Commit messages follow your project's rules (its `CLAUDE.md`, `AGENTS.md`,
  contribution guide or your instructions). Without any, the TYPO3 Core format
  is used.
- Destructive schema changes are never applied by the pilot on its own.
- Development versions of third-party packages are only used after your
  decision, and then as go-live blockers until a release is used and verified.
- The pre-analysis changes nothing: the composer probe restores
  `composer.json` and the lock file byte for byte.
- Local database changes (schema, wizards, rehearsal records) only touch the
  local instance. Take a snapshot before and restore it if you want the old
  state back.

## Limits

- The contact-point inventory and the changelog match are static heuristics.
  They rank what to read first. String-built class names, variable method calls
  and instance configuration (`settings.php`) are invisible to them. That is why
  the tests, the TCA check and the deprecation-log crawl are part of the flight.
- Only composer-mode installations.
- Automatic database snapshots only with ddev. With other runtimes the backup
  step is a handoff.
- The deprecation log under real editor traffic, staging and production are
  outside what an agent on your machine can see.
- Documentation claims are found by mentions of the target major in a
  development line's README and manual. Whether a claim means "supported",
  "planned" or "available elsewhere" is read by Claude and decided by you.
- A test that mentions a touchpoint is not proof it executes it. Read the test.
- The deployment check knows common CI and deployment file locations. Scripts
  elsewhere, and server configuration outside the repository, are not read.

## Verified on

Flown end to end on the *Fly the Upgrade* workshop project, TYPO3 12.4.45 to
13.4.35, on dedicated branches. Every number was recorded by the pilot:

| Stage | Functional suite |
|---|---|
| Baseline, after the pre-flight added one instrument test | 10 tests · 14 assertions · 5 deprecations |
| End of pre-flight on 12.4 (14 Rector + 2 Fractor rules, 3 hand fixes) | OK · 10 tests · 14 assertions |
| 13.4, straight after the bump | 10 tests · 12 assertions · 1 error · 5 deprecations |
| 13.4, Rector plugin rule as generated (wizard with a TODO) | 10 tests · 7 assertions · 4 errors · 4 deprecations |
| 13.4, after the flight | OK · 10 tests · 14 assertions |

Extension Scanner 13 → 8 findings on 12.4 and 11 → 9 on 13.4 (the rest is dead
code on the MEL), TCA migration messages 9 → 0 on 12.4 and 1 → 0 on 13.4, the
Rector-generated upgrade wizard completed and verified on a legacy content row.

The third-party notes were verified on real packages: `web-vision/deepltranslate-core`
5.1.10 → 6.0.7 (TYPO3-style changelog, UPGRADE.md, upgrade guide, `[!!!]` commits),
`fgtclb/academic-persons` 1.2.0 → 2.3.4 (split repository of a monorepo, 4 Breaking
entries, a new CType migration wizard), `ssch/typo3-rector` 2.15 → 3.16 (GitHub
release notes only) and `typo3/testing-framework` 8 → 9 (breaking commits only).

The TYPO3 Console support (0.2.0) was verified on the same project on a
throwaway branch: Console `^9.0` suggested as the bridge between 12.4.45 and
13.4, added on 12.4, kept by the bump, 0 pending statements on 12.4, 181 + 266
safe statements applied on 13.4 until converged, 19 destructive renames listed
for post-flight.

The packages scope (0.4.0) was verified on the same project, on TYPO3 13.4
with `fgtclb/academic-*` (two split packages) at 2.3.4, on throwaway branches.
The project had a sitepackage XCLASS and subclass of a repository, a listener
of a plugin event, a copied template with its TypoScript path and a label
override, added for the test:

- **Update to `dev-main` (3.0.x-dev)**: 16 Breaking and 30 Important entries for
  `academic-persons`, 4 Breaking for `academic-base`, the upgrade guide from the
  rendered manual, 15 and 14 breaking commits, two new wizards, one of them
  opt-in. Touchpoints flagged the XCLASS and subclass (a new parameter of the
  overridden method), the listener (its event was removed) and the template
  copy (original changed). The update itself then failed on `cache:flush` with
  exactly the predicted signature error, and the project's own tests stayed
  green, since none of them executed the package. After the fixes all eight
  touchpoints were `ok`, cache flush, schema and the new wizard passed, the
  opt-in wizard was not needed.
- **Check of `2.x-dev`**: the probe failed, because the branch alias of the
  development branch is declared under another name than the version composer
  uses, so composer ignores it. Reported with the reason, then resolved with a
  recorded inline alias. 4 Breaking entries on the minor branch (3 and 1), all
  seven touchpoints `ok`, nothing changed in the project.

The pre-analysis (0.5.0) was verified on a disposable TYPO3 13.4.35 project
assessed for 14.3, with `georgringer/news`, `fgtclb/academic-persons`,
`ichhabrecht/content-defender`, `in2code/femanager` and TYPO3 Console 8, a
sitepackage listening to a news event with a copied news template, three
composer patches for news, a CI workflow and a Deployer recipe:

- release status as the registries and repositories state it: news
  (12.3.2 to 14.1.1) and TYPO3 Console (v8.3.1 to v9.0.1) `released`, both
  outside the current constraint, `academic-persons` and its sibling
  `academic-base` `dev-only` on `dev-main` (alias `3.0.x-dev`, its
  `ext_emconf.php` and installation guide name 14.3), femanager `claimed`
  (its README points to a TYPO3 14 version in an early access program),
  content-defender `none`
- the composer probe did not resolve, so each package was read at the version
  the release check found: 16 Breaking entries and three new wizards (one
  opt-in) for `academic-persons`
- patches with `cweagans/composer-patches` 1.7.3: one applies to news 14.1.1,
  one fails, one is already contained. The same patches with
  `vaimo/composer-patches` 6.0.3, one from a `patches-search` header with a
  version constraint: applies, fails, retired
- deployment and CI: PHP 8.1 outside the 14.3 range, and two `typo3cms` calls
  that fail already today, since TYPO3 Console 8.3.1 has no `typo3cms` binary
- decisions recorded as two go-live blockers and a hold for content-defender,
  `blockers resolve` refused with the failing checks named, a re-check with
  `assess --quick` in eight seconds
- the packages scope on the same project (`fgtclb/academic-*` to `dev-main`
  on 13.4): both packages `dev-only`, since no release newer than 2.3.4
  exists, and a probe that left an uncommitted `composer.json` edit untouched

## What is in this repository

| Path | What |
|---|---|
| `.claude-plugin/` | Plugin manifest and the marketplace entry |
| `skills/` | The eight skills |
| `agents/rule-reviewer.md` | Read-only reviewer for one rule's diff |
| `hooks/` | The base-branch guard |
| `bin/upgrade-pilot`, `lib/upgrade_pilot/` | The CLI |
| `lib/php/tca-migrations.php` | Headless TCA migration check, copied into the project at run time |
| `data/checklist.json`, `data/checklist-packages.json` | The three-phase checklists (core upgrade, selected packages), with who can answer each line |
| `data/templates/` | Starting points for QRH, MEL and briefing |
| `docs/PROCESS.md` | The full process guide |
| `docs/SCENARIO-PACKAGES.md` | Updating or checking selected packages |
| `tests/` | Unit tests for parsers, constraint matching and the guard |
| `AGENTS.md`, `.claude/CLAUDE.md` | Rules for changing this repository, loaded by coding agents |
| `.github/workflows/ci.yml` | Unit tests on Python 3.9 and 3.12, plugin validation, PHP lint |

## Contributing

Issues and pull requests are welcome. Read [AGENTS.md](AGENTS.md) first, it
holds the rules for this repository (for people and for coding agents alike),
and [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow. Changes are listed in
[CHANGELOG.md](CHANGELOG.md).

## License

GPL-2.0-or-later, see [LICENSE](LICENSE).
