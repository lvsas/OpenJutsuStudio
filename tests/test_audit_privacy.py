"""The privacy audit must catch a path or a token, including in old commits."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('audit_privacy', ROOT / 'scripts' / 'audit_privacy.py')
audit = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(audit)


def git(repo: Path, *args: str) -> None:
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.org',
                    *args], check=True, capture_output=True, text=True)


class PrivacyAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        git(self.repo, 'init', '-q')
        self._root, self._allow = audit.ROOT, audit.ALLOWLIST
        audit.ROOT = self.repo
        audit.ALLOWLIST = self.repo / 'docs' / 'audit-allowlist.txt'
        self.addCleanup(self._restore)

    def _restore(self):
        audit.ROOT, audit.ALLOWLIST = self._root, self._allow

    def write(self, name: str, text: str) -> None:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_a_clean_tree_has_no_finding(self):
        self.write('README.md', 'Nothing private here.\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', 'clean')
        self.assertEqual(audit.audit_tree(), [])

    def test_a_home_path_in_the_tree_is_reported(self):
        self.write('notes.md', 'cache at /home/tester/work/x.png\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', 'leak')
        findings = audit.audit_tree()
        self.assertTrue(any('home-path' in line for line in findings), findings)

    def test_a_token_removed_from_the_tree_is_still_in_history(self):
        self.write('config.py', 'TOKEN = "ghp_' + 'a' * 32 + '"\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', 'token')
        (self.repo / 'config.py').unlink()
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', 'remove token')
        self.assertEqual(audit.audit_tree(), [])
        findings = audit.audit_history()
        self.assertTrue(any('github-token' in line for line in findings), findings)

    def test_a_declared_exception_is_honoured(self):
        self.write('tests/test_guard.py', "blacklist = '/home/tester/x'\n")
        self.write('docs/audit-allowlist.txt', 'tests/test_guard.py|home-path|fixture\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', 'allowlisted')
        self.assertEqual(audit.audit_tree(), [])


if __name__ == '__main__':
    unittest.main()
