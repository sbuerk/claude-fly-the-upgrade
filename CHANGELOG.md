# Changelog

All notable changes to this plugin. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow
[semantic versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/sbuerk/claude-fly-the-upgrade/compare/fly-the-upgrade--v0.1.0...HEAD
[0.1.0]: https://github.com/sbuerk/claude-fly-the-upgrade/releases/tag/fly-the-upgrade--v0.1.0
