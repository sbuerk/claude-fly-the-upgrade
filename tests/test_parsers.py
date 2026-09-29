import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))

from upgrade_pilot.instruments import parse_phpunit, summarize  # noqa: E402
from upgrade_pilot.platform import allows, expand_minified  # noqa: E402


class PhpunitSummaryTest(unittest.TestCase):
    def test_plain_ok(self):
        result = parse_phpunit('...\n\nOK (5 tests, 22 assertions)\n')
        self.assertEqual((result['tests'], result['assertions'], result['status']), (5, 22, 'OK'))
        self.assertEqual(summarize(result), 'OK - 5 tests · 22 assertions')

    def test_ok_with_issues(self):
        result = parse_phpunit('OK, but there were issues!\nTests: 8, Assertions: 11, Deprecations: 4.\n')
        self.assertEqual(result['deprecations'], 4)
        self.assertEqual(result['status'], 'OK, but there were issues!')

    def test_errors(self):
        result = parse_phpunit('ERRORS!\nTests: 8, Assertions: 2, Errors: 6, Deprecations: 4.\n')
        self.assertEqual((result['errors'], result['deprecations']), (6, 4))
        self.assertEqual(result['status'], 'ERRORS!')

    def test_phpunit_deprecations(self):
        result = parse_phpunit('OK, but there were issues!\nTests: 3, Assertions: 3, PHPUnit Deprecations: 2.\n')
        self.assertEqual(result['phpunit_deprecations'], 2)


class ConstraintTest(unittest.TestCase):
    def test_forms(self):
        self.assertTrue(allows('12.*.*@dev || 13.*.*@dev', '13.4.0'))
        self.assertFalse(allows('12.*.*@dev', '13.4.0'))
        self.assertTrue(allows('^13.4', '13.4.20'))
        self.assertFalse(allows('^13.4', '14.0.0'))
        self.assertTrue(allows('>=12.4 <14.0', '13.4.0'))
        self.assertTrue(allows('^8.2', '8.3.1'))
        self.assertTrue(allows('~8.2.0', '8.2.9'))
        self.assertFalse(allows('~8.2.0', '8.3.0'))
        self.assertTrue(allows('13.4.*', '13.4.1'))
        self.assertTrue(allows('^12.4 | ^13.4', '13.4.0'))


class MinifiedTest(unittest.TestCase):
    def test_expand(self):
        expanded = expand_minified([
            {'version': '2.0.0', 'require': {'a': '^1'}, 'x': 1},
            {'version': '1.0.0', 'x': '__unset'},
        ])
        self.assertEqual(expanded[1], {'version': '1.0.0', 'require': {'a': '^1'}})


if __name__ == '__main__':
    unittest.main()
