<?php

declare(strict_types=1);

/*
 * Headless equivalent of "Admin Tools > Upgrade > Check TCA Migrations".
 *
 * TYPO3 has no CLI command for this check. This helper does what the backend
 * action does: load Configuration/TCA and Configuration/TCA/Overrides of all
 * active packages WITHOUT the automatic bootstrap migration, run the core
 * TcaMigration over it and report the messages as JSON on STDOUT.
 *
 * Run it from the composer root, inside the PHP runtime of the project:
 *   php .upgrade-pilot/bin/tca-migrations.php
 */

use TYPO3\CMS\Core\Core\Bootstrap;
use TYPO3\CMS\Core\Core\SystemEnvironmentBuilder;
use TYPO3\CMS\Core\Information\Typo3Version;
use TYPO3\CMS\Core\Package\PackageManager;

$classLoader = require getcwd() . '/vendor/autoload.php';
SystemEnvironmentBuilder::run(1, SystemEnvironmentBuilder::REQUESTTYPE_CLI);
$container = Bootstrap::init($classLoader);

$migrationClass = null;
foreach ([
    'TYPO3\\CMS\\Core\\Migrations\\TcaMigration',
    'TYPO3\\CMS\\Core\\Configuration\\Tca\\TcaMigration',
] as $candidate) {
    if (class_exists($candidate)) {
        $migrationClass = $candidate;
        break;
    }
}
if ($migrationClass === null) {
    fwrite(STDERR, "No TcaMigration class found in this TYPO3 version.\n");
    exit(2);
}

$packageManager = $container->get(PackageManager::class);
$phpFiles = static function (string $directory): array {
    if (!is_dir($directory)) {
        return [];
    }
    $files = array_filter(
        scandir($directory) ?: [],
        static fn(string $file): bool => str_ends_with($file, '.php') && is_file($directory . '/' . $file)
    );
    return array_values($files);
};

$tableOwner = [];
$overriddenBy = [];
$tcaFactoryClass = 'TYPO3\\CMS\\Core\\Configuration\\Tca\\TcaFactory';
if (class_exists($tcaFactoryClass) && method_exists($tcaFactoryClass, 'createNotMigrated')) {
    // TYPO3 v13+: the core builds (and enriches) TCA without migration itself,
    // exactly what the install tool calls. Attribution by file name convention.
    $GLOBALS['TCA'] = $container->get($tcaFactoryClass)->createNotMigrated();
    foreach ($packageManager->getActivePackages() as $package) {
        foreach ($phpFiles($package->getPackagePath() . 'Configuration/TCA') as $file) {
            $tableOwner[substr($file, 0, -4)] = $package->getPackageKey();
        }
        foreach ($phpFiles($package->getPackagePath() . 'Configuration/TCA/Overrides') as $file) {
            $overriddenBy[substr($file, 0, -4)][$package->getPackageKey()] = true;
        }
    }
} else {
    // Up to TYPO3 v12: what LoadTcaService::loadExtensionTablesWithoutMigration() does.
    // Same order as the core: all base TCA files first, then all overrides.
    $GLOBALS['TCA'] = [];
    foreach ($packageManager->getActivePackages() as $package) {
        $directory = $package->getPackagePath() . 'Configuration/TCA';
        foreach ($phpFiles($directory) as $file) {
            $tca = (static fn(string $path) => require $path)($directory . '/' . $file);
            if (is_array($tca)) {
                $table = substr($file, 0, -4);
                $GLOBALS['TCA'][$table] = $tca;
                $tableOwner[$table] = $package->getPackageKey();
            }
        }
    }
    foreach ($packageManager->getActivePackages() as $package) {
        $directory = $package->getPackagePath() . 'Configuration/TCA/Overrides';
        foreach ($phpFiles($directory) as $file) {
            $before = array_map('serialize', $GLOBALS['TCA']);
            (static function (string $path): void {
                require $path;
            })($directory . '/' . $file);
            foreach ($GLOBALS['TCA'] as $table => $tca) {
                if (!isset($before[$table]) || $before[$table] !== serialize($tca)) {
                    $overriddenBy[$table][$package->getPackageKey()] = true;
                }
            }
        }
    }
}

try {
    $migration = new $migrationClass();
} catch (\Throwable) {
    $migration = $container->get($migrationClass);
}
$GLOBALS['TCA'] = $migration->migrate($GLOBALS['TCA']);

$tables = array_keys($GLOBALS['TCA']);
usort($tables, static fn(string $a, string $b): int => strlen($b) <=> strlen($a));
$messages = [];
foreach ($migration->getMessages() as $message) {
    $message = (string)$message;
    $table = null;
    foreach ($tables as $candidate) {
        if (preg_match('/(?<![a-z0-9_])' . preg_quote($candidate, '/') . '(?![a-z0-9_])/', $message)) {
            $table = $candidate;
            break;
        }
    }
    $messages[] = [
        'table' => $table,
        'extension' => $table !== null ? ($tableOwner[$table] ?? null) : null,
        'overriddenBy' => $table !== null ? array_keys($overriddenBy[$table] ?? []) : [],
        'message' => $message,
    ];
}

fwrite(STDOUT, json_encode([
    'typo3' => (new Typo3Version())->getVersion(),
    'migrationClass' => $migrationClass,
    'count' => count($messages),
    'messages' => $messages,
], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n");
exit(0);
