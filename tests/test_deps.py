import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))

from upgrade_pilot.deps import hosting_path, in_range, interval, kind_of, literals, parse_operations, sections_in_range  # noqa: E402

UPGRADE_MD = """# Upgrade 6.x

## 6.1.0

### (BREAKING): Removed old option

Use `Vendor\\Pkg\\NewService::run()` instead.

## 6.0.0

### Removed TYPO3 v12 support

Nothing else.

# Upgrade 5.x

## 5.2.0

Old stuff.
"""


class VersionTest(unittest.TestCase):
    def test_interval(self):
        self.assertEqual(((6, 0, 7), (6, 0, 7)), interval('6.0.7'))
        self.assertEqual(((6, 0, 0), (6, 0, 0)), interval('v6.0'))
        self.assertEqual(((5, 0, 0), (5, 999, 999)), interval('5.x'))
        self.assertEqual(((6, 0, 1), (6, 0, 999)), interval('6.0.x'))
        self.assertIsNone(interval('X.Y.Z'))

    def test_range(self):
        self.assertTrue(in_range(interval('6.0'), '5.1.10', '6.0.7'))
        self.assertFalse(in_range(interval('5.1'), '5.1.10', '6.0.7'))
        self.assertTrue(in_range(interval('5.x'), '5.1.10', '6.0.7'))
        self.assertFalse(in_range(interval('6.1.0'), '5.1.10', '6.0.7'))
        self.assertTrue(in_range(interval('6.0.x'), '6.0.0', '6.0.7'))
        self.assertFalse(in_range(interval('6.0.x'), '5.1.10', '5.1.12'))

    def test_kind(self):
        self.assertEqual('major', kind_of('v5.1.10', '6.0.7'))
        self.assertEqual('minor', kind_of('2.2.1', '2.3.4'))
        self.assertEqual('added', kind_of(None, '1.0.0'))
        self.assertEqual('removed', kind_of('1.0.0', None))


class NotesTest(unittest.TestCase):
    def test_sections_in_range(self):
        sections, versioned = sections_in_range(UPGRADE_MD, 'UPGRADE.md', '5.2.0', '6.1.0')
        headings = [s['heading'] for s in sections]
        self.assertTrue(versioned)
        self.assertIn('(BREAKING): Removed old option', headings)
        self.assertIn('Removed TYPO3 v12 support', headings)
        self.assertNotIn('5.2.0', headings)
        breaking = [line for s in sections for line in s['breaking']]
        self.assertTrue(any('BREAKING' in line for line in breaking))

    def test_mentioned_versions_are_not_headings(self):
        sections, _ = sections_in_range(UPGRADE_MD, 'UPGRADE.md', '6.0.0', '6.1.0')
        self.assertNotIn('Removed TYPO3 v12 support', [s['heading'] for s in sections])

    def test_literals(self):
        self.assertEqual(['Vendor\\Pkg\\NewService::run()'], literals(UPGRADE_MD))


class HostingTest(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(('github.com', 'o/r'), hosting_path('https://github.com/o/r.git'))
        self.assertEqual(('git.example.org', 'group/sub/r'), hosting_path('git@git.example.org:group/sub/r.git'))
        self.assertEqual(('gitlab.com', 'g/r'), hosting_path('https://token@gitlab.com/g/r'))


class OperationsTest(unittest.TestCase):
    def test_parse(self):
        out = """Lock file operations: 1 install, 2 updates, 1 removal
  - Removing old/pkg (1.0.0)
  - Upgrading doctrine/dbal (3.10.6 => 4.4.5)
  - Installing new/pkg (2.0.0)
Package operations: 1 install, 1 update
  - Upgrading doctrine/dbal (3.10.6 => 4.4.5)
"""
        moves = {m['name']: m for m in parse_operations(out)}
        self.assertEqual(('3.10.6', '4.4.5'), (moves['doctrine/dbal']['from'], moves['doctrine/dbal']['to']))
        self.assertIsNone(moves['new/pkg']['from'])
        self.assertIsNone(moves['old/pkg']['to'])

    def test_dev_versions_carry_their_commit(self):
        moves = parse_operations('  - Upgrading a/b (dev-main 7ea78cc => dev-main b5ae456)\n')
        self.assertEqual(('dev-main', 'b5ae456'), (moves[0]['to'], moves[0]['to_ref']))


if __name__ == '__main__':
    unittest.main()
