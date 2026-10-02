# AGENTS.md

Guidance for anybody changing this repository, people and coding agents alike.
Claude Code reads it through `.claude/CLAUDE.md` (a root `CLAUDE.md` would be
mistaken for plugin context by `claude plugin validate`).

## What this repository is

A Claude Code plugin, `fly-the-upgrade`, that flies a TYPO3 major upgrade in
three gated phases (pre-flight, flight, post-flight). It consists of:

| Part | Where | Role |
|---|---|---|
| Manifest and marketplace | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | The repository is its own single-plugin marketplace (`source: "./"`) |
| Skills | `skills/<name>/SKILL.md` | The procedures Claude follows: `upgrade`, `assess`, `preflight`, `instruments`, `rule-by-rule`, `flight`, `postflight`, `packages` |
| Agent | `agents/rule-reviewer.md` | Read-only review of one refactoring rule's diff |
| Hook | `hooks/hooks.json`, `hooks/guard_base_branch.py` | PreToolUse guard: nothing lands on the base branch while a flight is open |
| CLI | `bin/upgrade-pilot`, `lib/upgrade_pilot/*.py` | Tracking and tooling the skills drive. `bin/` is on `PATH` while the plugin is enabled |
| PHP helper | `lib/php/tca-migrations.php` | Headless TCA migration check. Copied into the target project at run time, because containers only mount the project |
| Data | `data/checklist.json`, `data/checklist-packages.json`, `data/templates/*.md` | The checklist of the talk, the checklist of the packages scope, templates for QRH, MEL, briefing |
| Tests | `tests/` | Unit tests for parsers, constraint matching and the guard |

CLI modules: `core` (state, runtime wrapper, git), `init` (detection),
`checklist` (items, gates, status), `instruments` (measure, scan, tca),
`contacts` (contact points vs tests), `platform` (versions, companion packages,
bump, snapshots), `schema` (schema tooling detection, dry run, converging apply),
`deps` (third-party packages that move, their notes by convention, new and opt-in wizards),
`docsite` (rendered manuals on docs.typo3.org, read as `llms.txt` asks),
`touchpoints` (where own code and configuration use or modify third-party packages, verified against the target, test coverage),
`catalog` (release status of a package for a core version: Packagist, composer, TER, development branches and their documentation),
`assess` (the pre-analysis: read-only steps, sizing, comparison, reports), `blockers` (go-live blockers and their resolution checks),
`patches` (cweagans 1.x/2.x and vaimo patch definitions, `git apply --check` against the target source),
`delivery` (deployment and CI files against the target),
`commit` (message rendering, recorded commands, composer fold, issues), `gitops`
(plumbing history rewrites), `context` (pre-collected information), `reports`
(developer and PM reports, en and de),
`changelog` (fetch, match), `rules` (Rector/Fractor campaigns), `render`
(flight log and report), `cli` (argument parsing).

## Hard rules

1. **Generic, always.** Nothing in this repository may be tailored to one
   project: no extension keys, table names, paths, hostnames, credentials or
   expected numbers of a particular project in code, skills, data or tests.
   Everything project-specific is detected by `init` or configured in the
   target project's `.upgrade-pilot/config.json`. Real projects appear only in
   the README's "Verified on" section, as a record of a test flight.
2. **Facts are fetched or measured, never assumed.** Version support, PHP
   ranges and compatible packages come from get.typo3.org and Packagist at run
   time. Behaviour changes come from the core changelog or a rule's
   `@changelog` reference. Skills must tell Claude to do the same, and must not
   hardcode facts that change between TYPO3 versions. If a skill states a fact
   about TYPO3 (a command, a class, an option), verify it on the versions it
   claims to cover.
3. **The CLI uses the Python standard library only** and must run on
   Python 3.9 or newer. Keep `from __future__ import annotations` in modules
   that use `X | None` or `list[str]` style hints. No backslashes inside
   f-string expressions (not allowed before Python 3.12).
4. **The PHP helper must work on every supported TYPO3 major** (currently
   12.4 and 13.4) and branch on available API (`class_exists`,
   `method_exists`), not on version numbers. Output goes to `STDOUT` via
   `fwrite`, because TYPO3 bootstraps with output buffering.
5. **Commands run in the target runtime go through `Flight.runtime_cmd()`.** It
   hands the inner command over as one quoted string: `ddev exec` joins
   separate arguments unquoted into `bash -c`, which breaks class names with
   backslashes.
6. **State belongs in the target project, never in the plugin directory.**
   `${CLAUDE_PLUGIN_ROOT}` changes on every plugin update.
7. **Never weaken safety.** The guard hook, the human gate default, the
   refusal to apply a rule on a dirty tree, and the rule that tests are never
   weakened to reach green are the point of the plugin, not obstacles.
8. **Skill frontmatter must be valid YAML.** A parse error makes Claude Code
   load the skill with empty metadata, silently. `claude plugin validate
   --strict` catches it.

## Checks before every commit

```bash
python3 -m unittest discover -s tests
claude plugin validate --strict .
claude plugin validate --strict ./.claude-plugin/plugin.json
```

The second command checks the marketplace, the third the plugin manifest and
every skill, agent and hook. CI runs the unit tests on Python 3.9 and 3.12 and
the validation (`.github/workflows/ci.yml`).

Changes to the CLI, the PHP helper or a skill's procedure need a real run as
well: load the plugin with `claude --plugin-dir .` in a TYPO3 project that is
under git, work on throwaway branches only, and restore the project afterwards
(`git switch <base> && git checkout -- . && git clean -fd`, reinstall
dependencies, restore the database snapshot). Never run a test flight on a
branch somebody else relies on.

Check that the skills are discovered:

```bash
claude -p --plugin-dir . "Without using any tool: list the skills and agents of the fly-the-upgrade plugin."
```

## Writing style

- Skills are instructions to Claude: imperative, specific, with the exact
  `upgrade-pilot` commands. Explain why when a step is easy to get wrong.
- British English. No em dash, and no semicolon as a sentence separator, in
  prose of any kind (docs, skills, commit messages, code comments).
- Keep the aviation vocabulary consistent with the talk: flight log, gate,
  QRH (expected failures and answers), MEL (accepted open items with reason and
  date), handoff, ferry equipment.
- Code follows the surrounding code: small functions, type hints, no new
  dependencies.

## Commits

TYPO3 Core commit message format:

- subject `[TASK]`, `[FEATURE]`, `[BUGFIX]`, `[DOCS]` (or `[!!!][TASK]` for a
  breaking change of the CLI or the state format), at most 52 characters,
  imperative
- empty line, body wrapped at 72 characters, explaining why
- one logical change per commit

## Releases

1. Update `CHANGELOG.md`.
2. Raise `version` in `.claude-plugin/plugin.json` (semantic versioning). Users
   only receive an update when the version changes.
3. Commit, then `claude plugin tag --push .` (creates and pushes the tag
   `fly-the-upgrade--v<version>`, after checking manifest and marketplace agree).
