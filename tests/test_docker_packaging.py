"""The Docker path must stay honest: loopback only, and the app, nothing else."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / 'Dockerfile').read_text()
COMPOSE = (ROOT / 'docker-compose.yml').read_text()


class DockerPackaging(unittest.TestCase):
    def test_the_image_runs_the_app_with_ffmpeg(self):
        self.assertIn('FROM python:3.12-slim', DOCKERFILE)
        self.assertIn('ffmpeg', DOCKERFILE)
        self.assertIn('-r requirements.txt', DOCKERFILE)
        self.assertIn('"uvicorn"', DOCKERFILE)
        self.assertIn('"src.app:app"', DOCKERFILE)

    def test_the_container_does_not_ship_tests_or_the_virtualenv(self):
        ignore = (ROOT / '.dockerignore').read_text()
        for entry in ('.venv', 'tests', 'work'):
            self.assertIn(entry, ignore)

    def test_the_published_port_is_loopback_only(self):
        self.assertIn('"127.0.0.1:8000:8000"', COMPOSE)
        self.assertNotIn('"0.0.0.0:8000:8000"', COMPOSE)

    def test_the_container_reaches_a_proxy_on_the_host(self):
        self.assertIn('COMFY_BASE_URL', COMPOSE)
        self.assertIn('host.docker.internal', COMPOSE)


if __name__ == '__main__':
    unittest.main()
