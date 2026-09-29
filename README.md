# Fly the Upgrade: a TYPO3 upgrade pilot for Claude Code

A Claude Code plugin that flies a TYPO3 major upgrade the way the talk
*"Fly the Upgrade"* describes it: three phases, each ending in a gate, flown on
instruments.

| Phase | What happens | Gate |
|---|---|---|
| **Pre-flight** | Inventory, route (versions, changelogs, bump probe), **instrument tests for core contact points**, baseline, deprecations cleared on the *current* version with Rector and Fractor **one rule per commit**, scanner, TCA check, QRH / MEL / briefing, backup rehearsal | Go / No-Go |
| **Flight** | Branch, platform, packages in one transaction, Rector and Fractor for the *target* one rule per commit, scan, red tests worked one at a time, schema, wizards (verified on data), caches | Cleared to hand over |
| **Post-flight** | Sweep again with the new rules, deprecation log, remove ferry equipment, re-pin constraints, report and debrief | Debriefed |

Everything is tracked in a flight log: every checklist answer, every
measurement, every rule. Nothing is estimated.

## What is in the box

| Component | What |
|---|---|
| `skills/upgrade` | Entry point: start, resume, status, the rules of the cockpit |
| `skills/preflight` | Phase 1 |
| `skills/instruments` | Find untested core contact points and write the missing tests |
| `skills/rule-by-rule` | Rector / Fractor campaigns: apply one rule, review, measure, commit, re-plan |
| `skills/flight` | Phase 2 |
| `skills/postflight` | Phase 3 |
| `agents/rule-reviewer` | Read-only reviewer for one rule's diff (generated code, data consequences) |
| `hooks/` | PreToolUse guard: while a flight is open, nothing is merged, committed, rebased or pushed onto the base branch |
| `bin/upgrade-pilot` | The tracking and tooling CLI the skills drive (Python 3, standard library only) |
| `lib/php/tca-migrations.php` | Headless equivalent of *Admin Tools > Upgrade > Check TCA Migrations*, which has no CLI in the core |
| `data/checklist.json` | The three-phase checklist of the talk, with who can answer each line: pilot, human, or both |

## Requirements

- Claude Code with plugin support
- Python 3.9 or newer on the host (standard library only)
- git
- A **composer-mode** TYPO3 project or extension (classic mode is not supported)
- PHP where the project runs it: ddev (detected automatically), a local PHP, or any
  container you describe with an exec template
- In the project, as dev dependencies, whatever the phases use:
  `ssch/typo3-rector`, `a9f/typo3-fractor`, `typo3/testing-framework` and
  `netresearch/extension-scanner-cli` (not on Packagist, install it from its VCS
  repository). The pilot tells you what is missing.

## Install

```bash
# from a git remote or a local checkout of this repository
claude plugin marketplace add <git-url-or-path-of-this-repository>
claude plugin install fly-the-upgrade@fly-the-upgrade
```

For development, load it for one session without installing:

```bash
claude --plugin-dir /path/to/this/repository
```

## Use

In the TYPO3 project, on a clean working tree:

```
/fly-the-upgrade:upgrade 13.4
```

Claude asks who decides the gates (`human` by default, `auto` only for an
unattended run), runs `upgrade-pilot init`, shows what it detected and then
walks the phases. Resume any time with `/fly-the-upgrade:upgrade` or ask
"where are we with the upgrade".

State lives in `.upgrade-pilot/` at the project root. `init` adds it to
`.git/info/exclude`, so it survives branch switches and never lands in a commit:

| File | What |
|---|---|
| `config.json` | Runtime wrapper, test commands, own extensions, branches, gate mode, version facts |
| `flightlog.json` | Checklist answers, gates, measurements, scans, TCA checks, rule campaigns, journal |
| `FLIGHT-LOG.md` | Rendered from `flightlog.json` after every change |
| `QRH.md`, `MEL.md`, `BRIEFING.md`, `DEBRIEF.md` | Written by the crew during the flight |
| `UPGRADE-REPORT.md` | `upgrade-pilot report`: key stages, every measurement, campaigns, commits, gates, handoffs |
| `logs/` | Raw output of every tool run, cited as evidence |

