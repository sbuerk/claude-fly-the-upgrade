import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))

from upgrade_pilot import docsite  # noqa: E402
from upgrade_pilot.deps import alias_version  # noqa: E402
from upgrade_pilot.docsite import docs_versions  # noqa: E402
from upgrade_pilot.deps import opt_in_wizards  # noqa: E402
from upgrade_pilot.touchpoints import package_info, project_files, scan, verdict  # noqa: E402

PHP = '<?php\n'


class VersionsTest(unittest.TestCase):
    def test_docs_versions(self):
        self.assertEqual(['main', '3.0'], docs_versions('dev-main', '3.0.x-dev'))
        self.assertEqual(['2', '2.4'], docs_versions('2.x-dev', '2.4.x-dev'))
        self.assertEqual(['3.0'], docs_versions('v3.0.7'))
        self.assertEqual(['2.3'], docs_versions('2.3.4'))

    def test_alias_version(self):
        meta = {'extra': {'branch-alias': {'dev-main': '3.0.x-dev'}}}
        self.assertEqual('3.0.999', alias_version(meta, 'dev-main'))
        self.assertIsNone(alias_version(meta, '3.0.1'))
        self.assertIsNone(alias_version({}, 'dev-feature'))


class DevelopmentVersionTest(unittest.TestCase):
    def test_development_versions_compare_by_alias(self):
        from upgrade_pilot.deps import comparable, kind_of, numeric
        self.assertFalse(numeric('2.x-dev'))
        self.assertFalse(numeric('2.4.x-dev'))
        self.assertTrue(numeric('v2.4.1'))
        self.assertEqual('changed', kind_of('2.3.4', '2.x-dev'))
        self.assertEqual('minor', kind_of('2.3.4', '2.x-dev', comparable('2.4.x-dev')))
        self.assertEqual('major', kind_of('2.3.4', 'dev-main', comparable('3.0.x-dev')))

    def test_alias_declared_for_another_version_name_is_ignored(self):
        from upgrade_pilot.platform import ignored_aliases
        facts = {'acme/shop-base': {'branch_alias': {'dev-2': '2.4.x-dev'}},
                 'acme/shop-catalog': {'branch_alias': {'2.x-dev': '2.4.x-dev'}},
                 'acme/shop-cart': {'branch_alias': {}}}
        self.assertEqual({'acme/shop-base': 'dev-2 -> 2.4.x-dev'}, ignored_aliases(facts, '2.x-dev'))


class ArchiveTest(unittest.TestCase):
    def test_restart_moves_the_old_flight_aside_and_keeps_the_cache(self):
        from upgrade_pilot.init import archive_previous
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            state = Path(tmp)
            (state / 'config.json').write_text(json.dumps({'source': '12.4', 'target': '13.4'}))
            for name in ('reports', 'cache', 'notes'):
                (state / name).mkdir()
            target = archive_previous(state)
            self.assertEqual({'archive', 'cache'}, {p.name for p in state.iterdir()})
            self.assertEqual({'config.json', 'reports', 'notes'}, {p.name for p in target.iterdir()})
            self.assertIsNone(archive_previous(state))


class WizardTest(unittest.TestCase):
    def test_excluded_wizard_is_opt_in_with_its_docblock(self):
        class Tree:
            files = {
                'Classes/Upgrades/A.php': PHP + '/**\n * Only for projects that used the old flag.\n */\n#[Exclude]\n'
                                          "#[UpgradeWizard('shop_a')]\nfinal class A {}\n",
                'Classes/Upgrades/B.php': PHP + "#[UpgradeWizard('shop_b')]\nfinal class B {}\n",
            }

            def read(self, path):
                return self.files[path]
        found = {'shop_a': 'Classes/Upgrades/A.php', 'shop_b': 'Classes/Upgrades/B.php'}
        self.assertEqual({'shop_a': 'Only for projects that used the old flag.'}, opt_in_wizards(Tree(), found))


