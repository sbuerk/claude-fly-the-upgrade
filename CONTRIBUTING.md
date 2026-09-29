# Contributing

Thanks for helping to make TYPO3 upgrades less exciting.

## Reporting problems

Open an issue with:

- the TYPO3 versions (source and target) and the runtime (ddev, local PHP, other)
- the `upgrade-pilot` command and its output, or the step of the skill that went
  wrong
- the relevant part of `.upgrade-pilot/logs/` if a tool run is involved (remove
  anything confidential first, the logs contain paths and command output of your
  project)

Wrong facts about TYPO3 (a command that does not exist, a changed API) are bugs,
please report them with the version where you checked.

## Changing the plugin

1. Read [AGENTS.md](AGENTS.md). The hard rules there apply to every change, the
   most important one: nothing project-specific in this repository.
2. Fork, branch, change.
3. Run the checks:

   ```bash
   python3 -m unittest discover -s tests
   claude plugin validate --strict .
   claude plugin validate --strict ./.claude-plugin/plugin.json
   ```

4. For changes to the CLI, the PHP helper or a skill's procedure, run it on a real
   TYPO3 project on throwaway branches (`claude --plugin-dir <your clone>`), and
   say in the pull request what you ran it on and what the flight log recorded.
5. Add an entry to [CHANGELOG.md](CHANGELOG.md) under "Unreleased".
6. Commit messages follow the TYPO3 Core format described in AGENTS.md.
