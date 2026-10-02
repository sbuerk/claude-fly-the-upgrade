import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))

from upgrade_pilot import assess, blockers, catalog, delivery, patches  # noqa: E402

PHP = '<?php\n'
CORE = '14.3.7'


def version(v, core=None, **extra):
    require = {'typo3/cms-core': core} if core else {'php': '>=8.2'}
    return {'version': v, 'require': require, **extra}


class CatalogTest(unittest.TestCase):
    def test_released_version_wins(self):
        entry = catalog.classify('acme/shop', '2.3.4', CORE, '8.3',
                                 [version('2.3.4', '^13.4'), version('3.0.0', '^13.4 || ^14.3'), version('3.1.0-beta1', '^14.3')],
                                 [version('dev-main', '^14.3')], None, '^2.3')
        self.assertEqual('released', entry['status'])
        self.assertEqual('3.0.0', entry['version'])
        self.assertFalse(entry['in_constraint'])

    def test_only_a_branch_supports_the_target(self):
        branch = version('dev-main', '~13.4.0@dev || ~14.3.6@dev', extra={'branch-alias': {'dev-main': '3.0.x-dev'}})
        entry = catalog.classify('acme/shop', '2.3.4', CORE, None, [version('2.3.4', '^12.4.22 || ^13.4')],
                                 [version('2.x-dev', '^13.4'), branch], None, '^2.3')
        self.assertEqual('dev-only', entry['status'])
        self.assertEqual([{'version': 'dev-main', 'alias': '3.0.x-dev', 'reference': None,
                           'requires': {'typo3/cms-core': '~13.4.0@dev || ~14.3.6@dev'}}], entry['branches'])

    def test_ter_has_a_release_composer_does_not(self):
        ter = [{'number': '5.0.0', 'state': 'stable', 'dependencies': {'typo3': '13.4.0-14.3.99'}},
               {'number': '5.1.0', 'state': 'beta', 'dependencies': {'typo3': '>=14.3.0 <=14.3.99'}}]
        entry = catalog.classify('acme/shop', '4.0.0', CORE, None, [version('4.0.0', '^13.4')], [], ter, '^4.0')
        self.assertEqual(('released-ter', '5.0.0'), (entry['status'], entry['version']))

    def test_nothing_and_independent(self):
        self.assertEqual('none', catalog.classify('a/b', '1.0.0', CORE, None, [version('1.0.0', '^12.4')], [], [], None)['status'])
        self.assertEqual('independent', catalog.classify('a/lib', '1.0.0', CORE, None, [version('1.0.0')], [], None, None)['status'])

    def test_ter_ranges(self):
        self.assertEqual('>=13.4.0 <=14.3.99', catalog.ter_range('13.4.0-14.3.99'))
        self.assertEqual('>=12.4.0', catalog.ter_range('12.4.0-0.0.0'))
        self.assertTrue(catalog.ter_supports({'dependencies': {'typo3': '>=13.4.29 <=14.3.99'}}, CORE))
        self.assertFalse(catalog.ter_supports({'dependencies': []}, CORE))

    def test_documentation_mentions(self):
        pattern = catalog.mention('14')
        self.assertTrue(pattern.search('Supports TYPO3 v14 and TYPO3 13 LTS'))
        self.assertTrue(pattern.search('compatible with TYPO3 CMS 14.3'))
        self.assertFalse(pattern.search('TYPO3 v140 is not a thing'))


class PatchesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def composer(self, data):
        (self.root / 'composer.json').write_text(json.dumps(data))

    def test_cweagans_1(self):
        self.composer({'require': {'cweagans/composer-patches': '^1.7'},
                       'extra': {'patches': {'acme/shop': {'Fix cart': 'patches/cart.patch'}}, 'patchLevel': {'acme/shop': '-p2'},
                                 'patches-file': 'ignored-because-patches-is-set.json'}})
        plugin = patches.detect(self.root, {})
        self.assertEqual(('cweagans', 1), (plugin['plugin'], plugin['major']))
        defs = patches.definitions(self.root, plugin, {})
        self.assertEqual([('acme/shop', 'patches/cart.patch', [2])], [(d['package'], d['source'], d['levels']) for d in defs])

    def test_cweagans_2_expanded_and_patches_file(self):
        self.composer({'require': {'cweagans/composer-patches': '^2.0'},
                       'extra': {'patches': {'acme/shop': [{'description': 'Fix', 'url': 'patches/a.patch', 'depth': 0}]},
                                 'composer-patches': {'default-patch-depth': 3}}})
        (self.root / 'patches.json').write_text(json.dumps({'patches': {'acme/cart': {'Other': 'https://example.org/b.patch'}}}))
        lock = {'cweagans/composer-patches': {'version': '2.0.0'}}
        defs = patches.definitions(self.root, None, lock)
        self.assertEqual([('acme/shop', [0]), ('acme/cart', [3])], [(d['package'], d['levels']) for d in defs])

    def test_cweagans_2_lock_is_the_truth(self):
        self.composer({'require': {'cweagans/composer-patches': '^2.0'}, 'extra': {'patches': {'acme/shop': {'Old': 'old.patch'}}}})
        (self.root / 'patches.lock.json').write_text(json.dumps({'_hash': 'x', 'patches': [
            {'package': 'acme/shop', 'description': 'Locked', 'url': 'locked.patch', 'depth': 1, 'extra': {'provenance': 'root'}}]}))
        defs = patches.definitions(self.root, None, {'cweagans/composer-patches': {'version': '2.0.0'}})
        self.assertEqual(['locked.patch'], [d['source'] for d in defs])

    def test_vaimo_forms_and_search(self):
        (self.root / 'patches').mkdir()
        (self.root / 'patches' / 'found.patch').write_text(
            'Fixes the cart\n@package acme/shop\n@version >=2.0 <3.0\n@level 1\n\n--- a/x.php\n+++ b/x.php\n')
        self.composer({'require': {'vaimo/composer-patches': '^6.0'}, 'extra': {
            'patches': {'acme/shop': {'plain': 'patches/plain.patch', 'ranged': {'<2.5': 'patches/ranged.patch'},
                                      'object': {'source': 'patches/object.patch', 'version': '^2.3', 'level': 0},
                                      'skipped': 'patches/skip.patch#skip', '_comment': 'ignored'}},
            'patches-search': 'patches'}})
        defs = {d['description']: d for d in patches.definitions(self.root, None, {})}
        self.assertEqual(['plain', 'ranged', 'object', 'skipped', 'Fixes the cart'], list(defs))
        self.assertEqual(('patches/ranged.patch', '<2.5'), (defs['ranged']['source'], defs['ranged']['version']))
        self.assertEqual(([0], '^2.3'), (defs['object']['levels'], defs['object']['version']))
        self.assertTrue(defs['skipped']['skip'])
        self.assertEqual(('acme/shop', '>=2.0 <3.0', [1]), (defs['Fixes the cart']['package'], defs['Fixes the cart']['version'],
                                                          defs['Fixes the cart']['levels']))

    def test_vaimo_header_label_skips_git_metadata(self):
        tags = patches.vaimo_header('Fix the cart\n@package acme/shop\n@version pkg/x:>=1.0\n\ndiff --git a/x b/x\n'
                                    'index 1234abc..5678def 100644\n--- a/x\n+++ b/x\n')
        self.assertEqual(('Fix the cart', 'acme/shop', 'pkg/x:>=1.0'), (tags['label'], tags['package'], tags['version']))

    def test_vaimo_dependency_paths_are_relative_to_the_owner(self):
        self.composer({'require': {'vaimo/composer-patches': '^6.0'}})
        (self.root / 'vendor' / 'acme' / 'fixes').mkdir(parents=True)
        lock = {'vaimo/composer-patches': {'version': '6.0.2'},
                'acme/fixes': {'extra': {'patches': {'acme/shop': {'From a package': 'p/fix.patch'}}}}}
        defs = patches.definitions(self.root, None, lock)
        self.assertEqual([('acme/fixes', 'vendor/acme/fixes')], [(d['owner'], d['base']) for d in defs])

    def test_apply_check_outside_the_project_repository(self):
        tree = self.root / 'tree'
        tree.mkdir()
        (tree / 'a.txt').write_text('one\ntwo\n')
        patch = self.root / 'change.patch'
        patch.write_text('--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,2 @@\n one\n-two\n+three\n')
        self.assertEqual(1, patches.apply_check(tree, patch, [0, 1]))
        self.assertIsNone(patches.apply_check(tree, patch, [1], reverse=True))
        (tree / 'a.txt').write_text('one\nthree\n')
        self.assertEqual(1, patches.apply_check(tree, patch, [1], reverse=True))


class RestoreTest(unittest.TestCase):
    def test_probe_restore_keeps_uncommitted_work(self):
        from upgrade_pilot.platform import restore_files, snapshot_files
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            (root / 'composer.json').write_text('{"description": "uncommitted edit"}')
            saved = snapshot_files(root, ['composer.json', 'packages.json'])
            (root / 'composer.json').write_text('{"require": {}}')
            (root / 'packages.json').write_text('{}')
            restore_files(root, saved)
            self.assertEqual('{"description": "uncommitted edit"}', (root / 'composer.json').read_text())
            self.assertFalse((root / 'packages.json').exists())


