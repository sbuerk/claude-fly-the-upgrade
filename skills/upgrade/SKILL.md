---
name: upgrade
description: Fly a TYPO3 major upgrade (for example 12.4 to 13.4, or 13.4 to 14.x) of a composer project or extension in three gated phases, pre-flight, flight and post-flight, with a tracked flight log, instrument tests for core contact points, Rector/Fractor applied one rule per commit, commits in the project's style with issue references, and reports for developers and project managers. Also flies updates of selected third-party packages without a core upgrade, or only checks them (see the packages skill). Use when the user wants to plan, start, resume or check the status of a TYPO3 core upgrade or a package update.
when_to_use: >-
  Requests like upgrade this project to TYPO3 13, prepare the v14 upgrade,
  where are we with the upgrade, continue the upgrade, run the upgrade checklist.
argument-hint: "[target version, e.g. 13.4 | status | resume]"
---

# Fly the Upgrade: the pilot

An upgrade is flown, not hoped for. Three phases, each ending in a gate:

| Phase | Skill | Ends with |
|---|---|---|
| 1 Pre-flight: nothing touches the target version | `fly-the-upgrade:preflight` (+ `fly-the-upgrade:instruments`) | Go / No-Go |
| 2 Flight: the fixed sequence, on the target version | `fly-the-upgrade:flight` | Cleared to hand over |
| 3 Post-flight: sweep again, remove ferry equipment, debrief | `fly-the-upgrade:postflight` | Debriefed |

A flight has a **scope**: `core` (the default, the table above) or `packages`, selected third-party packages on an unchanged core, flown in the same phases or only checked. For the packages scope, `fly-the-upgrade:packages` says what differs.

Rector and Fractor are always run through `fly-the-upgrade:rule-by-rule`: one rule, one review, one measurement, one commit. The full process with every command is in the plugin's `docs/PROCESS.md` (`${CLAUDE_PLUGIN_ROOT}/docs/PROCESS.md`).

## The tracking tool

Everything is recorded by the `upgrade-pilot` CLI that ships with this plugin (on `PATH` while the plugin is enabled, otherwise `${CLAUDE_PLUGIN_ROOT}/bin/upgrade-pilot`). It needs Python 3.9+ on the host. State lives in `.upgrade-pilot/` at the project root, which `init` adds to `.git/info/exclude`, so it survives branch switches and never ends up in a commit.

| File | What |
|---|---|
| `config.json` | how to run things: runtime, test commands, own extensions, branches, gate mode, commit policy |
| `flightlog.json` | what happened: checklist answers, gates, measurements, scans, campaigns, commits, issues, context |
| `FLIGHT-LOG.md` | rendered from `flightlog.json` after every change, for humans |
| `QRH.md`, `MEL.md`, `BRIEFING.md`, `DEBRIEF.md` | written by you |
| `ISSUES.md` | issue placeholders or per-step issues, with the commits that use them |
| `context/` | digests of pre-collected information |
| `reports/` | developer and PM reports per gate and at the end |
| `notes/` | the prose summaries you write for those reports |
| `logs/` | raw output of every tool run, cite these as evidence |

Never edit `flightlog.json` or `FLIGHT-LOG.md` by hand. Use the CLI. Run `upgrade-pilot <command> --help` when unsure.

## Starting a new flight: ask first

`upgrade-pilot status` says whether a flight exists. For a new one, the working tree must be clean, on the branch the upgrade starts from. Then:

1. `upgrade-pilot init --detect` prints what the project offers: ddev, an `.envrc` for direnv (in the project or one folder up: installed, allowed, php and composer usable inside it), local PHP and composer, the git host, and how existing commit messages look (TYPO3 tags, `PRJ-123:` keys in subjects, footers).
2. Ask the user with `AskUserQuestion`, pre-selecting what the detection suggests. Skip a question only if the user already answered it.
   - **Scope**: TYPO3 core upgrade, update of selected packages, or only a check of selected packages. For the two package variants, continue with the questions of `fly-the-upgrade:packages` (packages or globs, target version or branch, development stability) and its init command.
   - **Runtime**, when more than one is possible: ddev, direnv or local PHP (or a custom exec template). If an `.envrc` exists but is not allowed, say so: the user reviews it and runs `direnv allow` themselves. Never run `direnv allow` yourself, an `.envrc` executes code.
   - **Commit style**: TYPO3 Core style (`[TAG] Subject`, 52 characters, body at 72, no Resolves/Releases footers, issue references as `Related:` lines), YouTrack style (`[TAG] PRJ-123: Subject` with `Related:` lines), or a custom subject template (`{tag}`, `{ref}`, `{subject}`). If the project or the user's instructions already define a style, propose exactly that.
   - **Issue references**: none, one reference for all commits, a parent issue with one issue per step (only if this session can create issues in that tracker, for example a YouTrack MCP server, `gh` or `glab`), or placeholders (`{ISSUE-01}`) collected in `ISSUES.md` for a human to create, which `issues apply` later replaces in the commits. Ask for the reference or parent and the project key.
   - **Gates**: `human` (default, you stop and ask at every gate) or `auto` (only for an unattended run the user asked for).
   - **Extras**: whether to run the Rector PHP level set as an additional campaign (`--php-set`), and whether pre-collected information exists: issues with findings, notes from a previous attempt, customer requirements (`--context`, repeatable).
   Pushing stays blocked for the whole flight unless the user explicitly wants it (`--allow-push`).