## The CLI

| Command | Does |
|---|---|
| `init --target 13.4 [--gates human\|auto] [--exec "…{cmd}…"] [--ext path]` | Detect project, runtime, own extensions, test commands, open the flight |
| `status [-v]` | Phase, gates, open items (with how to answer them), last measurements, campaigns |
| `item <id> done\|no\|na\|handoff\|open --note --evidence` | Answer a checklist line. `no` and `na` require a reason |
| `gate <phase> show\|go\|nogo --note` | Gate criteria and blockers, or record the decision |
| `measure --label <stage> [--suite name\|all]` | Run the configured suites, parse PHPUnit, record, print the failures |
| `scan --label` / `tca --label` | Extension Scanner (JSON) and headless TCA migration check, recorded, diffed against the last run |
| `contacts` | Core contact points of own extensions and which ones the tests execute, gaps ranked |
| `versions [--target]` | Support dates and requirements from get.typo3.org, core PHP constraint and a compatible `typo3/testing-framework` from Packagist |
| `bump show\|probe\|apply` | Raise core constraints in root and own `composer.json` plus `ext_emconf.php`. `probe` dry-runs `composer update -W` and restores the files |
| `changelog fetch` / `changelog match` | Sparse-fetch the target's core changelog, match `:php:` literals against own code, strong and weak hits |
| `rules config\|plan\|next\|apply\|commit\|skip\|list` | Rector / Fractor campaigns, one rule at a time (native `--only`, or a generated single-rule config for Rector 1.x) |
| `snapshot take\|restore\|list` | Local database snapshots (ddev) |
| `report` | Render `UPGRADE-REPORT.md` |

`init` detects ddev (`ddev exec {cmd}`) and local PHP. For anything else pass
the wrapper, the inner command is always handed over as one quoted string:

```bash
upgrade-pilot init --target 13.4 --exec 'docker compose exec -T php sh -c {cmd}' --composer 'docker compose exec -T php composer'
```

## Safety

- Gates default to **human**. The pilot stops, shows the evidence and asks.
- Human-only checklist lines (production backup, freeze, editor smoke test,
  staging) are recorded as `handoff`, never ticked off by the pilot.
- The hook blocks `git merge|commit|rebase|cherry-pick|pull|revert` on the base
  branch, pushes to it, moving it, and `gh pr merge`, while a flight is open. It
  is a seatbelt, not a security boundary. Set `"guard": false` in
  `config.json` to switch it off for a flight.
- Integrating the flight branches into the base branch is always left to humans.

## Heuristics, and what they cannot see

`contacts` and `changelog match` are static heuristics: they rank what to read
first, they do not replace reading. String-built class names, variable method
calls and instance configuration are invisible to them, which is why the
instruments (tests), the TCA check and a local deprecation-log crawl are part of
the flight.

## Verified on

Flown end to end on the *Fly the Upgrade* workshop project, TYPO3 12.4.45 →
13.4.35, on dedicated branches, with every number below recorded by the pilot:

| Stage | Functional suite |
|---|---|
| Baseline, after the pre-flight added one instrument test | 10 tests · 14 assertions · 5 deprecations |
| End of pre-flight on 12.4 (14 Rector + 2 Fractor rules, 3 hand fixes) | OK · 10 tests · 14 assertions |
| 13.4, straight after the bump | 10 tests · 12 assertions · 1 error · 5 deprecations |
| 13.4, Rector plugin rule as generated (wizard with TODO) | 10 tests · 7 assertions · 4 errors · 4 deprecations |
| 13.4, after the flight | OK · 10 tests · 14 assertions |

Extension Scanner 13 → 8 findings on 12.4 and 11 → 9 on 13.4 (the rest is dead code on the MEL), TCA migration messages 9 → 0 on 12.4 and
1 → 0 on 13.4, the Rector-generated upgrade wizard completed and verified on a
legacy content row.

## License

GPL-2.0-or-later, see [LICENSE](LICENSE).
