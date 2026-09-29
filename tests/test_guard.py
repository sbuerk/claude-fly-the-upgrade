import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'hooks'))

from guard_base_branch import verdict  # noqa: E402


class GuardTest(unittest.TestCase):
    def test_blocks(self):
        for command, branch in [
            ('git checkout main && git merge upgrade/13.4', 'upgrade/13.4'),
            ('git merge --no-ff x', 'main'),
            ('git commit -m x', 'main'),
            ('git push origin main', 'upgrade/13.4'),
            ('git push origin HEAD:main', 'upgrade/13.4'),
            ('git push', 'main'),
            ('git push --all origin', 'upgrade/13.4'),
            ('git switch main; git cherry-pick abc', 'x'),
            ('git branch -f main HEAD', 'x'),
            ('gh pr merge 12 --squash', 'x'),
            ('git -C . rebase upgrade/13.4', 'main'),
            ('git reset --hard origin/upgrade', 'main'),
        ]:
            with self.subTest(command=command):
                self.assertIsNotNone(verdict(command, 'main', branch))

    def test_allows(self):
        for command, branch in [
            ('git commit -m x', 'upgrade/13.4'),
            ('git push -u origin upgrade/13.4', 'upgrade/13.4'),
            ('git checkout main && git checkout -- . && git clean -fd', 'upgrade/13.4'),
            ('git switch -c upgrade/13.4 main', 'main'),
            ('git switch -c upgrade/13.4 && git commit -m x', 'main'),
            ('git log main..upgrade/13.4', 'main'),
            ('git diff main', 'upgrade/13.4'),
            ('git reset --hard', 'main'),
            ('git switch -c upgrade/13.4 main && git commit -m x', 'main'),
            ('git checkout -b pilot/x origin/main; git merge y', 'main'),
        ]:
            with self.subTest(command=command):
                self.assertIsNone(verdict(command, 'main', branch))


if __name__ == '__main__':
    unittest.main()
