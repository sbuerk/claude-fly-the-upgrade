---
name: assess
description: Pre-analysis of a TYPO3 upgrade or package update before anything changes. Checks whether every third-party package has a released version for the target (Packagist, other composer repositories, the TER, development branches and their documentation), probes the target graph, runs composer audit on the installed and the target graph, verifies composer patches (cweagans and vaimo) and the places where the project modifies third-party packages, checks deployment and CI scripts, counts the size of the work, and writes a report for developers and project managers. Leads the user through the decisions it finds (development version as go-live blocker, or hold) and re-checks later. Use right after `upgrade-pilot init`, when the user asks whether an upgrade is possible yet, or to re-check a held upgrade.
when_to_use: >-
  Requests like can we upgrade to TYPO3 14 yet, what blocks the upgrade, make a
  pre-analysis, check again whether the extensions have releases now, is the
  held upgrade unblocked.
argument-hint: "[re-check | --quick]"
---

# Pre-analysis: know before you change anything

The assessment is the first thing after `upgrade-pilot init`, before any branch, before any commit. It decides whether the flight can start, and it is what the team and the customer decide on. Read `fly-the-upgrade:upgrade` first if you have not in this session.

## 1. Run it

```bash
upgrade-pilot assess            # complete: a few minutes, reads dependency sources
upgrade-pilot assess --quick    # without dependency documentation and the core changelog
```

Every step is read-only, the composer probe restores `composer.json` and the lock file byte for byte. Each step's output is kept under `.upgrade-pilot/logs/assess-*`. A step that fails is a finding: read its log, do not rerun blindly.

What it checks, so you can explain it:
- **Release status** of every third-party TYPO3 extension and every direct requirement: `released`, `released-ter`, `dev-only`, `claimed`, `none`, `independent`. Only stable releases count as released. The TER is asked by extension key. Development lines are the main branches, version branches and anything with a branch alias, feature branches only when nothing else exists.
- **Security**: `composer audit` of the installed graph and, when the probe resolves, of the target graph, plus abandoned packages.
- **Probe, dependency documentation, touchpoints with test coverage, core changelog, patches, deployment and CI.**

## 2. Read the report, then decide with the user

Read `.upgrade-pilot/reports/assessment-dev.en.md` completely. For `claimed` packages, read the quoted documentation: it can mean a supported branch, a plan, or a version that is not public (an early access program, a paid edition). Say which.

Then ask with `AskUserQuestion`, one question per package that needs a decision (all of them in one call, up to four per call):

| Status | Options to offer |
|---|---|
| `dev-only` | **Use `<branch>` meanwhile as a go-live blocker** (recommended when the branch's own requirements name the target), or **hold the upgrade until a release** |
| `claimed` | **Verify and use the branch as a go-live blocker**, **hold**, or **replace / drop** |
| `none` | **Replace**, **drop**, **fork / take over**, or **hold** |
| `released-ter` | **Ask the maintainers** for a composer release, or **hold** |

Record each answer:
- Go-live blocker: `upgrade-pilot blockers add --package <name> --use <branch> --reason "<why, as a clause after 'because'>" --waits-for "<the release it waits for>"`. Packages that come along with it (a sibling the branch requires) get their own blocker.
- Hold: `upgrade-pilot gate preflight nogo --note "Hold: <package> <reason>"` after answering `pf.release-status` with `no` and the reason. Stop the flight there and tell the user how to re-check (below).
- Replace, drop, fork: these are project changes. Put them into the QRH with the user's decision, they happen on the pre-flight branch (on the current version) or in the flight transaction.

Answer `pf.assessment`, `pf.release-status`, `pf.security`, `pf.patches` and `pf.delivery` with what the report shows.

## 3. Summaries and reports

Write the summaries, then render again:
- `notes/assessment-dev.en.md`: the technical picture in a few sentences, what blocks, what needs care.
- `notes/assessment-pm.en.md`, `notes/assessment-pm.de.md`: five to ten plain sentences: can the upgrade start, what has to be decided, what it means for the go-live, the size of the work in the counted numbers of the report. No hours or days: the plugin counts, it never estimates. The German text in real German with the formal "Sie".

```bash
upgrade-pilot assess --render
```

Tell the user where the three reports are, the decisions taken, the go-live blockers, and whether the flight continues or is on hold.

## 4. Re-check

Every run compares itself with the previous assessment (or `--since <file>` from `.upgrade-pilot/assessments/`). Run `upgrade-pilot assess` again:
- before continuing a held upgrade: a package that is `released` now ends the hold for it
- during the flight and after landing: `go-live blockers that can be resolved now` names packages with a release. Then require the release through `upgrade-pilot composer require --no-update '<package>:^<version>'` and `upgrade-pilot composer update <package> -W`, commit, measure every suite, run `deps touchpoints --verify --package <package>`, and `upgrade-pilot blockers resolve --package <package>`. `blockers check` says what is still missing.

Never resolve a blocker by hand-editing the flight log, and never drop one to make a report look better: `drop` is for a package that was removed or replaced, with that as the note.
