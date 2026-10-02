---
name: flight
description: Phase 2 of a TYPO3 major upgrade (take-off and cruise). The fixed sequence on a dedicated branch, raising the core and tooling with composer, Rector and Fractor rule by rule against the target level, scanner and TCA check with target rules, working the red tests one at a time, schema, upgrade wizards, caches, and the "cleared to hand over" gate. Use after a GO at the pre-flight gate, or when the flight log says phase flight.
argument-hint: "[resume]"
---

# Phase 2: Take-Off & Cruise

The order is not a preference. Do these in sequence, or do several of them twice. Requires a recorded GO at the pre-flight gate (`upgrade-pilot status`). Measure after every step that changes code or dependencies, so the flight log shows the path from red to green.

## Before the roll

- `fl.freeze`: human (content, code and deploy freeze). `handoff` unless the user confirmed it.
- `fl.backup`: on ddev `upgrade-pilot snapshot take --name before-flight`. Production backup is human.

## The sequence

**1. Branch** (`fl.branch`): from the pre-flight branch, `git switch -c <flight branch from config.json>`. Everything after this is reversible, up to step 7.

**2. Platform** (`fl.platform`): `upgrade-pilot versions`. If the runtime PHP or `config.platform.php` does not satisfy the target core, stop: moving PHP belongs before departure, on the source version, as its own change.

**3. Packages** (`fl.packages`), one transaction:
- `upgrade-pilot bump show`, then `upgrade-pilot bump apply`. It raises `typo3/cms-*` to `^<target>` in the root and own extensions' `composer.json` through `composer require --no-update` commands (recorded for the commit), the `typo3` range in own `ext_emconf.php`, and `typo3/testing-framework` to a major that supports the target.
- `upgrade-pilot composer update -W`. Raise the constraints first, then `update -W`, never `composer require typo3/cms-core:^<target>` alone (it keeps the other core packages locked). Further composer changes in this transaction also go through `upgrade-pilot composer ...` (or `upgrade-pilot run -- jq ...`), never by editing the files.
- If it fails, read "Problem 1" completely. Typical causes, in the order they usually appear: an own path package still pinned to the old core, dev tooling pinning a shared dependency (rector, fractor, phpstan, php-parser: raise them in the same transaction), a third-party extension without a release for the target (update, patch, fork or replace: human decision, QRH). Never pass `--ignore-platform-reqs`, and never silence security blocking without telling the user.
- `fl.dependency-migrations`: the real resolution can differ from the probe. `upgrade-pilot deps list --from-lock <pre-flight branch>` compares the lock files, `upgrade-pilot deps docs` reads the notes for the versions actually installed (sources are cached from the pre-flight). Compare with the QRH, add what is new. The dependencies' breaking entries are worked like core ones below.
- Go-live blockers (`upgrade-pilot blockers list`): their development versions belong into the same transaction, through `upgrade-pilot composer config minimum-stability dev`, `upgrade-pilot composer config prefer-stable true` and `upgrade-pilot composer require --no-update '<package>:<branch>'` for each blocker (and only for those). Composer applies a declared branch alias, so siblings that require the aliased version resolve.
- `fl.patches`: composer applies the patches during the update and reports failures. Then `upgrade-pilot patches --label flight`: rebase a failing patch on the new version (its own commit), remove `contained` and `retired` patches from the patch definitions (in the plugin's syntax, through recorded commands or a reviewed edit of the patches file), and solve `out of range` ones.
- `fl.third-party-modifications`: once the packages are installed, `upgrade-pilot deps touchpoints --verify --label flight`. Work every `attention` entry with the package's changelog or upgrade guide open (the deps report has the migration text): adapt XCLASS and subclass signatures, move listeners to replacement events, re-base template copies onto the new original (diff old and new original, then re-apply only the project's own changes). Run it again until nothing is left in `attention`. A PHP fatal on `cache:flush` after the update is usually one of these.
- Check the new versions (`upgrade-pilot composer --no-record show "typo3/*"`), then commit composer files, lock and ext_emconf changes together as the **first commit of the flight branch**: `upgrade-pilot commit --tag TASK --subject "Raise TYPO3 to v<target>" --body-file <file> --step bump`. The "Used command(s):" block lists every recorded composer command. A composer-only follow-up later in the flight goes into that commit with `--into-composer-commit`.
- TYPO3 Console, if installed, moves with the core: `bump` raises it only when its constraint allows no release for the target, and warns when that crosses Console 8.0, where the `typo3cms` binary disappears (deployment scripts must call `typo3` instead). If the pre-flight decided to add Console but composer refused on the source version, add it now, in this transaction.
- If the test runner needs a core selector or other change for the new version, update `config.json -> tests` now.
- `upgrade-pilot measure --label "after bump"`. Red is expected: this is the real worklist. Keep this result, it is the reference for the rest of the flight.

