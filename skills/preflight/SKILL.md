---
name: preflight
description: Phase 1 of a TYPO3 major upgrade (dispatch and pre-flight). Inventory, route, instrument tests for core contact points, baseline measurement, deprecation clean-up on the current version with Rector/Fractor rule by rule, Extension Scanner and TCA migration check, QRH/MEL/briefing, backup rehearsal, and the Go / No-Go gate. Use after `upgrade-pilot init`, or when the flight log says phase preflight.
argument-hint: "[resume]"
---

# Phase 1: Dispatch & Pre-Flight

Nothing here touches the target version. The aim is to reach the runway with a known aircraft, a read route and working instruments. Everything you change in this phase must still run on the **source** version.

Read `fly-the-upgrade:upgrade` first if you have not in this session. Use `upgrade-pilot status -v` to see what is open. Record every answer with `upgrade-pilot item <id> <done|no|na|handoff> --note "..." --evidence "..."`.

## 0. Branch

Clean working tree on the base branch, then `git switch -c <preflight branch from config.json>`. Item `fl.branch` is for the flight branch, not this one.

## 1. The aircraft you have

- `pf.current-version`: installed core is in `config.json` (`source_installed`). Check patch level with `<composer> outdated "typo3/cms-*" --direct --patch-only` (composer command from `config.json`, without `--patch-only` it lists the next majors). If a newer patch of the source version exists and resolves, updating it is a separate, first commit. If composer refuses because of security advisories on an unmaintained version, record that fact, it is a finding, not something to silence.
- `pf.platform`: PHP and database from `config.json -> platform`. Web server and image processing are `handoff` unless visible in the runtime config.
- `pf.own-extensions`: from `config.json -> extensions`. Owners are `handoff` unless the user named them.
- `pf.third-party`: `upgrade-pilot versions`, then `upgrade-pilot bump probe`. The probe edits constraints, runs `composer update -W --dry-run`, and restores the files. Every "Problem N" it prints is a package that cannot follow yet: find out if a compatible release, fork or replacement exists and write it into `QRH.md`. `pf.unowned` is a human decision.
- `pf.your-changes`: from `upgrade-pilot contacts` (step 3): XCLASS, hooks and `template-override` entries. List them in `BRIEFING.md`.

## 2. The route ahead

- `pf.target-version` and `pf.php-baseline`: `upgrade-pilot versions` prints support dates and the PHP range the target core requires. The PHP version must be supported by both source and target and be in production *before* departure. Production is `handoff`, the runtime and `composer.json -> config.platform.php` you can check.
- `pf.changelogs`, `pf.breaking-worklist`: `upgrade-pilot changelog fetch`, then `upgrade-pilot changelog match`. Read every **strong** entry's rst (path is in the cache under `.upgrade-pilot/cache/`), and at least skim the weak ones. For each entry that really touches own code, add a `QRH.md` row: what will break, found by, what we will do, changelog file name.

## 3. Instruments, before touching any code

This is the most commonly missing group and the one everything else rests on. Do it before any clean-up, so the clean-up itself is flown on instruments.

- `upgrade-pilot contacts` lists core contact points and gaps, most critical first.
- Follow `fly-the-upgrade:instruments` to add the missing tests, on this branch, one commit per logical test addition.
- `upgrade-pilot measure --label baseline`. This recorded result is the reference for "broken by the upgrade or broken already". A red baseline is fine **if it is understood**: deprecations reported by `failOnDeprecation` are the pre-flight worklist. Unexplained failures are not fine, investigate them first.
- Items `pf.tests-exist`, `pf.coverage`, `pf.baseline`.

## 4. Airworthy on the version you are on

- `upgrade-pilot scan --label preflight` and `upgrade-pilot tca --label preflight`. Record both counts.
- Rector and Fractor against the **source** version's rule set:
  - `upgrade-pilot rules config --tool rector --level <source major>` (creates `rector.php` for own extensions if missing, or sets its level set). Commit the config on its own.
  - Run the `preflight-rector` campaign with `fly-the-upgrade:rule-by-rule`.
  - Same for Fractor (`--tool fractor`, campaign `preflight-fractor`).
- Then by hand, one commit per topic, only with replacements that already exist in the source version:
  - remaining deprecations the baseline measurement reported,
  - TCA migrations reported by `upgrade-pilot tca` for own extensions (the migrated form is accepted by the source core, that is why the core can migrate it),
  - strong scanner matches.
  Re-measure after each commit (`--label "preflight: <topic>"`).
  Before committing a hand fix, check the replacement against the **target's** changelog too (`changelog match` output, or grep the fetched changelog for the symbol): an API that exists on the source can already be removed on the target, and a pre-flight fix that uses it just moves the failure. Anything that has no replacement on the source version goes on the MEL with the reason "fixable only after the bump" and a QRH row.
- Re-run `scan` and `tca` with label `preflight-clean`. Items `pf.deprecations`, `pf.scanner`, `pf.tca`, `pf.rector-fractor-current`.
- `pf.deprecation-log` needs real traffic: `handoff`. `pf.ci`: read the CI config, recommend adding scanner and Rector dry run, do not add CI jobs unasked.

## 5. Crew and contingency

- Write `QRH.md`, `MEL.md` and `BRIEFING.md` in `.upgrade-pilot/`. The QRH must include at least: the bump blockers from the probe, the strong changelog matches, what the baseline reported, and tool-generated code to expect (Rector may scaffold upgrade wizards, for example for plugin registration changes). Items `pf.qrh`, `pf.mel`, `pf.briefing`.
- `pf.schema-tooling`: `upgrade-pilot schema check`. It detects TYPO3 Console (`helhum/typo3-console`) from the lock file and confirms in the runtime which binary offers `database:updateschema` (`typo3`, or `typo3cms` for Console before 8.0).
  - **Console present:** `upgrade-pilot schema plan --label preflight` must report 0 statements. Pending safe changes on the source version mean the database already drifted from the code: find out why before departure.
  - **Console missing:** the core can only apply safe changes with `extension:setup`, without a dry run, so nobody sees the statements of the point of no return before they run. Ask the user whether to add TYPO3 Console: it is a production dependency that deployments call, so this is the team's decision, not yours. `schema check` prints a constraint that supports both the source and the target. On yes, add it on this branch as its own commit (`<composer> require "helhum/typo3-console:<constraint>"`) and run `schema plan`. If composer refuses on the source version (security advisories on an unmaintained core), do not bypass the block: add it in the flight together with the bump instead and note that on the QRH. On no, answer the item `no` with the reason, and write the manual schema review (Admin Tools > Maintenance > Analyze Database Structure) into `BRIEFING.md`.
- `pf.backup-restore`: on ddev, `upgrade-pilot snapshot take --name preflight` and prove the restore with `upgrade-pilot snapshot restore --name preflight` (local database only). Production backup and restore rehearsal is `handoff`.
- `pf.rollback-criteria`, `pf.window-people`: human. Draft proposals in `BRIEFING.md`, mark `handoff`.

## 6. Gate: Go / No-Go

`upgrade-pilot gate preflight show` prints the criteria and every open item.

- **Gate mode human:** present the evidence (baseline and latest measurement, scanner and TCA counts, probe result, MEL, handoff items) and ask the user for Go or No-Go. Record their answer: `upgrade-pilot gate preflight go|nogo --by human --note "<their reason>"`.
- **Gate mode auto:** decide yourself by the written criteria. Go only when the probe resolves, the suite state is understood, strong scanner matches are zero or on the MEL, and every open item is answered (human-only items as `handoff`). Otherwise No-Go with the reason, and stop.

No-Go is a professional outcome. Report what is missing and stop.