3. `upgrade-pilot init --target <major.minor> --runtime <...> --gates <...> --commit-style <...> [--commit-template "..."] [--tracker <name>] [--project-key <KEY>] --issue-mode <none|single|per-step|placeholder> [--issue <REF>] [--php-set] [--context <REF> ...]`
4. Read what `init` prints. Correct `.upgrade-pilot/config.json` if the runtime, extensions or test commands are wrong (a wrong test command poisons every measurement). Set `"confirmed": true` on a suite once it ran as expected.
5. Read every context reference before anything else (`upgrade-pilot context list`): issues through whatever this session has (a YouTrack MCP server or skill, `gh issue view`, `glab issue view`), URLs if they are readable, files are copied already. Write a short digest per reference (what it says, what it means for the upgrade) and store it: `upgrade-pilot context add <REF> --title "..." --file <digest.md>`. If a reference cannot be read, tell the user and ask for the content.

Resuming: `upgrade-pilot status -v`, then continue with the phase skill it names. The first open item of that phase is the next thing to do.

## Branch model and commits

- Base branch (recorded at init): never committed to, merged into or pushed to while the flight is open. Integrating the upgrade is a human decision after the gates.
- Pre-flight branch `<prefix>/preflight-<source>`, from the base branch: instrument tests and clean-ups that still run on the **source** version. It could ship before the upgrade.
- Flight branch `<prefix>/<target>`, from the pre-flight branch: the bump and everything after it.
- **Nothing is pushed.** The plugin's hook blocks every `git push` and pull or merge request creation while a flight is open, unless the flight was opened with `--allow-push`.
- **Every commit goes through the CLI**: `upgrade-pilot commit --tag TASK --subject "..." --body-file <file> --step <slug>` for your own changes, `upgrade-pilot rules commit ...` for a Rector or Fractor rule. The CLI renders the configured style, adds the issue reference for the step, `Related:` lines, and the commands behind composer changes. Write subject and body the way the project wants them (no attribution lines unless the project asks for them). `--dry-run` shows the message first.
- **Small logical units.** One step per concern (a test area, a hand fix, the bump, one rule). Steps name issues in per-step and placeholder mode, so reuse a step slug for commits that belong together.
- **Composer files change only through commands**: `upgrade-pilot composer <args>` (runs composer in the configured runtime) or `upgrade-pilot run -- jq ...`. Both record the command, and the next commit lists them in a "Used command(s):" block. A commit with changed composer files but no recorded command is refused. Never edit `composer.json` or `composer.lock` by hand.
- **Composer changes early.** Aim for the composer change to be the first commit of a branch. A later composer-only change can be folded into it with `upgrade-pilot commit ... --into-composer-commit`. The CLI rewrites the local branch through git plumbing and falls back to a normal commit when that is not safe (later commits touching composer files, the commit shared with another branch). It is a preference, not a rule.

## Non-negotiables

- **Measure, never estimate.** Every claim about tests, scanner findings or TCA migrations comes from an `upgrade-pilot measure|scan|tca` run recorded in the log. Quote the recorded numbers.
- **Order is not a preference.** Rector and Fractor for the target run *after* the packages are raised. Wizards after the schema. The schema after the code.
- **One tool, one commit. One rule, one commit.** No unrelated refactoring on these branches (sterile cockpit).
- **Generated code is read before it is trusted.** Anything a tool scaffolds (upgrade wizards, TODO markers) is completed or reported, never committed blind.
- **"No" is a valid answer.** `upgrade-pilot item <id> no --note "<reason>"` is an accepted risk. An open item is a forgotten one.
- **Tests are not weakened to get green.** Never delete, skip or loosen a test or `failOnDeprecation` to pass a gate. Fixtures that represent data may be migrated the way production data is migrated, and that must be said in the commit.
- **Do not guess facts.** Versions, PHP ranges and support dates come from `upgrade-pilot versions`. Behaviour changes come from changelog entries (`upgrade-pilot changelog`, `upgrade-pilot deps docs`) or the tool's `@changelog` reference.
- **Human-only items are never faked.** Backups of production, freezes, editor smoke tests and staging deployments are `handoff` with a note saying what the human has to do.

## Reports at every gate, and at the end

At each gate decision (and after `postflight` for the final one): `upgrade-pilot report --phase <preflight|flight|postflight|final>`. It writes three variants to `.upgrade-pilot/reports/`: `<phase>-dev.en.md` (technical record), `<phase>-pm.en.md` and `<phase>-pm.de.md` (project managers and customers). The facts come from the flight log. You write the summaries it embeds:

- `notes/<phase>-dev.en.md`: what happened technically, surprises, what the next phase must watch.
- `notes/<phase>-pm.en.md` and `notes/<phase>-pm.de.md`: five to ten sentences for non-developers. What was done, whether the plan holds, what it costs or risks, what they have to decide or do. No jargon without a short explanation. The German text is written in German, not translated word for word, with correct grammar and the formal "Sie".

Re-run `report --phase <phase>` after writing the notes. Handoff notes appear in the reports as written, so write them clearly enough for a project manager to act on.

After each phase, and whenever you stop, tell the user: phase and gate state, the measurement table (stage, result, exit), what changed since the last report, what waits for a human, and where the reports are.
