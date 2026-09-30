import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))

from upgrade_pilot import gitops  # noqa: E402
from upgrade_pilot.commit import PLACEHOLDER, render, wrap_body  # noqa: E402
from upgrade_pilot.reports import day  # noqa: E402

TYPO3 = {'style': 'typo3', 'subject_max': 52, 'body_wrap': 72}
YOUTRACK = {'style': 'youtrack', 'subject_max': 52, 'body_wrap': 72}


class RenderTest(unittest.TestCase):
    def test_typo3_style_puts_refs_into_related_footers(self):
        message, warnings = render(TYPO3, 'TASK', 'Raise TYPO3 to v13.4', 'Why.', 'PRJ-7', ['PRJ-1'], [])
        self.assertTrue(message.startswith('[TASK] Raise TYPO3 to v13.4\n\nWhy.\n\n'))
        self.assertTrue(message.endswith('Related: PRJ-7\nRelated: PRJ-1\n'))
        self.assertNotIn('Resolves:', message)
        self.assertEqual([], warnings)

    def test_youtrack_style_puts_the_ref_into_the_subject(self):
        message, _ = render(YOUTRACK, 'TASK', 'Raise TYPO3', '', '{ISSUE-01}', ['PRJ-100'], [])
        self.assertEqual('[TASK] {ISSUE-01}: Raise TYPO3\n\nRelated: PRJ-100\n', message)

    def test_custom_template(self):
        policy = {'style': 'custom', 'template': '{ref} [{tag}] {subject}', 'subject_max': 80}
        message, _ = render(policy, 'BUGFIX', 'Fix it', '', 'ABC-1', [], [])
        self.assertTrue(message.startswith('ABC-1 [BUGFIX] Fix it'))

    def test_commands_block_and_breaking(self):
        message, _ = render(TYPO3, 'TASK', 'Drop X', 'Body.', None, [], ["composer require --no-update 'a/b:^2'"], breaking=True)
        self.assertTrue(message.startswith('[!!!][TASK] Drop X'))
        self.assertIn("Used command(s):\n\n```bash\ncomposer require --no-update 'a/b:^2'\n```", message)

    def test_long_subject_warns(self):
        _, warnings = render(TYPO3, 'TASK', 'x' * 60, '', None, [], [])
        self.assertEqual(1, len(warnings))

    def test_wrap_keeps_code_and_lists(self):
        body = ('word ' * 30).strip() + '\n\n- ' + ('item ' * 20).strip() + '\n\n```bash\n' + 'a' * 100 + '\n```'
        wrapped = wrap_body(body, 72)
        self.assertTrue(all(len(line) <= 72 for line in wrapped.splitlines() if not line.startswith('a')))
        self.assertIn('a' * 100, wrapped)
        self.assertIn('\n  item', wrapped)

    def test_placeholder_pattern(self):
        self.assertEqual(['{ISSUE-01}', '{ISSUE-12}'], PLACEHOLDER.findall('[TASK] {ISSUE-01}: x\n\nRelated: {ISSUE-12}'))


class GermanDateTest(unittest.TestCase):
    def test_day(self):
        self.assertEqual('31.12.2027', day('2027-12-31T00:00:00+01:00', 'de'))
        self.assertEqual('2027-12-31', day('2027-12-31T00:00:00+01:00'))


def git(root, *args, env=None):
    return subprocess.run(['git', *args], cwd=root, check=True, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}).stdout.strip()


class RewriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)
        env = {'GIT_AUTHOR_NAME': 'Ann', 'GIT_AUTHOR_EMAIL': 'ann@example.org', 'GIT_COMMITTER_NAME': 'Ann',
               'GIT_COMMITTER_EMAIL': 'ann@example.org', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull}
        self.env = env
        git(self.root, 'init', '-q', '-b', 'main', env=env)
        (self.root / 'composer.json').write_text('{"a": 1}\n')
        git(self.root, 'add', '-A', env=env)
        git(self.root, 'commit', '-q', '-m', 'base', env=env)
        git(self.root, 'switch', '-q', '-c', 'pilot', env=env)
        (self.root / 'composer.json').write_text('{"a": 2}\n')
        git(self.root, 'commit', '-q', '-am', '[TASK] {ISSUE-01}: composer', env=env)
        (self.root / 'code.php').write_text('<?php\n')
        git(self.root, 'add', '-A', env=env)
        git(self.root, 'commit', '-q', '-m', '[TASK] {ISSUE-02}: code\n\nRelated: {ISSUE-01}', env=env)

    def tearDown(self):
        self.tmp.cleanup()

    def test_message_rewrite_keeps_trees_and_authors(self):
        trees_before = git(self.root, 'log', '--format=%T', 'main..pilot')
        os.environ.update({'GIT_CONFIG_GLOBAL': os.devnull})
        mapping = gitops.rewrite(self.root, ['pilot'], ['main'],
                                 message=lambda sha, text: text.replace('{ISSUE-01}', 'PRJ-5').replace('{ISSUE-02}', 'PRJ-6'))
        self.assertEqual(2, sum(1 for old, new in mapping.items() if old != new))
        self.assertEqual(trees_before, git(self.root, 'log', '--format=%T', 'main..pilot'))
        self.assertEqual('[TASK] PRJ-6: code\n\nRelated: PRJ-5\n[TASK] PRJ-5: composer',
                         git(self.root, 'log', '--format=%B', 'main..pilot').replace('\n\n[TASK]', '\n[TASK]').strip())
        self.assertEqual('Ann', git(self.root, 'log', '-1', '--format=%an', 'pilot'))

    def test_unchanged_commits_keep_their_ids(self):
        mapping = gitops.rewrite(self.root, ['pilot'], ['main'], message=lambda sha, text: text)
        self.assertTrue(all(old == new for old, new in mapping.items()))

    def test_tree_replacement_for_composer_fold(self):
        blob = subprocess.run(['git', 'hash-object', '-w', '--stdin'], cwd=self.root, input='{"a": 3}\n', text=True,
                              capture_output=True, check=True).stdout.strip()
        gitops.rewrite(self.root, ['pilot'], ['main'], tree=lambda sha, tree: gitops.tree_with(self.root, tree, {'composer.json': blob}))
        self.assertEqual('{"a": 3}', git(self.root, 'show', 'pilot:composer.json'))
        self.assertEqual('{"a": 3}', git(self.root, 'show', 'pilot~1:composer.json'))
        self.assertEqual('<?php', git(self.root, 'show', 'pilot:code.php'))


if __name__ == '__main__':
    unittest.main()