class VerdictTest(unittest.TestCase):
    def test_unchanged_is_not_a_finding(self):
        self.assertEqual('ok', verdict('overridden methods unchanged (packages/site/Classes/X.php)'))
        self.assertEqual('ok', verdict('copied templates are unchanged in target'))
        self.assertEqual('attention', verdict('original CHANGED in target, re-base the copy'))
        self.assertEqual('attention', verdict('findByDemand() signature changed'))
        self.assertEqual('manual', verdict('check by hand: package class not resolved'))


class ResolveTest(unittest.TestCase):
    def test_globs(self):
        from upgrade_pilot.init import resolve_packages
        packages = {'acme/shop-base': {'version': '2.3.4'}, 'acme/shop-catalog': {'version': '2.3.4'},
                    'acme/other': {'version': '1.0.0'}, 'typo3/cms-core': {'version': 'v13.4.35'}}
        self.assertEqual({'acme/shop-base': '2.3.4', 'acme/shop-catalog': '2.3.4'},
                         resolve_packages(packages, ['acme/shop-*']))


class DocsiteTest(unittest.TestCase):
    def test_pages_from_toc_and_selection(self):
        toc = {'project': {'version': 'main'}, 'pages': [{'path': 'Index', 'title': 'X', 'md': 'Index.md', 'pages': [
            {'path': 'Upgrade/Index', 'title': 'Upgrading from 2.4 to 3.0.0', 'md': 'Upgrade/Index.md'},
            {'path': 'Configuration/Index', 'title': 'Configuration', 'md': 'Configuration/Index.md'},
            {'path': 'Changelog/3.0/Breaking-A', 'title': 'Breaking: A', 'md': 'Changelog/3.0/Breaking-A.md'},
            {'path': 'Changelog/2.3/Feature-B', 'title': 'Feature: B', 'md': 'Changelog/2.3/Feature-B.md'},
        ]}]}
        old_inventory = {'std:doc': {'Changelog/2.3/Feature-B': ['X', '2.3', 'Changelog/2.3/Feature-B.html', 'Feature: B']}}
        responses = {
            '/p/v/p/main/en-us/toc.json': (200, json.dumps(toc)),
            '/p/v/p/2.3/en-us/toc.json': (404, ''),
            '/p/v/p/2.3/en-us/objects.inv.json': (200, json.dumps(old_inventory)),
        }
        original = docsite.fetch

        def fake(url, cache):
            path = url.replace(docsite.BASE, '')
            if path in responses:
                return responses[path]
            if path.endswith('.md'):
                return 200, f'# {path}'
            return 404, ''
        docsite.fetch = fake
        try:
            result = docsite.read_manual('v/p', '2.3.4', 'dev-main', '3.0.999', None, Path('.'))
        finally:
            docsite.fetch = original
        self.assertEqual('main', result['version'])
        self.assertTrue(result['compared_with'].endswith('/2.3/en-us'))
        self.assertEqual(['Upgrade/Index', 'Changelog/3.0/Breaking-A'], [p['path'] for p in result['pages']])
        self.assertEqual('markdown', result['pages'][0]['format'])


class TouchpointsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        root = self.root = Path(self.tmp.name)
        pkg = root / 'vendor' / 'acme' / 'shop'
        (pkg / 'Configuration' / 'TCA').mkdir(parents=True)
        (pkg / 'Configuration' / 'TCA' / 'tx_shop_domain_model_product.php').write_text(PHP + 'return [];\n')
        (pkg / 'Resources' / 'Private' / 'Templates' / 'Product').mkdir(parents=True)
        (pkg / 'Resources' / 'Private' / 'Templates' / 'Product' / 'List.html').write_text('<div/>\n')
        (pkg / 'ext_localconf.php').write_text(PHP + "ExtensionUtility::configurePlugin('Shop', 'List', [], []);\n")
        ext = root / 'packages' / 'site'
        (ext / 'Classes' / 'Xclass').mkdir(parents=True)
        (ext / 'Classes' / 'Xclass' / 'ProductController.php').write_text(
            PHP + 'namespace Me\\Site\\Xclass;\nuse Acme\\Shop\\Controller\\ProductController as Base;\n'
            'final class ProductController extends Base\n{\n    public function listAction(): void {}\n}\n')
        (ext / 'Classes' / 'Listener.php').write_text(
            PHP + "use Acme\\Shop\\Event\\BeforeListEvent;\n#[AsEventListener]\nfinal class Listener {\n"
            '    public function __invoke(BeforeListEvent $event): void {}\n}\n')
        (ext / 'ext_localconf.php').write_text(
            PHP + "$GLOBALS['TYPO3_CONF_VARS']['SYS']['Objects'][\\Acme\\Shop\\Service\\Cart::class] = ['className' => \\Me\\Site\\Cart::class];\n"
            "$GLOBALS['TYPO3_CONF_VARS']['SYS']['locallangXMLOverride']['EXT:shop/Resources/Private/Language/locallang.xlf'][] = "
            "'EXT:site/Resources/Private/Language/shop.xlf';\n"
            "$GLOBALS['TYPO3_CONF_VARS']['EXTCONF']['shop']['hooks'][] = \\Me\\Site\\Hook::class;\n")
        (ext / 'Configuration' / 'TCA' / 'Overrides').mkdir(parents=True)
        (ext / 'Configuration' / 'TCA' / 'Overrides' / 'tx_shop_domain_model_product.php').write_text(PHP + "// adjust\n")
        (ext / 'Configuration' / 'TypoScript').mkdir(parents=True)
        (ext / 'Configuration' / 'TypoScript' / 'setup.typoscript').write_text(
            'plugin.tx_shop {\n  view.templateRootPaths.10 = EXT:site/Resources/Private/Extensions/Shop/Templates/\n}\n')
        (ext / 'Resources' / 'Private' / 'Extensions' / 'Shop' / 'Templates' / 'Product').mkdir(parents=True)
        (ext / 'Resources' / 'Private' / 'Extensions' / 'Shop' / 'Templates' / 'Product' / 'List.html').write_text(
            '<html xmlns:shop="http://typo3.org/ns/Acme/Shop/ViewHelpers"><shop:price value="1"/></html>\n')
        (root / 'config' / 'sites' / 'main').mkdir(parents=True)
        (root / 'config' / 'sites' / 'main' / 'config.yaml').write_text('routeEnhancers:\n  Shop:\n    type: Extbase\n    extension: Shop\n    plugin: List\n')
        (root / 'composer.json').write_text(json.dumps({'require': {'cweagans/composer-patches': '^1.7'},
                                                       'extra': {'patches': {'acme/shop': {'Fix cart': 'patches/shop-cart.patch'}}}}))
        self.lock = {'acme/shop': {'version': '1.2.0', 'type': 'typo3-cms-extension',
                                   'autoload': {'psr-4': {'Acme\\Shop\\': 'Classes/'}},
                                   'extra': {'typo3/cms': {'extension-key': 'shop'}}}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_kind_is_found(self):
        class FakeFlight:
            root = self.root

            def extensions(self):
                return [{'key': 'site', 'path': 'packages/site', 'package': 'me/site'}]
        flight = FakeFlight()
        info = package_info(flight, 'acme/shop', self.lock)
        self.assertEqual(['tx_shop_domain_model_product'], info['tables'])
        self.assertEqual(['shop_list'], info['plugins'])
        files = project_files(flight)
        kinds = {h['kind'] for h in scan(info, files, self.root)}
        for kind in ('patch', 'xclass', 'subclass', 'listener', 'hook', 'tca-override', 'template-copy',
                     'template-override', 'language-override', 'viewhelper-usage', 'site-config'):
            with self.subTest(kind=kind):
                self.assertIn(kind, kinds)


if __name__ == '__main__':
    unittest.main()
