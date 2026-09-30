---
name: instruments
description: Write the missing tests for a TYPO3 project's or extension's critical core contact points (plugins, controllers, services with core API, hooks, event listeners, middlewares, commands, TCA, TypoScript) before an upgrade, so the new core reports breakage as red tests instead of production incidents. Use during upgrade pre-flight, or whenever `upgrade-pilot contacts` shows gaps.
argument-hint: "[extension key or gap to cover]"
---

# Instruments: cover the core contact points

Every other upgrade tool *reads* code. Tests *run* it, so the core can tell you, while you are still on the source version, what the target will take away: with `failOnDeprecation` every deprecation a test triggers becomes a finding. And after the bump, removed API becomes an error with file and line instead of a blank page three weeks later. Coverage here means coverage of **contact points with the core**, not a percentage.

## 1. Find the gaps

`upgrade-pilot contacts` prints, per own extension, registration points (plugins with their registration type, TCA tables, TypoScript, middlewares, hooks, XCLASSes, template overrides) and classes with their core references, then a list of **gaps, most critical first**. The full data is in `.upgrade-pilot/contacts.json`. It is a heuristic: read the code behind each gap before deciding.

For each gap decide one of:
- **cover it** (default for plugins, controllers, middlewares, hooks, listeners, commands, services and repositories that call core API, TCA tables, TypoScript that the site depends on),
- **accept it**: note why in `MEL.md` (for example a backend module that needs a browser, covered by the human smoke test),
- **flag it**: a class that is not registered anywhere may be dead code. Do not delete it in pre-flight (sterile cockpit), report it to the user and in `BRIEFING.md`. If it stays, it still needs a test, or the upgrade can break it unnoticed.

## 2. Before writing, learn the project's test setup

- Where do existing tests live, which namespace, which base classes, which PHPUnit config picks them up? New tests go where the configured suites (`config.json -> tests`) already run them.
- Which `typo3/testing-framework` version is installed? Read its `FunctionalTestCase` in `vendor/` for the helpers that really exist (`importCSVDataSet`, `setUpFrontendRootPage`, `executeFrontendSubRequest`, `setUpBackendUser`, ...). Do not assume helpers from other versions or from the Core's own test suite.
- Keep `failOnDeprecation` (and the other `failOn*` flags) exactly as they are.

## 3. What a good instrument test looks like, per contact point

| Contact point | Test | Why |
|---|---|---|
| Plugin / content element | Functional **frontend request**: fixture page + `tt_content` row exactly as production stores it (same `CType` / `list_type`), load the extension's TypoScript, `executeFrontendSubRequest`, assert rendered data from fixtures | covers registration, dispatch, controller, services, database and templates in one run. Registration changes (e.g. `list_type` to `CType`) only show up here |
| Controller action | Through the plugin rendering above, not by instantiating the controller | the dispatch is part of what breaks |
| Service / repository using core API | Functional test with CSV fixtures, call the public method, assert the result | executes the query builder, context, page repository... |
| Hook / event listener | Functional: dispatch the real event or run the core code path that calls the hook, assert the effect | hook signatures and events change between majors |
| Middleware | Frontend request that passes through it, assert its effect | |
| Command | Functional with Symfony `CommandTester` on the container service | |
| TCA table | Functional test that boots with the extension and asserts the table and key columns exist. Boot runs the automatic TCA migration, so outdated TCA surfaces as a deprecation | there is no CLI check, this and `upgrade-pilot tca` are the only instruments |
| TypoScript | Loaded by the frontend rendering test (`setUpFrontendRootPage` with the extension's files) | Fractor-only territory otherwise |
| Pure logic without core API | Unit test | cheap, but it tells you nothing about the core |

Rules:
- **Do not mock the core.** A mocked removed method still "works". Mock only what is outside TYPO3 (HTTP clients, mail transport).
- Assert observable behaviour (rendered output, rows written, return values), not internals.
- Fixtures model production data, including legacy shapes. That is what makes data migrations visible later.
- A test must pass its assertions on the **source** version. Deprecations it reports are findings, keep them. If it reveals a bug that exists already, do not fix it in the same commit, record it as "broken already" in `MEL.md`.

## 4. Commit and measure

- One commit per contact area through `upgrade-pilot commit --step instruments --tag TASK --subject "Cover the <plugin> plugin with a frontend test" --body-file <file>`.
- After each commit: `upgrade-pilot measure --label "instruments: <what>"` and note how the number of reported deprecations changed. More findings is the goal of this step, not a regression.
- When done: `upgrade-pilot contacts --label after-instruments`, then answer `pf.tests-exist` and `pf.coverage` (note the accepted gaps), and let the pre-flight record the `baseline`.
