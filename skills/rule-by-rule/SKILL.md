---
name: rule-by-rule
description: Run Rector (ssch/typo3-rector) or Fractor (a9f/typo3-fractor) on a TYPO3 project one rule at a time, each rule reviewed, measured with the test suites and committed on its own, until the dry run is empty. Use for the pre-flight and flight refactoring campaigns of an upgrade, or whenever the user wants Rector/Fractor applied in reviewable steps instead of one big diff.
argument-hint: "[rector|fractor] [campaign name]"
---

# Rule by rule

Rector is a co-pilot, not an autopilot. A single `rector process` produces one diff nobody can review, mixes a dozen reasons into one commit, and hides the one rule that silently broke something (for example a plugin registration moved from `list_type` to `CType`, with a scaffolded upgrade wizard that says `TODO: Add this mapping yourself!`). So: one rule, one review, one measurement, one commit.

A **campaign** is one tool with one configuration on one branch, named `<phase>-<tool>` by default (`preflight-rector`, `flight-fractor`). The CLI remembers every rule's state: `pending`, `applied` (uncommitted), `committed`, `skipped` (with reason), `noop` (changes nothing alone), `absorbed` (disappeared from the dry run after other rules), `reappeared` (reported again after being committed: investigate).

## Setup

- The config must exist and have the right level set for the phase: source major in pre-flight, target major in flight, and in flight only **after** the packages are raised (the rules ship with the tool, the code they match ships with the core). `upgrade-pilot rules config --tool <rector|fractor> --level <major>` creates it for own extensions or changes the `UP_TO_TYPO3_<n>` level. Commit a config change on its own before the campaign.
- The working tree must be clean. `apply` refuses otherwise, because the diff could not be attributed to one rule.
- Decide the per-rule measurement. Default: all configured suites (`upgrade-pilot measure --label ...`). For very large campaigns a faster suite per rule is acceptable, with the full suite at least every 10 rules and at the end, and say so in the flight log with `item` notes.

## The loop

```
upgrade-pilot rules plan  --tool <tool> [--campaign <name>]    # dry run, JSON, rule -> files
repeat:
  upgrade-pilot rules apply --campaign <name>                  # exactly one rule, the next pending one
  review (below)
  upgrade-pilot measure --label "<tool>: <RuleShortName>"
  write the body to .upgrade-pilot/tmp/body.txt
  upgrade-pilot rules commit --campaign <name> --tag TASK --subject "<what changed>" --body-file .upgrade-pilot/tmp/body.txt [--note "..."]
  upgrade-pilot rules plan --campaign <name>                   # rules interact, re-plan every time
until plan reports 0 rules
```

`apply` uses the tool's native `--only` when available and otherwise generates a single-rule configuration (project config plus every other loaded rule skipped), so older Rector versions work too. It reports changed files, **new files**, **markers** (TODO/FIXME in added code), rules the tool applied in the same run, the rule's source file and its `@changelog` links.

## Review, every rule

Run `git diff` (and read new files in full). Then answer:
1. Is every hunk what the rule's changelog entry asks for? Open the `@changelog` link or the rst in the core when the intent is unclear.
2. Does it only touch what it should? A rule may reformat or touch unrelated code, fix that by hand in the same commit or skip the rule.
3. **New files and markers.** Generated code is incomplete by design. Complete it (for example fill the wizard mapping from the real data, which you can derive from existing registrations and fixtures) or skip the rule and put the work on the QRH. Never commit a TODO a tool wrote for you without a decision recorded in the commit body.
4. **Data consequences.** Does the change alter how existing database records are interpreted (plugin registration type, CType, field names, FlexForm structure)? Then a data migration is part of this change: an upgrade wizard for production and the matching update of test fixtures, in the same commit, and a QRH row. Say it in the commit body.
5. Layout. Tools print code their own way: Rector 1.x collapses fluent method chains onto one line, Fractor re-indents TypoScript conditions. If the project has a coding-standards fixer, run it on the changed files only. Otherwise restore the original layout by hand in the same commit, so the diff shows the migration and nothing else.

For long or tricky diffs, delegate the review to the `fly-the-upgrade:rule-reviewer` agent with the campaign, rule and diff, then decide yourself.

## Measure, then decide

Compare the measurement with the previous one in `.upgrade-pilot/FLIGHT-LOG.md`. For TCA rules also run `upgrade-pilot tca --label "<tool>: <RuleShortName>"`: the core raises one combined deprecation for all TCA migrations, so the suite only changes when the last one is gone, while the TCA message count drops with every rule.

- same or better: commit.
- worse: find out why before committing. A rule that is correct but exposes missing data migration gets that migration in the same commit. A rule that is wrong for this code: `upgrade-pilot rules skip --campaign <name> --reason "<why>"` (reverts the files) and add a QRH or MEL row if the change is still needed by hand.

## Commit message

`rules commit` renders the style chosen at init (TYPO3 Core or YouTrack style, or a custom template), adds the issue reference of the step (default step: the campaign, so one issue per campaign in per-step and placeholder mode), `Related:` lines, and appends `Applied <Tool> rule <class>.` to the body when you did not name the rule. Use `--dry-run` on `upgrade-pilot commit` to preview the style. Subject says what changed in the code, not which tool ran. Copy changelog references from the `@changelog` link `apply` printed, the scanner output or a file name in the core's `Documentation/Changelog`, never type them from memory. Body names the tool and full rule class, the changelog reference, and any manual completion or data migration you added. TYPO3 Core style example:

```
[TASK] Migrate QueryBuilder::execute() calls        (YouTrack style: [TASK] PRJ-123: Migrate ...)

Replace the deprecated QueryBuilder::execute() with executeQuery()
and executeStatement().

Applied Rector rule
Ssch\TYPO3Rector\TYPO312\v0\MigrateQueryBuilderExecuteRector.
Changelog: Deprecation-96972-DeprecateQueryBuilderexecute
```

## Sets: TYPO3 first, PHP as its own campaign

The TYPO3 level set (`rector.php`, `fractor.php`) is the upgrade. If the flight was opened with `--php-set`, the PHP level set runs afterwards as a separate campaign with its own configuration, still one rule per commit:

```
upgrade-pilot rules config --tool rector --set php            # rector-php.php, minimum PHP of the target core
upgrade-pilot rules plan --tool rector --campaign <phase>-rector-php --config rector-php.php
```

It modernises syntax the target's minimum PHP allows, so it belongs on the flight branch (or on the pre-flight branch only when production already runs that PHP version). Skip rules that only restyle code without a reason for this upgrade, and say so with `rules skip --reason`.

## Finish

When `plan` reports 0 rules, run the full suite once more (`--label "<campaign> done"`), then `upgrade-pilot rules list --campaign <name>` and report: committed, skipped with reasons, no-ops, generated files you completed. Answer the matching checklist item (`pf.rector-fractor-current`, `fl.rector` or `fl.fractor`) with the campaign name as evidence.
