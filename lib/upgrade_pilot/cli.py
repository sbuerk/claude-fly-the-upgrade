"""upgrade-pilot: the tracking and tooling CLI behind the fly-the-upgrade skills."""

from __future__ import annotations

import argparse

from . import changelog, checklist, contacts, deps, init, instruments, platform, render, rules, schema


def build() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='upgrade-pilot',
        description='Fly a TYPO3 major upgrade: flight log, gates, instruments, one rule per commit.',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('init', help='detect the project and open a flight log in .upgrade-pilot/')
    p.add_argument('--target', required=True, help='target major.minor, e.g. 13.4')
    p.add_argument('--source', help='source major.minor (default: from composer.lock)')
    p.add_argument('--ext', action='append', default=[], help='own extension path (repeatable, default: detected)')
    p.add_argument('--exec', help='runtime wrapper with {cmd}, e.g. "docker compose exec -T php sh -c {cmd}"')
    p.add_argument('--composer', help='composer command on the host, e.g. "ddev composer"')
    p.add_argument('--gates', choices=['human', 'auto'], default='human', help='who decides gates (default human)')
    p.add_argument('--branch-prefix', default='upgrade', help='prefix for the pre-flight and flight branches')
    p.add_argument('--project', help='project directory (default: git toplevel of cwd)')
    p.add_argument('--force', action='store_true', help='start over, replacing an existing flight')
    p.set_defaults(func=init.run)

    p = sub.add_parser('status', help='where are we, what is open')
    p.add_argument('-v', '--verbose', action='store_true', help='show how each open item can be answered')
    p.set_defaults(func=checklist.cmd_status)

    p = sub.add_parser('item', help='answer a checklist item')
    p.add_argument('id', help='item id, e.g. pf.scanner (unique suffix is enough)')
    p.add_argument('status', choices=checklist.STATUSES)
    p.add_argument('--note', help='reason / answer (required for no and na)')
    p.add_argument('--evidence', help='where the proof is: log path, commit, measurement label')
    p.set_defaults(func=checklist.cmd_item)

    p = sub.add_parser('gate', help='show or decide the gate at the end of a phase')
    p.add_argument('phase', choices=checklist.PHASES)
    p.add_argument('decision', choices=['show', 'go', 'nogo'])
    p.add_argument('--note', help='the reason for the decision')
    p.add_argument('--by', choices=['human', 'pilot'], help='who decided (default from the gate mode)')
    p.add_argument('--force', action='store_true', help='GO despite open items (they are recorded)')
    p.set_defaults(func=checklist.cmd_gate)

    p = sub.add_parser('phase', help='set the phase by hand')
    p.add_argument('phase', choices=checklist.PHASES + ['landed'])
    p.set_defaults(func=checklist.cmd_phase)

    p = sub.add_parser('measure', help='run test suites and record the result')
    p.add_argument('--suite', default='all', help='configured suite name or all (default)')
    p.add_argument('--label', required=True, help='stage label, e.g. "baseline" or "rector: RuleName"')
    p.add_argument('--extra', help='extra arguments appended to the suite command')
    p.add_argument('--show', type=int, default=60, help='lines of failure detail to print (default 60)')
    p.add_argument('--no-record', action='store_true', help='run without recording (quick checks while fixing)')
    p.set_defaults(func=instruments.cmd_measure)

    p = sub.add_parser('scan', help='Extension Scanner over own extensions, recorded')
    p.add_argument('--label', required=True)
    p.add_argument('--target', action='append', help='explicit scanner arguments instead of own extension keys')
    p.set_defaults(func=instruments.cmd_scan)

    p = sub.add_parser('tca', help='headless TCA migration check, recorded')
    p.add_argument('--label', required=True)
    p.set_defaults(func=instruments.cmd_tca)

    p = sub.add_parser('contacts', help='core contact points of own extensions and their test coverage')
    p.add_argument('--label', default='inventory')
    p.set_defaults(func=contacts.cmd_contacts)

    p = sub.add_parser('versions', help='support dates, PHP and testing-framework facts (get.typo3.org, Packagist)')
    p.add_argument('--target', help='another target than the configured one')
    p.set_defaults(func=platform.cmd_versions)

    p = sub.add_parser('bump', help='raise core constraints: show, probe (dry-run resolve, then restore) or apply')
    p.add_argument('mode', choices=['show', 'probe', 'apply'])
    p.set_defaults(func=platform.cmd_bump)

    p = sub.add_parser('deps', help='third-party packages that move, and their changelogs, upgrade notes and wizards')
    dsub = p.add_subparsers(dest='deps_command', required=True)
    c = dsub.add_parser('list', help='which third-party packages move: from the last bump probe, or between a git ref and now')
    c.add_argument('--from-lock', metavar='REF', help='compare composer.lock at this git ref with the working tree (after the bump)')
    c.set_defaults(func=deps.cmd_list)
    c = dsub.add_parser('docs', help='read changelogs, upgrade notes, breaking commits and new wizards of the moving packages')
    c.add_argument('--package', action='append', help='only this package (repeatable)')
    c.add_argument('--all', action='store_true', help='every moving package, not only extensions, majors and new ones')
    c.add_argument('--from', dest='from_version', help='with one --package: inspect this range without a deps list')
    c.add_argument('--to', dest='to_version')
    c.set_defaults(func=deps.cmd_docs)

    p = sub.add_parser('schema', help='database schema: detect tooling, dry run, apply (TYPO3 Console or core)')
    p.add_argument('action', choices=['check', 'plan', 'apply'])
    p.add_argument('--label', help='stage label for the flight log')
    p.add_argument('--types', help='TYPO3 Console update types, default "safe" (e.g. "*.add,*.change", "destructive")')
    p.add_argument('--destructive', action='store_true', help='plan: list drops and renames (types "destructive")')
    p.add_argument('--allow-destructive', action='store_true', help='apply: permit drops and renames, only on a recorded human decision')
    p.add_argument('--passes', type=int, default=None, help='apply: maximum passes (TYPO3 Console default 3, core default 2)')
    p.set_defaults(func=schema.cmd_schema)

    p = sub.add_parser('snapshot', help='local database snapshot (ddev)')
    p.add_argument('action', choices=['take', 'restore', 'list'])
    p.add_argument('--name')
    p.set_defaults(func=platform.cmd_snapshot)

    p = sub.add_parser('changelog', help='fetch and match core changelog entries against own code')
    csub = p.add_subparsers(dest='changelog_command', required=True)
    c = csub.add_parser('fetch')
    c.add_argument('--version', help='core branch to fetch (default: target)')
    c.add_argument('--refresh', action='store_true')
    c.set_defaults(func=changelog.cmd_fetch)
    c = csub.add_parser('match')
    c.add_argument('--source')
    c.add_argument('--target')
    c.add_argument('--no-source-deprecations', action='store_true', help='skip deprecations of the source major')
    c.add_argument('--strong-only', action='store_true')
    c.add_argument('--hits', type=int, default=4, help='hits printed per entry')
    c.set_defaults(func=changelog.cmd_match)

    p = sub.add_parser('rules', help='Rector / Fractor campaigns, one rule per commit')
    rsub = p.add_subparsers(dest='rules_command', required=True)

    def campaign_args(c, tool_needed=False):
        c.add_argument('--tool', choices=rules.TOOLS, required=tool_needed)
        c.add_argument('--campaign', help='campaign name (default: <phase>-<tool>)')

    c = rsub.add_parser('config', help='create the tool config for own extensions, or change its level set')
    c.add_argument('--tool', choices=rules.TOOLS, required=True)
    c.add_argument('--level', required=True, type=int, help='TYPO3 major for UP_TO_TYPO3_<n>')
    c.set_defaults(func=rules.cmd_config)
    c = rsub.add_parser('plan', help='dry run: which rules would change which files')
    campaign_args(c)
    c.add_argument('--config', help='tool config file (default <tool>.php)')
    c.add_argument('--all', action='store_true', help='list finished rules too')
    c.set_defaults(func=rules.cmd_plan)
    c = rsub.add_parser('next', help='the next rule to apply')
    campaign_args(c)
    c.set_defaults(func=rules.cmd_next)
    c = rsub.add_parser('apply', help='apply exactly one rule (default: the next one)')
    campaign_args(c)
    c.add_argument('--rule', help='FQCN or short class name')
    c.add_argument('--allow-dirty', action='store_true')
    c.set_defaults(func=rules.cmd_apply)
    c = rsub.add_parser('commit', help='commit the applied rule plus your review fixups')
    campaign_args(c)
    c.add_argument('--rule')
    c.add_argument('--message-file', help='commit message file (project commit rules apply)')
    c.add_argument('--note', help='review note stored with the rule')
    c.set_defaults(func=rules.cmd_commit)
    c = rsub.add_parser('skip', help='decline a rule (reverts it if applied)')
    campaign_args(c)
    c.add_argument('--rule')
    c.add_argument('--reason', required=True)
    c.set_defaults(func=rules.cmd_skip)
    c = rsub.add_parser('list', help='all rules of one or all campaigns')
    c.add_argument('--campaign')
    c.set_defaults(func=rules.cmd_list)

    p = sub.add_parser('report', help='render UPGRADE-REPORT.md from the flight log')
    p.set_defaults(func=render.cmd_report)
    return parser


def main(argv=None) -> None:
    args = build().parse_args(argv)
    args.func(args)
