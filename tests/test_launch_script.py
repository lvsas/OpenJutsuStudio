"""The cross-platform launcher must refuse unsafe binds and find the venv."""
import importlib.util
import os
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('launch', ROOT / 'scripts' / 'launch.py')
assert SPEC is not None and SPEC.loader is not None
launch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launch)


class LauncherTests(unittest.TestCase):
    def test_port_open_detects_a_listening_socket(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen(1)
            port = server.getsockname()[1]
            self.assertTrue(launch.port_open('127.0.0.1', port))

    def test_port_open_is_false_when_nothing_listens(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        self.assertFalse(launch.port_open('127.0.0.1', port))

    def test_venv_binary_name_matches_the_platform(self):
        path = launch.venv_bin('python')
        self.assertEqual(path.parent.name, 'Scripts' if os.name == 'nt' else 'bin')
        self.assertEqual(path.name, 'python.exe' if os.name == 'nt' else 'python')

    def test_a_wildcard_bind_is_refused_before_anything_starts(self):
        for host in ('0.0.0.0', '::', '[::]'):
            with patch.dict(os.environ, {'OPENGENJUTSU_HOST': host}):
                with self.assertRaises(SystemExit) as caught:
                    launch.main()
            self.assertEqual(caught.exception.code, 1)


if __name__ == '__main__':
    unittest.main()
