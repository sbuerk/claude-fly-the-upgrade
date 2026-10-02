# Scenario: updating or checking selected packages

The core stays on its version. One or more third-party packages move: a
single extension, a list, or a family of split packages. This guide shows how
the pilot handles that, and what it does differently from a core upgrade. The
general rules (branches, commits, composer, issues, reports) are those of the
[process guide](PROCESS.md).

Typical questions this scenario answers:

- "Can we update `acme/shop` from 2.3 to 3.0, and what does it take?"
- "The maintainers work on the next major on `main`. What breaks for us if we
  go there now?"
- "Raise all `acme/shop-*` split packages to the next minor."

---

## Contents

1. [Two modes: update or check](#1-two-modes-update-or-check)
2. [Starting](#2-starting)
3. [Development targets: stability and aliases](#3-development-targets-stability-and-aliases)
4. [What the maintainers wrote](#4-what-the-maintainers-wrote)
5. [What your project built on top: touchpoints](#5-what-your-project-built-on-top-touchpoints)
6. [Pre-flight](#6-pre-flight)
7. [Flight](#7-flight)
8. [Post-flight](#8-post-flight)
9. [Reports](#9-reports)
10. [Limits](#10-limits)

---

## 1. Two modes: update or check

| Mode | What happens | Where it ends |
|---|---|---|
| **update** | pre-flight, flight and post-flight, with gates, like a core upgrade | Debriefed, branches ready for review |
| **check** (`--check-only`) | the pre-flight only. Nothing in the project changes, apart from instrument tests if you want them | Go / No-Go, then the flight is landed |

A check is an assessment: which versions resolve, what the maintainers
documented, which places of your project are affected and how. Its reports say
that nothing was changed. The update itself is a new flight, started from them.

Nothing in the plugin is tailored to a package. Everything is derived from the
packages' own metadata and documentation and from your project's code, so it
works for any composer package, with extra depth for TYPO3 extensions.

## 2. Starting

Ask Claude, for example: *"Check what updating acme/shop-* to dev-main would
take"*. The `upgrade` skill asks the usual questions (runtime, commit style,
issues, gates), and for this scenario:

- **Packages**: names or globs. Globs are matched against `composer.lock`, so
  `acme/shop-*` catches every installed split package.
- **Target**: a release (`^3.0`, `3.0.2`) or a development branch (`dev-main`,
  `2.x-dev`).
- **Development stability**, for a development target (see below).
- **Mode**: update or check.

The resulting command:

```bash
upgrade-pilot init --scope packages --package 'acme/shop-*' --to dev-main \
  --dev-stability minimum-stability [--check-only] [--label shop-3.0] ...
```

`init` prints the matched packages with their installed versions, the
branches (`<prefix>/preflight-<label>` and `<prefix>/<label>`), and whether the
target is a development version. The checklist of this scope is
`data/checklist-packages.json`: the same three phases, with items about the
packages instead of the core.

`init --force` replaces a flight. The old state moves to
`.upgrade-pilot/archive/<time>-<title>/`, so reports of two flights never mix.
The download cache stays.

## 3. Development targets: stability and aliases

Composer only installs development versions of dependencies when the root
package allows it. `--dev-stability minimum-stability` records two commands for
the first commit of the flight branch:

```bash
composer config minimum-stability dev
composer config prefer-stable true
```

With `prefer-stable`, only the packages that have no stable version in the
requested range become development versions. `--dev-stability none` leaves it
to you. Either way it is temporary: the MEL gets a row with the date or event
that ends it, usually the release.

**Branch aliases.** A development branch usually declares which version it
stands for (`"branch-alias": {"dev-main": "3.0.x-dev"}`). Other packages of the
same family then require it as `~3.0.0@dev`, and composer matches that through
the alias. `upgrade-pilot versions` reads the declared aliases and warns when
one is declared under another name than the version composer uses. Composer
then ignores it, and every constraint on the aliased version fails.
That is a packaging issue to report to the maintainers.

If the probe fails for that reason, the CLI explains it and offers the way
around: an inline alias in the root `composer.json`,

```bash
upgrade-pilot bump probe --alias acme/shop-base=2.4.x-dev
```

which becomes `composer require --no-update 'acme/shop-base:2.x-dev as 2.4.x-dev'`.
It is remembered for `bump apply` and appears in every report as a temporary
workaround, to be removed with the release. Decide it with the team, it is not
a fix.

## 4. What the maintainers wrote

`upgrade-pilot deps docs` reads, for each package, what changed between the
installed and the target version. The core-scope conventions apply (see the
README section *Third-party changelogs and upgrade notes*), plus:

- **Development targets**: the target is read at the commit composer resolved,
  and ranges are compared through the branch alias (`dev-main` with
  `3.0.x-dev` counts as a 3.0 release, so the step from 2.3 is a major).
- **The rendered manual on docs.typo3.org** for TYPO3 extensions. It follows
  the host's rules for machines (`llms.txt`): pages are found through
  `toc.json` or `objects.inv.json` and read as Markdown where it is published,
  with the reStructuredText source as a flagged fallback. Only pages that are
  new against the manual of the installed version are taken, upgrade and
  migration guides first. Changelog pages are left out when the repository's
  changelog was read already, they hold the same entries. Manual versions are
  tried by branch name and by alias (`main`, `3.0`). `--no-rendered` skips it.
- **Opt-in wizards**: an upgrade wizard class that its package excludes from
  the service container (`#[Exclude]`) is never offered by the core. The
  report marks it and quotes its class documentation, which usually says when
  a project has to register it. That is a decision per project.

A breaking entry on a minor or a development branch is still breaking. Read
every report in `.upgrade-pilot/deps/` completely.

## 5. What your project built on top: touchpoints

Projects rarely use a package as it comes. Sitepackages and local path
extensions replace its classes, listen to its events, copy its templates and
override its labels. Every one of these places can break when the package
moves, and none of them shows up in the package's changelog.

`upgrade-pilot deps touchpoints` finds them. It derives what to look for from
each package's declarations (PSR-4 namespaces, extension key, TCA tables,
plugin signatures, template and label files) and searches your own extensions,
sitepackages, local path packages, `config/` and the root `composer.json`.
Namespaces match case-insensitively, as PHP does.

| Kind | Found by | Verified against the target (`--verify`) |
|---|---|---|
| `xclass` | `$GLOBALS['TYPO3_CONF_VARS']['SYS']['Objects'][<package class>]` | the replacement class: overridden methods still exist, signatures compatible, parent not final |
| `subclass` | `extends` of a package class | same checks as for an XCLASS |
| `service-override` | package classes in own `Services.yaml` with `decorates:`, `class:` or `alias:` | classes still exist |
| `listener` | own listeners of package events (`#[AsEventListener]` or `event.listener` tags) | event classes still exist |
| `hook` | `SC_OPTIONS` or `EXTCONF` entries naming the extension key or its classes | by hand, against the changelog |
| `tca-override` | `Configuration/TCA/Overrides/<package table>.php` | by hand |
| `template-copy` | own copies of the package's templates, partials, layouts | the original changed between both versions, or the copy already equals the new original |
| `template-override` | TypoScript template, partial and layout paths of the package's plugins | refers to the template-copy verdicts |
| `language-override` | `locallangXMLOverride` for the package's label files | overridden keys still exist |
| `viewhelper-usage` | the package's ViewHelper namespace in own templates | the used ViewHelpers still exist |
| `persistence-mapping` | `Configuration/Extbase/Persistence/*.php` naming package classes | classes still exist |
| `site-config` | YAML in `config/` naming the package's plugins, extension name, tables or `EXT:` paths | by hand |
| `typoscript` | TypoScript and TSconfig referring to `tx_<key>` or `EXT:<key>/` | by hand |
| `php-usage` | package classes used in own code | classes still exist |
| `patch` | composer patches for the package, read the way the installed plugin (cweagans 1.x or 2.x, vaimo) reads them | `git apply --check` against the target source: applies, fails, contained, retired, out of range ([process guide](PROCESS.md#4-pre-analysis-the-assessment)) |
| `fixture` | package tables or plugin signatures in own CSV and XML fixtures | by hand |

Each verified entry ends as **ok**, **manual** (a person has to look) or
**attention** (the target changes or removes what the project relies on). The
details are in `.upgrade-pilot/touchpoints.json`. Verification needs the
target's source, so `deps docs` runs first.

Touchpoints are part of the core scope as well: a core upgrade moves
third-party packages too, and the same command covers them there.

`--coverage` adds the test files that mention each touchpoint. A touchpoint no
test mentions is surely untested. One that is mentioned still needs a look at
the test, the `instruments` skill has a test pattern per kind.

## 6. Pre-flight

In order, all without changing the packages:

| Step | Command | Result |
|---|---|---|
| Pre-analysis | `assess` | release status of the packages against the installed core, security, patches, deployment, the size of the work, reports for developers and project managers ([process guide](PROCESS.md#4-pre-analysis-the-assessment)) |
| Release decision | `blockers add`, or a hold | a development target the user keeps is a go-live blocker. If a release exists, the assessment says so |
| Inventory | `init` output, `deps list` | what is in scope, what moves along, abandoned packages |
| Compatibility | `versions` | target requirements for core and PHP, declared branch aliases |
| Probe | `bump probe [--alias ...]` | does the update resolve, and with what |
| Documentation | `deps docs` | one report per package in `.upgrade-pilot/deps/` |
| Touchpoints | `deps touchpoints --verify --label preflight` | every affected place, with a verdict |
| Work list | QRH | a row per breaking entry and per `attention` touchpoint |
| Tests | `fly-the-upgrade:instruments`, `deps touchpoints --coverage` | tests that execute the touchpoints |
| Patches, deployment | `patches`, `delivery --label preflight` | patches that need work, scripts that break |
| Baseline | `measure --label baseline` | the reference |

The tests deserve attention. A project's suite rarely renders a third-party
plugin, so it stays green while the update breaks the site. Tests that render
the package's plugins with the project's configuration, run own listeners and
use own overrides are what turns a touchpoint into a measurement.

In check mode, the GO of the pre-flight gate lands the flight. Write the
summaries, run `report --phase all`, done.

## 7. Flight

1. Branch, backup.
2. `bump apply`, then `composer update <packages> -W` as printed. The first
   commit of the branch, with the commands in its "Used command(s):" block.
3. Migration steps from the QRH, one logical change per commit.
4. `deps touchpoints --verify --label flight`, until nothing is in
   `attention`. `commit --path` keeps several pending changes in separate
   commits.
5. Template copies re-based: diff the old and the new original, re-apply only
   your own changes. A copy without own changes is best removed.
6. Configuration: site sets and settings, TypoScript constants, TCA overrides,
   extension configuration.
7. Schema, 8. wizards (opt-in ones decided), 9. caches, as in a core upgrade.

`measure` after every fix. The gate needs green suites.

## 8. Post-flight

- `deps touchpoints --verify --label postflight` on the final state.
- Deprecations the project still uses: the next update's work list.
- Development stability and inline aliases: reverted once a release exists,
  constraints pinned to it, then `blockers resolve`. Until then `handoff` with
  a date, and the result is not releasable.
- `delivery --label postflight`: deployment and CI against the updated instance.
- Frontend, backend, logs and deprecation log as in a core upgrade.

## 9. Reports

The same reports as a core upgrade (`report --phase ...`), titled with the
packages and the versions. In addition:

- the assessment reports (`reports/assessment-*`) before anything changed
- a section on touchpoints: how many, how many need work, per run
- go-live blockers, and "not releasable" while one is open
- inline aliases as a temporary workaround under risks
- in check mode, only pre-flight and final reports, saying that nothing
  was changed

## 10. Limits

- Touchpoints are found statically. Class names built from strings, services
  replaced through compiler passes and configuration generated at run time are
  invisible. The tests are the answer to that.
- Signature checks compare declarations, not behaviour. A method whose meaning
  changed without a new signature is only found by the changelog and the tests.
- Declared branch aliases are read from Packagist. For packages from other
  repositories, the warning is missing, the probe still fails in the same way.
- The rendered manual is only read for TYPO3 extensions that publish one on
  docs.typo3.org.
