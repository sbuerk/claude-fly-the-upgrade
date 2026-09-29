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
- `upgrade-pilot bump show`, then `upgrade-pilot bump apply`. It raises `typo3/cms-*` to `^<target>` in the root and own extensions' `composer.json`, the `typo3` range in own `ext_emconf.php`, and `typo3/testing-framework` to a major that supports the target.
- `<composer from config.json> update -W`. Edit constraints then `update -W`, never `composer require typo3/cms-core:^<target>` (it keeps the other core packages locked).
- If it fails, read "Problem 1" completely. Typical causes, in the order they usually appear: an own path package still pinned to the old core, dev tooling pinning a shared dependency (rector, fractor, phpstan, php-parser: raise them in the same transaction), a third-party extension without a release for the target (update, patch, fork or replace: human decision, QRH). Never pass `--ignore-platform-reqs`, and never silence security blocking without telling the user.
- Check the new versions (`<composer> show "typo3/*"`), commit composer.json(s), lock and ext_emconf changes together (for example `[TASK] Raise TYPO3 to v<target>`).
- If the test runner needs a core selector or other change for the new version, update `config.json -> tests` now.
- `upgrade-pilot measure --label "after bump"`. Red is expected: this is the real worklist. Keep this result, it is the reference for the rest of the flight.

**4. Rector** (`fl.rector`): `upgrade-pilot rules config --tool rector --level <target major>`, commit, then campaign `flight-rector` with `fly-the-upgrade:rule-by-rule`.

**5. Fractor** (`fl.fractor`): same with `--tool fractor`, campaign `flight-fractor`. TypoScript, Fluid, YAML, XLIFF: the half Rector never sees.

**6. Scan** (`fl.scan`): `upgrade-pilot scan --label flight` and `upgrade-pilot tca --label flight`. The scanner and the TCA migration now carry the target's rules, expect findings the pre-flight never showed.

**Working the failures** (between 6 and 7, until green):
- `upgrade-pilot measure --label "<what you fixed>"` after each fix. One failure at a time, in order, not in parallel.
- Classify each: **error** (removed API, cannot run: fix now) or **deprecation** of the target (fix now if cheap, else MEL with a date). Compare with the `baseline` measurement: broken *by* the upgrade, or broken already (`fl.two-kinds`).
- Look up the replacement in the changelog entry (core `Documentation/Changelog` in `vendor/typo3/cms-core`, or `upgrade-pilot changelog match`), never from memory.
- Scanner findings that tests do not reach still need a decision: fix, or MEL.
- Data: if a change alters how records are read (plugin registration, CType, FlexForm), an upgrade wizard must migrate production data, and test fixtures that model production data get the same migration. Fixture edits are allowed only as that migration, never to make an assertion pass.
- Own template or FlexForm overrides of core or third-party extensions (`contacts` lists `template-override`): re-base them onto the new originals (`fl.overrides`).
- One logical fix per commit, message per project rules. No unrelated refactoring (`fl.sterile`, `fl.one-tool-one-commit`).

**7. Schema** (`fl.schema`), the point of no return for a real database: on the local runtime only. Find the command the installed version really provides (`<runtime> vendor/bin/typo3 list`), never from memory: the core ships `extension:setup` (it applies the schema of all extensions), a schema command such as `database:updateschema` only exists if the project installs a console package that provides it. Run it, record the output as evidence.

**8. Wizards** (`fl.wizards`): `typo3 cache:flush` first (a new wizard class is invisible to a cached container), then `typo3 upgrade:list --all` and `typo3 upgrade:run` (all, or one by one). Verify what each one did by querying the affected table before and after. If the local database has no records a wizard would touch, rehearse on production-shaped data: insert a record the way the source version stored it (for example the fixture row before its migration) into the **local** database only, run the wizard, query again. A generated wizard that throws or migrates nothing is a finding.

**9. Caches** (`fl.caches`): `typo3 cache:flush`, then request the site's frontend (base URL from the site configuration or the runtime) and check status and content. The backend and the real smoke test are for a human.

## Gate: cleared to hand over

`upgrade-pilot measure --label "cleared"` must be green on every configured suite, without skipped or weakened tests. Then `upgrade-pilot gate flight show`.
- Human smoke tests, staging deployment and editor testing are `handoff` items: list precisely what to test (plugins, backend modules, anything on the MEL).
- Gate mode human: present the measurement table from the flight log, scanner and TCA trend, generated code you completed, MEL, and ask. Gate mode auto: GO only on green suites and every pilot item answered.

Do not merge, rebase or push the flight branch into the base branch. That is the humans' call after the gate, and the plugin's hook blocks it anyway.