class DeliveryTest(unittest.TestCase):
    def test_findings(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            (root / '.github' / 'workflows').mkdir(parents=True)
            (root / '.github' / 'workflows' / 'ci.yml').write_text("jobs:\n  t:\n    steps:\n      - uses: shivammathur/setup-php@v2\n"
                                                                   "        with:\n          php-version: '8.1'\n")
            (root / 'deploy.php').write_text(PHP + "run('{{bin/php}} {{release_path}}/vendor/bin/typo3cms database:updateschema');\n"
                                             "run('vendor/bin/typo3 cache:flush'); // typo3 is great\n")
            (root / 'composer.lock').write_text(json.dumps({'packages': [{'name': 'helhum/typo3-console', 'version': 'v8.2.1'}]}))

            class FakeFlight:
                config = {'target': '14.3', 'facts': {'14.3': {'core_php': '^8.2', 'companions': {'helhum/typo3-console': {'constraint': '^8.3'}}}}}

            FakeFlight.root = root
            findings = delivery.scan(FakeFlight(), ['cache:flush', 'list'])
            got = [(f['kind'], f['status']) for f in findings]
            self.assertIn(('php', 'attention'), got)
            self.assertIn(('binary', 'attention'), got)
            self.assertIn(('command', 'attention'), got)  # database:updateschema unknown to the instance
            self.assertIn(('command', 'ok'), got)
            self.assertEqual(4, len(findings))


class DiffTest(unittest.TestCase):
    def test_changes_between_assessments(self):
        class FakeFlight:
            log = {'blockers': [{'package': 'acme/shop', 'status': 'open'}]}
        old = {'at': '2026-10-01', 'probe': 1, 'packages': [{'name': 'acme/shop', 'status': 'dev-only'}],
               'audits': {'target': {'advisories': [{'id': 'A1', 'title': 't'}]}}}
        new = {'at': '2026-10-02', 'probe': 0, 'packages': [{'name': 'acme/shop', 'status': 'released', 'version': '3.0.0'}],
               'audits': {'target': {'advisories': [{'id': 'A2', 'title': 't'}]}}}
        result = assess.diff(old, new, FakeFlight())
        self.assertEqual([{'package': 'acme/shop', 'change': 'dev-only -> released 3.0.0'}], result['packages'])
        self.assertEqual((['A2'], ['A1'], (1, 0), ['acme/shop']),
                         (result['advisories_new'], result['advisories_gone'], result['probe'], result['blockers_resolvable']))


class BlockerTest(unittest.TestCase):
    def test_resolution_needs_release_commit_green_tests_and_touchpoints(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            run = lambda *a: subprocess.run(['git', *a], cwd=root, check=True, capture_output=True,
                                            env={'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
                                                 'GIT_COMMITTER_EMAIL': 't@t', 'HOME': tmp, 'PATH': '/usr/bin:/bin'})
            run('init', '-q', '-b', 'main')
            lock = {'packages': [{'name': 'acme/shop', 'version': '3.0.0', 'require': {'typo3/cms-core': '^14.3'}}]}
            (root / 'composer.lock').write_text(json.dumps(lock))
            run('add', '.')
            run('commit', '-qm', 'lock')

            class FakeFlight:
                config = {'tests': {'unit': {}}}
                log = {'measurements': [{'suite': 'unit', 'exit': 0, 'at': '2999-01-01T00:00:00+00:00'}],
                       'touchpoints': [{'verified': True, 'at': '2999-01-01T00:00:00+00:00'}]}
            FakeFlight.root = root
            FakeFlight.dir = root / '.upgrade-pilot'
            entry = {'package': 'acme/shop', 'core': CORE}
            self.assertTrue(all(passed for _, passed, _ in blockers.resolution_checks(FakeFlight(), entry)))
            FakeFlight.log['measurements'][0]['exit'] = 1
            self.assertFalse(all(passed for _, passed, _ in blockers.resolution_checks(FakeFlight(), entry)))
            FakeFlight.log['measurements'][0]['exit'] = 0
            lock['packages'][0]['version'] = 'dev-main'
            (root / 'composer.lock').write_text(json.dumps(lock))
            checks = dict((n, p) for n, p, _ in blockers.resolution_checks(FakeFlight(), entry))
            self.assertFalse(checks['a released version is installed'])
            self.assertFalse(checks['the change is committed'])


if __name__ == '__main__':
    unittest.main()
