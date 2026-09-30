# Changelog

All notable changes to this plugin. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow
[semantic versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-09-30

### Added

- Initialization asks how to run things: `init --detect` reports ddev, direnv
  (an `.envrc` in the project or one folder up, its `direnv status`, php and
  composer inside it) and local PHP, plus the commit style of the repository.
  New runtime `direnv`, chosen with `--runtime`. An `.envrc` is never allowed by
  the pilot.
- Commit policy chosen at init: TYPO3 Core style without Resolves/Releases,
  YouTrack style `[TAG] PRJ-123: Subject` with `Related:` lines, or a custom
  template. Issue modes: none, single reference, parent plus one issue per step,
  or `{ISSUE-nn}` placeholders with `ISSUES.md` and `issues apply`, which
  replaces them in the pilot branches through a local history rewrite.
- `upgrade-pilot commit`, `composer` and `run`: commits in the configured style,
  composer files only changed by recorded commands, listed in a
  `Used command(s):` block. `--into-composer-commit` folds composer-only changes
  into the branch's composer commit.
- `--context` at init and `upgrade-pilot context`: pre-collected issues,
  documents and notes, read and digested before the pre-flight.
- `--php-set` and `rules config --set php`: the Rector PHP level set as its own
  campaign, one rule per commit.
- Reports per gate and final: developer report (English), PM/customer report
  (English and German), with summaries written into `notes/`.
- `docs/PROCESS.md`: the full process guide.
- README: how to update the plugin, and upgrade notes per version for flights
  opened with an earlier version.
- The guard blocks every push and pull or merge request creation while a flight
  is open, unless `--allow-push` was chosen.

- `upgrade-pilot deps list|docs`: third-party packages that move with the bump
  (from the bump probe, or from the old and new composer.lock), and what their
  maintainers documented between the installed and the target release. Found by
  convention for any package: TYPO3-style `Documentation/Changelog/<version>/`
  entries, CHANGELOG / UPGRADE / MIGRATION / NEWS files, upgrade guides, GitHub
  and GitLab release notes, `[!!!]` or breaking commits, and upgrade wizards new
  in the target release. Sources come through composer, so private repositories
  work with the project's credentials. Per-package reports with the full text
  and hits in own code.
- Checklist lines `pf.dependency-docs` and `fl.dependency-migrations`. The
  pre-flight turns dependency breaking entries and wizards into QRH rows, the
  flight re-reads them for the versions really installed and expects their
  wizards in step 8.

### Changed

- `bump` changes composer files through `composer require --no-update` commands
  instead of editing them, and records the commands for the commit.
- `rules commit` renders the configured commit style (`--subject`, `--body`,
  `--step`) instead of taking a message file.
- `report` writes the reports per phase (`--phase`), `UPGRADE-REPORT.md` is the
  final developer report.
- direnv status lines are filtered from captured tool output.

## [0.2.0] - 2026-09-29

### Added

- `upgrade-pilot schema check|plan|apply`: detects TYPO3 Console
  (`helhum/typo3-console`) from the lock file and confirms in the runtime which
  binary offers `database:updateschema` (`typo3`, or `typo3cms` before Console
  8.0). With Console: dry run of the exact statements and a safe apply that
  repeats until the dry run is empty. Without it: `extension:setup`, run twice.
  Destructive update types need `--allow-destructive`.
- Checklist lines `pf.schema-tooling` (pre-flight: Console present, or offered
  to the team with a version that supports source and target) and
  `pst.schema-destructive` (post-flight: drops and renames listed for after the
  rollback window). Existing flights receive new checklist lines as open items.
- `versions` reports compatible TYPO3 Console releases, filtered by the
  runtime PHP version, including a constraint that bridges source and target.

### Changed

- `bump` handles companion packages generically: the testing framework moves to
  the newest compatible major as before, TYPO3 Console only when its constraint
  allows no release for the target, with a warning when that crosses Console
  8.0 (the `typo3cms` binary is gone).
- Compatibility of companion packages is probed against the latest patch of a
  core line instead of `x.y.0`.
- The flight skill applies the schema through `upgrade-pilot schema` and requires
  a converged dry run, the post-flight skill lists destructive changes.

## [0.1.0] - 2026-09-29

### Added

- Skills `upgrade`, `preflight`, `instruments`, `rule-by-rule`, `flight` and
  `postflight` for a three-phase TYPO3 major upgrade with gates.
- Agent `rule-reviewer` for the review of one Rector or Fractor rule's diff.
- PreToolUse hook that keeps merges, commits and pushes off the base branch while
  a flight is open.
- `upgrade-pilot` CLI: flight log with the checklist of the talk, gates, test
  measurements, Extension Scanner and headless TCA migration check, core contact
  point inventory, version facts from get.typo3.org and Packagist, composer bump
  probe, changelog matching, Rector and Fractor campaigns one rule per commit,
  ddev snapshots, upgrade report.
- Verified by a test flight TYPO3 12.4.45 to 13.4.35.

[Unreleased]: https://github.com/sbuerk/claude-fly-the-upgrade/compare/fly-the-upgrade--v0.3.0...HEAD
[0.3.0]: https://github.com/sbuerk/claude-fly-the-upgrade/compare/fly-the-upgrade--v0.2.0...fly-the-upgrade--v0.3.0
[0.2.0]: https://github.com/sbuerk/claude-fly-the-upgrade/compare/fly-the-upgrade--v0.1.0...fly-the-upgrade--v0.2.0
[0.1.0]: https://github.com/sbuerk/claude-fly-the-upgrade/releases/tag/fly-the-upgrade--v0.1.0
