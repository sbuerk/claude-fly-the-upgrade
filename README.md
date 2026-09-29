# Fly the Upgrade: a TYPO3 upgrade pilot for Claude Code

A [Claude Code](https://code.claude.com/) plugin that flies a TYPO3 major
upgrade the way pilots fly an aircraft: three phases, a gate at the end of each,
a checklist that is answered out loud, and instruments instead of guesses.

It is the companion of the talk *"Fly the Upgrade: how pilots would fly a TYPO3
upgrade"*. The plugin does not replace the people who own the project. It does
the measurable work, records every step, and stops where a human has to decide.

| Phase | What the pilot does | Ends with |
|---|---|---|
| **1 Pre-flight** | Inventory, version facts, bump probe, changelog triage, **tests for untested core contact points**, baseline, deprecations cleared on the *current* version with Rector and Fractor **one rule per commit**, Extension Scanner, TCA migration check, QRH / MEL / briefing, backup rehearsal | Go / No-Go |
| **2 Flight** | Branch, platform check, core and tooling raised in one composer transaction, Rector and Fractor for the *target* one rule per commit, scan again, red tests worked one at a time, schema, upgrade wizards verified on data, caches | Cleared to hand over |
| **3 Post-flight** | Sweep again with the new core's rules, local deprecation-log crawl, ferry equipment removed, constraints re-pinned, upgrade report and debrief | Debriefed |

Every checklist answer, measurement, scan and refactoring rule lands in a flight
log inside the project. Nothing is estimated.

---

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Prepare the project](#prepare-the-project)
- [Upgrade a project, step by step](#upgrade-a-project-step-by-step)
- [What you get: the flight log](#what-you-get-the-flight-log)
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
- PHP where the project runs it: [ddev](https://ddev.com/) is detected
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

**Update and remove:**

```bash
claude plugin marketplace update fly-the-upgrade
claude plugin update fly-the-upgrade@fly-the-upgrade
claude plugin uninstall fly-the-upgrade@fly-the-upgrade
```

**Try it without installing** (for example from a local clone):

```bash
git clone https://github.com/sbuerk/claude-fly-the-upgrade.git
claude --plugin-dir ./claude-fly-the-upgrade
```

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
4. **Have a working local instance** (installed, database set up). The TCA
   migration check, the schema step, the upgrade wizards and the frontend checks
   run against it.

## Upgrade a project, step by step

### 1. Start the flight

Open Claude Code in the project root and run:

```
/fly-the-upgrade:upgrade 13.4
```

(or just say *"upgrade this project to TYPO3 13.4"*). Claude asks who decides
the gates:

- **human** (default): Claude stops at the end of every phase, shows the
  evidence and asks you for Go or No-Go.
- **auto**: Claude decides by the written gate criteria. Human-only checklist
  lines are still handed over to you, never ticked off. Use it for rehearsals
  and unattended runs.

It then runs `upgrade-pilot init`, which detects the installed TYPO3 version,
the runtime (ddev, local PHP), your own extensions (path repositories, classic
extensions, or the repository itself when it is an extension) and the test
commands. **Check what it prints.** A wrong test command poisons every
measurement.

### 2. Pre-flight (on a branch, still on the current version)

Claude creates `upgrade/preflight-<current>` from your branch and works through
the pre-flight checklist:

- version facts, PHP overlap and support dates (`get.typo3.org`, Packagist)
- a **bump probe**: constraints raised, `composer update -W --dry-run`, files
  restored. Every "Problem N" is a blocker to solve before departure
- the core changelog of the target, matched against your code
- **instruments**: core contact points of your extensions (plugins, controllers,
  services using core API, hooks, listeners, middlewares, commands, TCA,
  TypoScript) and which of them any test executes. Claude writes the missing
  tests, committed one area at a time
- a **baseline** measurement of all suites
- Rector and Fractor with the *current* version's level set, **one rule per
  commit**: apply, review, measure, commit, plan again
- remaining deprecations fixed by hand, only with API the current version has
- Extension Scanner and TCA migration check before and after
- `QRH.md` (expected failures and answers), `MEL.md` (accepted open items with
  reason and date), `BRIEFING.md`, a local backup and restore rehearsal

Everything on this branch still runs on the current version and could be
deployed before the upgrade.

**Gate: Go / No-Go.** In human mode you get the evidence and decide.

### 3. Flight (on a second branch, on the target version)

Claude creates `upgrade/<target>` from the pre-flight branch and follows the
fixed sequence: platform check, then all `typo3/cms-*` constraints, your own
extensions' constraints and the testing framework raised together and
`composer update -W`, one commit. It measures straight after the bump (that
result is the real worklist), then runs the Rector and Fractor campaigns against
the *target* level set, scans again, and works the red tests one at a time.
Generated code, such as upgrade wizards that Rector scaffolds with a `TODO`, is
completed and verified, never committed blind. Schema, wizards and caches run
on the local instance, and the wizards are checked against real rows.

**Gate: Cleared to hand over.** All suites green, without skipped or weakened
tests. Smoke tests by people, staging and editor testing are listed as your
tasks.

### 4. Post-flight

Scanner and TCA check again with the new core's rules, a local deprecation-log
crawl, upgrade-only leftovers removed, constraints re-pinned, next upgrade dated
from the support calendar, then `UPGRADE-REPORT.md` with the debrief.

**Gate: Debriefed.** The flight is closed.

### 5. Land it yourself

The pilot never merges, rebases or pushes into your base branch, and its hook
blocks attempts to while a flight is open. Review the two branches, push them,
open merge or pull requests and deploy the way your team does. The pre-flight
branch can go out first, on the current version.

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
| `UPGRADE-REPORT.md` | Key stages, every measurement, campaigns (generated code, skipped rules), commits of both branches, gates, human handoffs, accepted risks, debrief |
| `QRH.md`, `MEL.md`, `BRIEFING.md`, `DEBRIEF.md` | Written during the flight, hand them to your team |
| `config.json` | How things run: runtime wrapper, test commands, own extensions, branches, gate mode, fetched version facts |
| `flightlog.json` | The machine-readable log the CLI keeps |
| `contacts.json`, `changelog-*.json` | Full reports of the contact-point inventory and the changelog match |
| `logs/` | Raw output of every tool run, cited as evidence |

Checklist answers use five states: done, **no** (answered no, with a reason: an
accepted risk), not applicable, **handoff** (a person has to do or confirm it),
open.

## Using parts of the plugin on their own

The skills can also be used outside a full upgrade. They need a flight log, so
run `upgrade-pilot init --target <version>` once (or let Claude do it).

| Skill | Use it for |
|---|---|
| `/fly-the-upgrade:upgrade` | Start, resume, status of a whole upgrade |
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
| `--gates human\|auto` | `human` | Who decides the gates |
| `--branch-prefix` | `upgrade` | Branches `<prefix>/preflight-<source>` and `<prefix>/<target>` |
| `--ext <path>` | detected | Own extension paths, repeatable |
| `--exec '<wrapper with {cmd}>'` | detected | How to run PHP commands, for runtimes other than ddev or local PHP |
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
| `init --target <v>` | Detect project, runtime, own extensions, tests. Open the flight |
| `status [-v]` | Phase, gates, open items and how to answer them, last measurements, campaigns |
| `item <id> done\|no\|na\|handoff\|open --note --evidence` | Answer a checklist line. `no` and `na` need a reason |
| `gate <phase> show\|go\|nogo --note` | Gate criteria and blockers, or record the decision |
| `measure --label <stage> [--suite <name>\|all]` | Run the suites, parse PHPUnit, record, print failures |
| `scan --label` | Extension Scanner over own extensions, diffed against the last scan |
| `tca --label` | Headless *Check TCA Migrations* (the core has no CLI for it) |
| `contacts` | Core contact points and which ones the tests execute |
| `versions [--target]` | Support dates, PHP range, compatible testing framework |
| `bump show\|probe\|apply` | Raise core constraints. `probe` dry-runs composer and restores the files |
| `changelog fetch\|match` | Fetch the target's core changelog, match it against own code |
| `rules config\|plan\|next\|apply\|commit\|skip\|list` | Rector and Fractor campaigns, one rule at a time |
| `snapshot take\|restore\|list` | Local database snapshots (ddev) |
| `report` | Render `UPGRADE-REPORT.md` |

`upgrade-pilot <command> --help` shows every option.

## Safety

- Gates default to a human decision.
- Human-only work (production backup, freeze, editor smoke test, staging) is
  recorded as a handoff with instructions, never marked done by the pilot.
- A hook blocks `git merge`, `commit`, `rebase`, `cherry-pick`, `pull` and
  `revert` on the base branch, pushes to it, moving or deleting it, and
  `gh pr merge`, while a flight is open. It is a seatbelt, not a security
  boundary.
- Tests are never deleted, skipped or weakened to reach green. Fixtures that
  model production data are only changed the way the upgrade wizard changes the
  production data, and the commit says so.
- Commit messages follow your project's rules (its `CLAUDE.md`, `AGENTS.md`,
  contribution guide or your instructions). Without any, the TYPO3 Core format
  is used.
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

## What is in this repository

| Path | What |
|---|---|
| `.claude-plugin/` | Plugin manifest and the marketplace entry |
| `skills/` | The six skills |
| `agents/rule-reviewer.md` | Read-only reviewer for one rule's diff |
| `hooks/` | The base-branch guard |
| `bin/upgrade-pilot`, `lib/upgrade_pilot/` | The CLI |
| `lib/php/tca-migrations.php` | Headless TCA migration check, copied into the project at run time |
| `data/checklist.json` | The three-phase checklist, with who can answer each line |
| `data/templates/` | Starting points for QRH, MEL and briefing |
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
