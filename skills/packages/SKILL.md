---
name: packages
description: Update, or only check, selected third-party packages of a TYPO3 project without a core upgrade. One package, a list, or a glob such as split packages (acme/shop-*), to a release, a branch alias or a development branch. Reads changelogs, upgrade guides, release notes and the rendered manual on docs.typo3.org, finds and verifies every place where own extensions, sitepackages, configuration and patches use or modify those packages (XCLASS, subclasses, listeners, overrides and more), runs the same gated phases as a core upgrade, and reports for developers and project managers. Use when the flight log says scope packages.
when_to_use: >-
  Requests like update acme/shop to 3.0, check whether we can move the shop
  extensions to the main branch, what breaks if we update extension X, raise
  the vendor/* packages to the next minor, assess the update of these
  extensions without doing it.
argument-hint: "[package or glob] [target version or branch | status | resume]"
---

# Packages scope: third-party updates without a core upgrade

The core stays where it is. The packages the user names move, and everything the project built on top of them has to move along. The phases, gates, commit policy, reports and non-negotiables are those of `fly-the-upgrade:upgrade`. Read it first if you have not in this session. This skill says what is different.

Two modes, chosen at init:

| Mode | What happens | Ends with |
|---|---|---|
| update | pre-flight, flight, post-flight, like a core upgrade | Debriefed |
| check (`--check-only`) | pre-flight only, nothing in the project changes | Go / No-Go, then the flight is `landed` |

A check is the answer to "what would it take". Its reports are an assessment, and a later update starts a new flight from them.

## Nothing here is package-specific

The plugin knows no extension. Every finding comes from what the packages declare (composer metadata, PSR-4 namespaces, extension key, TCA tables, plugin registrations, templates, labels), from what their maintainers documented, and from what the project's own code does. Never add knowledge about a particular package to the plugin. If a package does something unusual, it is a finding for the QRH, found by reading its code and documentation.

## Starting: ask first

Follow "Starting a new flight" in the upgrade skill (runtime, commit style, issues, gates, extras). In addition, ask with `AskUserQuestion`:

- **Scope**: core upgrade, or selected packages. For packages: which ones. Names, a list, or globs (`vendor/prefix-*` for split packages). Globs are matched against `composer.lock`, init prints what matched.
- **Target**: a release constraint (`^3.0`, `3.0.2`), or a development branch (`dev-main`, `2.x-dev`). Composer resolves the name, check it with the user if unsure.
- **Development target**: composer only accepts development versions of dependencies when the root allows them. `--dev-stability minimum-stability` records `composer config minimum-stability dev` and `composer config prefer-stable true` (only the named packages become dev, the rest stays stable). `none` leaves it to the user (for example explicit `@dev` flags). Say that this is temporary and belongs on the MEL with a date.
- **Mode**: update or check only.

Then:

```bash
upgrade-pilot init --scope packages --package '<name or glob>' [--package ...] --to <target> \
  [--dev-stability minimum-stability|none] [--check-only] [--label <slug>] <the options of the upgrade skill>
```

The label names the branches (`<prefix>/preflight-<label>`, `<prefix>/<label>`), default from the package and target. `init --force` on an existing flight moves the old state to `.upgrade-pilot/archive/`, it never mixes two flights.

The checklist of this scope is `data/checklist-packages.json`. `upgrade-pilot status -v` shows its items with their `how`.

## Pre-flight

Work the items in order. Everything except instrument tests stays unchanged in the project.

1. **Inventory** (`pf.packages-inventory`, `pf.packages-support`): what init resolved, which of them are direct requirements and which come along. `upgrade-pilot deps list` after the probe shows abandoned packages. Maintainer contacts are a human answer.
2. **Compatibility** (`pf.packages-compatibility`): `upgrade-pilot versions`. It checks the target's `typo3/cms-core` and `php` requirements against what is installed, and reads declared branch aliases. A **WARNING about a branch alias** means the alias is declared for another version name than the one composer uses, so composer ignores it and constraints of other packages on the aliased version will fail. That is a packaging issue of the package, report it to its maintainers.
3. **Probe** (`pf.packages-probe`): `upgrade-pilot bump probe`. It runs the recorded composer commands and `composer update <packages> -W --dry-run`, then restores the files. If it does not resolve, read every "Problem N". When a package of the flight does not satisfy a constraint of another one, the CLI says why and what helps:
   - wait for a release, or choose another branch or version
   - bridge it with an inline alias in the root `composer.json`: `upgrade-pilot bump probe --alias <name>=<version>` (remembered for `apply`, listed as a temporary workaround in the reports). An alias is a deliberate decision with the user, never a silent fix.
4. **Stability** (`pf.packages-stability`): for a development target, the decision from init goes on the MEL with the date or event that ends it (usually the release).
5. **Documentation** (`pf.dependency-docs`): `upgrade-pilot deps docs`. Per package it reads, between the installed and the target version:
   - TYPO3-style changelog entries in the package, CHANGELOG, UPGRADE, MIGRATION files, upgrade guides, release notes of the hosting, commits marked as breaking
   - the rendered manual on docs.typo3.org, as Markdown where published (`--no-rendered` to skip). Pages of the target manual that are new against the installed version's manual, upgrade and migration guides first. Changelog pages are skipped when the repository's changelog was read already, they are the same entries.
   - new upgrade wizards, and whether one is **opt-in** (excluded from the service container by the package, so the core never offers it). The class documentation is in the report.
   Read every report in `.upgrade-pilot/deps/` completely. A breaking change on a minor or a development branch is still a breaking change.
6. **Touchpoints** (`pf.packages-touchpoints`): `upgrade-pilot deps touchpoints --verify --label preflight`. It scans own extensions, sitepackages, local path packages, `config/` and the root `composer.json` (patches) for every place that uses or modifies the packages, and verifies each against the target: signatures of overridden methods (also for XCLASS replacement classes), final classes, removed classes and events, changed originals of copied templates, removed label keys, missing ViewHelpers, changed patched files. Each entry ends as `ok`, `manual` or `attention`. The details are in `.upgrade-pilot/touchpoints.json`.
7. **Work list** (`pf.breaking-worklist`): every breaking entry that touches the project and every `attention` touchpoint becomes a `QRH.md` row: what breaks, where, the migration text of the package, what you will do.
8. **Tests** (`pf.packages-tests`): the existing suite rarely executes third-party code. With `fly-the-upgrade:instruments`, add tests that render the package's plugins with the project's configuration, run own listeners and overrides, and read records through the package's repositories. Only these tests turn a touchpoint into a measurement. Commit them on the pre-flight branch (`upgrade-pilot commit --step instruments`).
9. **Baseline, QRH, MEL, briefing, schema tooling, backup** as in `fly-the-upgrade:preflight`.

Gate `preflight`. In **check** mode the GO lands the flight: write the notes and run `upgrade-pilot report --phase all` (preflight and final). The final reports say that nothing was changed. Stop there.

## Flight (update mode)

The sequence, one item each, in this order:

1. `fl.backup`, `fl.branch`: flight branch from the pre-flight branch (or the base branch when the pre-flight made no commits).
2. `fl.packages-require`: `upgrade-pilot bump apply` records the composer commands (stability, requires, aliases), then `upgrade-pilot composer update <packages> -W --no-interaction` as printed. Commit as the first commit of the branch: `upgrade-pilot commit --tag TASK --subject "Raise <packages> to <target>" --step packages`. Then `upgrade-pilot measure --label "after packages"`.
3. `fl.dependency-migrations`: work the QRH. `upgrade-pilot deps list --from-lock <pre-flight branch>` shows what really moved, `deps docs` for anything new.
4. `fl.third-party-modifications`: `upgrade-pilot deps touchpoints --verify --label flight`. Adapt signatures, replace removed events with what the migration text names, and so on, one logical change per commit. Use `upgrade-pilot commit --path <dir-or-file>` when several changes are pending, so each commit holds one of them. Repeat until nothing is in `attention`.
5. `fl.packages-overrides`: re-base template copies. Diff the old and the new original, then re-apply only the project's own changes to the new original. A copy without own changes is replaced by the new original, and is then better removed together with its template path, if the project does not need it.
6. `fl.packages-configuration`: site sets and settings, TypoScript constants, TCA overrides, extension configuration, as the changelog says.
7. `fl.schema`: `upgrade-pilot schema plan` and `schema apply`, as in the flight skill.
8. `fl.wizards`: `typo3 cache:flush`, `typo3 upgrade:list`, run the new wizards, verify on data. Opt-in wizards need a decision (see the flight skill).
9. `fl.caches`: flush, request the pages that use the packages.

`upgrade-pilot measure` after each fix. Gate `flight` when every suite is green.

## Post-flight (update mode)

- `pst.touchpoints`: `deps touchpoints --verify --label postflight` on the final state.
- `pst.packages-deprecations`: the Deprecation entries of the deps reports that the project still uses are the next update's work list.
- `pst.packages-stability`, `pst.constraints`: once a release exists, pin it (`upgrade-pilot composer require --no-update <name>:^<version>`) and revert the stability settings and aliases. Until then both stay on the MEL as `handoff` with a date.
- Frontend, backend, logs, deprecation log, docs and debrief as in `fly-the-upgrade:postflight`.

Then the reports, as in the upgrade skill.
