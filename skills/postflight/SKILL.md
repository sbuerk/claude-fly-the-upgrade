---
name: postflight
description: Phase 3 of a TYPO3 major upgrade (approach, landing and debrief). Sweep again with the new core's rules (Extension Scanner, TCA migrations, deprecation log), remove upgrade-only ferry equipment, re-pin constraints, raise CI, record new deprecations as the next upgrade's work list, write the upgrade report and close the flight. Use after the "cleared to hand over" gate, or when the flight log says phase postflight.
argument-hint: "[resume]"
---

# Phase 3: Approach, Landing & Debrief

Green again is the end of the flight, not of the work. Everything found here is the pre-flight of the next upgrade. Work stays on the flight branch.

## Straight after landing

- `pst.frontend`: request the main pages of the local site and check status and content, then `handoff` for a human look.
- `pst.backend`, `pst.logs`: human, `handoff` with concrete instructions (which modules, which log files).
- `pst.scheduler`: if `typo3/cms-scheduler` is installed, `typo3 scheduler:list` (or the backend module) and a dry run of own tasks. Otherwise `na`.

## Sweep again, with the new rules

- `upgrade-pilot scan --label postflight`: the scanner now warns about the version after this one. Every remaining finding is either fixed now or goes into the "next flight" list in the report.
- `upgrade-pilot tca --label postflight`: the migration list changes with the core, a new message here is a new deprecation.
- `pst.deprecation-log`: locally, enable the deprecation log writer in a settings file that is not committed (for example a git-ignored `config/system/additional.php`: copy it first, restore it byte for byte afterwards):
  `$GLOBALS['TYPO3_CONF_VARS']['LOG']['TYPO3']['CMS']['deprecations']['writerConfiguration'][\Psr\Log\LogLevel::NOTICE][\TYPO3\CMS\Core\Log\Writer\FileWriter::class]['disabled'] = false;`
  Flush caches, request the frontend pages and page types you can reach, read `var/log/typo3_deprecations_*.log` and `var/log/typo3_*.log`. Instance configuration (`settings.php`) shows up here and nowhere else. Real editor traffic is `handoff`.
- `pst.static-missed`: compare what the tests reported during the flight with what the scanner and changelog match predicted in pre-flight. List what only the tests caught. That list is the argument for the instruments.
- Target-version deprecations still open: optionally run a Rector campaign at the *next* level only as a dry run (`rules plan`), and put the result in the report, not into this branch.

## Remove the ferry equipment

- `pst.schema-destructive`: with TYPO3 Console, `upgrade-pilot schema plan --destructive --label postflight` lists what the target no longer needs (fields and tables to rename or drop). Without it, the same list is in Admin Tools > Maintenance > Analyze Database Structure (`handoff`). Put every entry on the MEL with a date after the rollback window. Running them is a human decision (`schema apply --types destructive --allow-destructive`), never part of this flight.
- `pst.shims`, `pst.markers`: grep the diff of both branches for compatibility shims and TODO markers added during the flight (`git diff <base>...HEAD`). Remove what is resolved, one commit.
- `pst.upgrade-packages`: rector, fractor, the scanner CLI and similar exist for the upgrade. Propose to the user: keep in `require-dev` (and in CI) or move to an isolated tools install. Record the decision, do not decide alone.
- `pst.constraints`: own extensions' `composer.json` and `ext_emconf.php` point at the target only, unless the extension deliberately supports both.
- `pst.ci`: CI must run on the target version. Propose the change, and raise scanner/Rector checks to the next target.

## Record it while you still remember

- `upgrade-pilot versions` for the next target: support end of the new version gives the date of the next flight (`pst.maintenance`).
- `upgrade-pilot changelog match` lists `Feature` entries touching own code: `pst.features` is a human triage, `handoff` with the list.
- `upgrade-pilot report` writes `.upgrade-pilot/UPGRADE-REPORT.md` from the flight log: measurements stage by stage, scanner and TCA trend, rule campaigns with generated code and skipped rules, commits of both branches, gates, open handoffs, accepted risks. The debrief is yours to write, in `.upgrade-pilot/DEBRIEF.md` (the report embeds it, re-rendering never overwrites it): what the QRH predicted versus what happened, what took longest, what only the tests caught, and the lines to add to the checklist. Then run `upgrade-pilot report` again (`pst.report`, `pst.checklist`).
- `pst.docs`: update the project's own upgrade notes or README if they mention versions or commands that changed.

## Gate: debriefed

`upgrade-pilot gate postflight show`, then decide per gate mode. A GO sets the phase to `landed`, which also releases the base-branch guard. Tell the user where the branches are, what the report says, and that integrating the branches into the base branch is theirs to do.
