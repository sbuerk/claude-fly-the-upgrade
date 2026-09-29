---
name: upgrade
description: Fly a TYPO3 major upgrade (for example 12.4 to 13.4, or 13.4 to 14.x) of a composer project or extension in three gated phases, pre-flight, flight and post-flight, with a tracked flight log, instrument tests for core contact points and Rector/Fractor applied one rule per commit. Use when the user wants to plan, start, resume or check the status of a TYPO3 core upgrade.
when_to_use: >-
  Requests like upgrade this project to TYPO3 13, prepare the v14 upgrade,
  where are we with the upgrade, continue the upgrade, run the upgrade checklist.
argument-hint: "[target version, e.g. 13.4 | status | resume]"
---

# Fly the Upgrade: the pilot

An upgrade is flown, not hoped for. Three phases, each ending in a gate:

| Phase | Skill | Ends with |
|---|---|---|
| 1 Pre-flight: nothing touches the target version | `fly-the-upgrade:preflight` (+ `fly-the-upgrade:instruments`) | Go / No-Go |
| 2 Flight: the fixed sequence, on the target version | `fly-the-upgrade:flight` | Cleared to hand over |
| 3 Post-flight: sweep again, remove ferry equipment, debrief | `fly-the-upgrade:postflight` | Debriefed |

Rector and Fractor are always run through `fly-the-upgrade:rule-by-rule`: one rule, one review, one measurement, one commit.

## The tracking tool

Everything is recorded by the `upgrade-pilot` CLI that ships with this plugin (on `PATH` while the plugin is enabled, otherwise `${CLAUDE_PLUGIN_ROOT}/bin/upgrade-pilot`). It needs Python 3 on the host. State lives in `.upgrade-pilot/` at the project root, which `init` adds to `.git/info/exclude`, so it survives branch switches and never ends up in a commit:

| File | What |
|---|---|
| `config.json` | how to run things: runtime wrapper, test commands, own extensions, branches, gate mode |
| `flightlog.json` | what happened: checklist answers, gates, measurements, scans, TCA checks, rule campaigns, journal |
| `FLIGHT-LOG.md` | rendered from `flightlog.json` after every change, for humans |
| `QRH.md`, `MEL.md`, `BRIEFING.md` | written by you during pre-flight |
| `logs/` | raw output of every tool run, cite these as evidence |

Never edit `flightlog.json` or `FLIGHT-LOG.md` by hand. Use the CLI. Run `upgrade-pilot <command> --help` when unsure about options.

## Starting or resuming

1. `upgrade-pilot status -v`. If it says no flight exists, this is a new flight:
   - Working tree must be clean, on the branch the upgrade should start from (usually the main line).
   - Ask the user, unless already stated: target version, and who decides gates. `human` (default) means you stop at every gate and ask. `auto` means you decide by the written criteria and hand human-only items over. Only use `auto` when the user asked for an unattended run.
   - `upgrade-pilot init --target <major.minor> [--gates human|auto]`
   - Read the detected runtime, own extensions and test commands it prints. Correct `.upgrade-pilot/config.json` if anything is wrong (a wrong test command poisons every measurement). Test commands have `"where": "host"` (run as is) or `"where": "runtime"` (wrapped, e.g. into `ddev exec`). Set `"confirmed": true` once a suite ran as expected.
2. Otherwise continue in the phase `status` reports, with the matching phase skill. The first open item in that phase is the next thing to do.

## Branch model

- Base branch (recorded at init): never committed to, merged into or pushed to while the flight is open. The plugin's hook blocks this. Integrating the upgrade is a human decision after the gates, not part of the flight.
- Pre-flight branch `<prefix>/preflight-<source>`, from the base branch: instrument tests and clean-ups that still run on the **source** version. It could ship before the upgrade.
- Flight branch `<prefix>/<target>`, from the pre-flight branch: the bump and everything after it.

## Non-negotiables

- **Measure, never estimate.** Every claim about tests, scanner findings or TCA migrations comes from an `upgrade-pilot measure|scan|tca` run recorded in the log. Quote the recorded numbers.
- **Order is not a preference.** Rector and Fractor for the target run *after* the packages are raised. Wizards after the schema. The schema after the code.
- **One tool, one commit. One rule, one commit.** No unrelated refactoring on these branches (sterile cockpit).
- **Generated code is read before it is trusted.** Anything a tool scaffolds (upgrade wizards, TODO markers) is completed or reported, never committed blind.
- **"No" is a valid answer.** `upgrade-pilot item <id> no --note "<reason>"` is an accepted risk. An open item is a forgotten one.
- **Tests are not weakened to get green.** Never delete, skip or loosen a test or `failOnDeprecation` to pass a gate. Fixtures that represent data may be migrated the way production data is migrated, and that must be said in the commit.
- **Do not guess facts.** Versions, PHP ranges and support dates come from `upgrade-pilot versions`. Behaviour changes come from the changelog entries in the core (`upgrade-pilot changelog`) or the tool's `@changelog` reference.
- **Commit messages follow the project's rules** (its CLAUDE.md, CONTRIBUTING or the user's instructions, including attribution rules). Without any rules, use the TYPO3 Core format: `[TASK] Subject` up to 52 characters, body wrapped at 72.
- **Human-only items are never faked.** Backups of production, freezes, editor smoke tests and staging deployments are `handoff` with a note saying what the human has to do.

## Reporting to the user

After each phase, and whenever you stop, give: the phase and gate state, the measurement table from the flight log (stage, result, exit), what changed since the last report, and what is waiting for a human. Point to `.upgrade-pilot/FLIGHT-LOG.md` for the full picture.
