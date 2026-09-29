import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))

from upgrade_pilot.platform import companion_constraint  # noqa: E402
from upgrade_pilot.schema import is_safe, statements_of  # noqa: E402

FACTS = {'companions': {
    'helhum/typo3-console': {'latest_compatible': '9.0.1', 'constraint': '^9', 'compatible': ['8.3.0', '8.3.1', '9.0.1']},
    'typo3/testing-framework': {'latest_compatible': '9.7.0', 'constraint': '^9', 'compatible': ['8.3.3', '9.7.0']},
}}


class SafeTypesTest(unittest.TestCase):
    def test_safe(self):
        for types in ('safe', '*.add,*.change', 'field.add', 'table.add, table.change'):
            with self.subTest(types=types):
                self.assertTrue(is_safe(types))

    def test_destructive(self):
        for types in ('destructive', '*', 'field.drop', '*.add,table.drop', 'field.prefix'):
            with self.subTest(types=types):
                self.assertFalse(is_safe(types))


class CompanionTest(unittest.TestCase):
    def test_console_is_kept_while_a_compatible_release_is_allowed(self):
        self.assertIsNone(companion_constraint('helhum/typo3-console', '^8.3', FACTS))

    def test_console_is_raised_when_nothing_allowed_supports_the_target(self):
        self.assertEqual('^9', companion_constraint('helhum/typo3-console', '^7.1', FACTS))

    def test_testing_framework_moves_to_the_latest_major(self):
        self.assertEqual('^9', companion_constraint('typo3/testing-framework', '^8.0', FACTS))
        self.assertIsNone(companion_constraint('typo3/testing-framework', '^9.1', FACTS))

    def test_dev_constraints_are_left_alone(self):
        self.assertIsNone(companion_constraint('helhum/typo3-console', 'dev-main', FACTS))


class StatementsTest(unittest.TestCase):
    def test_split(self):
        out = 'ALTER TABLE a ADD b INT;\nCREATE TABLE c (d INT);\n'
        self.assertEqual(['ALTER TABLE a ADD b INT', 'CREATE TABLE c (d INT)'], statements_of(out))
        self.assertEqual([], statements_of('\n'))


if __name__ == '__main__':
    unittest.main()


class BumpTest(unittest.TestCase):
    def run_bump(self, console_constraint):
        import json
        import tempfile
        from upgrade_pilot.platform import planned_edits

        class FakeFlight:
            config = {'facts': {'13.4': FACTS}}

            def __init__(self, root):
                self.root = root

            def extensions(self):
                return []

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            (root / 'composer.json').write_text(json.dumps({'require': {
                'typo3/cms-core': '^12.4', 'helhum/typo3-console': console_constraint,
            }, 'require-dev': {'typo3/testing-framework': '^8.0'}}, indent=4))
            edits, warnings = planned_edits(FakeFlight(root), '13.4')
            return json.loads(edits[0][2]), warnings

    def test_bridge_constraint_is_kept_without_warning(self):
        composer, warnings = self.run_bump('^8.3')
        self.assertEqual('^13.4', composer['require']['typo3/cms-core'])
        self.assertEqual('^8.3', composer['require']['helhum/typo3-console'])
        self.assertEqual('^9', composer['require-dev']['typo3/testing-framework'])
        self.assertEqual([], warnings)

    def test_console_seven_is_raised_with_binary_warning(self):
        composer, warnings = self.run_bump('^7.1')
        self.assertEqual('^9', composer['require']['helhum/typo3-console'])
        self.assertEqual(1, len(warnings))
        self.assertIn('typo3cms', warnings[0])