**4. Rector** (`fl.rector`): `upgrade-pilot rules config --tool rector --level <target major>`, commit it (`upgrade-pilot commit --step flight-rector ...`), then campaign `flight-rector` with `fly-the-upgrade:rule-by-rule`. If the flight was opened with `--php-set`, the PHP level set follows as campaign `flight-rector-php` after the TYPO3 campaigns (see the rule-by-rule skill).

**5. Fractor** (`fl.fractor`): same with `--tool fractor`, campaign `flight-fractor`. TypoScript, Fluid, YAML, XLIFF: the half Rector never sees.

**6. Scan** (`fl.scan`): `upgrade-pilot scan --label flight` and `upgrade-pilot tca --label flight`. The scanner and the TCA migration now carry the target's rules, expect findings the pre-flight never showed.

**Working the failures** (between 6 and 7, until green):
- `upgrade-pilot measure --label "<what you fixed>"` after each fix. One failure at a time, in order, not in parallel.
- Classify each: **error** (removed API, cannot run: fix now) or **deprecation** of the target (fix now if cheap, else MEL with a date). Compare with the `baseline` measurement: broken *by* the upgrade, or broken already (`fl.two-kinds`).
- Look up the replacement in the changelog entry (core `Documentation/Changelog` in `vendor/typo3/cms-core`, or `upgrade-pilot changelog match`), never from memory.
- Scanner findings that tests do not reach still need a decision: fix, or MEL.
- Data: if a change alters how records are read (plugin registration, CType, FlexForm), an upgrade wizard must migrate production data, and test fixtures that model production data get the same migration. Fixture edits are allowed only as that migration, never to make an assertion pass.
- Own template or FlexForm overrides of core or third-party extensions (`contacts` and `deps touchpoints` list them): re-base them onto the new originals (`fl.overrides`).
- One logical fix per commit through `upgrade-pilot commit --step <slug>`. No unrelated refactoring (`fl.sterile`, `fl.one-tool-one-commit`).

**7. Schema** (`fl.schema`), the point of no return for a real database: on the local runtime only. `upgrade-pilot schema check` tells you what the project has (never assume a command from memory, `database:updateschema` is TYPO3 Console, not core).
- With TYPO3 Console: `upgrade-pilot schema plan --label flight` shows the safe statements, read them, then `upgrade-pilot schema apply --label flight`. It applies exactly the safe types and repeats plan and apply until the dry run is empty (at most 3 passes). A major step does not always converge in one pass: 12.4 to 13.4 needed two (181, then 266 statements) with either tool. If it does not converge, stop: the same would happen on every environment. The recorded passes are what the production deployment has to run, put them into `BRIEFING.md` and make sure the deployment repeats the update until its dry run is empty.
- Without it: `upgrade-pilot schema apply --label flight` runs the core's `extension:setup` twice (safe changes only, idempotent, no dry run, statements and convergence not verifiable). Say so in the briefing: the production run cannot be previewed or checked, and it has to run the setup twice as well.
- Never apply destructive types (drops, renames) in the flight. The old code needs those fields until the rollback window has passed. `apply` refuses them without `--allow-destructive`, which you only pass on an explicit, recorded human decision.

**8. Wizards** (`fl.wizards`): the wizards of the core and of every dependency (`deps docs` lists the new ones per package) must appear in the list and run. `typo3 cache:flush` first (a new wizard class is invisible to a cached container), then `typo3 upgrade:list --all` and `typo3 upgrade:run` (all, or one by one). Verify what each one did by querying the affected table before and after. If the local database has no records a wizard would touch, rehearse on production-shaped data: insert a record the way the source version stored it (for example the fixture row before its migration) into the **local** database only, run the wizard, query again. A generated wizard that throws or migrates nothing is a finding. A wizard `deps docs` marks as **opt-in** is excluded from the service container by its package, so the core never offers it: read the class documentation in the deps report, decide with the user whether the project needs it (usually: did the project use the data it migrates), and record that decision in `fl.wizards`. Registering it is a project change with its own commit.

**9. Caches** (`fl.caches`): `typo3 cache:flush`, then request the site's frontend (base URL from the site configuration or the runtime) and check status and content. The backend and the real smoke test are for a human.

## Gate: cleared to hand over

`upgrade-pilot measure --label "cleared"` must be green on every configured suite, without skipped or weakened tests. Then `upgrade-pilot gate flight show`.
- Human smoke tests, staging deployment and editor testing are `handoff` items: list precisely what to test (plugins, backend modules, anything on the MEL).
- Gate mode human: present the measurement table from the flight log, scanner and TCA trend, generated code you completed, MEL, and ask. Gate mode auto: GO only on green suites and every pilot item answered.

After the decision: `upgrade-pilot report --phase flight`, write `notes/flight-dev.en.md`, `notes/flight-pm.en.md` and `notes/flight-pm.de.md`, render again (see the upgrade skill).

Do not merge, rebase or push the flight branch into the base branch. That is the humans' call after the gate, and the plugin's hook blocks it anyway.
