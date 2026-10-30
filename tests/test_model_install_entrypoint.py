"""Exercise the real CLI in a cold interpreter, without network or runtime IO."""
import json
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ColdInstallerTests(unittest.TestCase):
    def run_cli(self, *flags):
        # Keep this independent of imported config/module caches in the test runner.
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            root = Path(directory)
            runtime, comfy = root / 'runtime', root / 'ComfyUI'
            environment = dict(os.environ, OPENGENJUTSU_WORK=str(runtime),
                               PYTHONDONTWRITEBYTECODE='1')
            code = (
                "import runpy,socket,sys; "
                "deny=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network forbidden')); "
                "socket.create_connection=deny; socket.socket.connect=deny; "
                "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
            )
            command = [sys.executable, '-B', '-c', code,
                       str(ROOT / 'scripts/download_models.py')]
            command += list(flags) if flags == ('--help',) else [
                '--comfyui', str(comfy), '--engine', 'h3', *flags]
            result = subprocess.run(command, cwd=root, env=environment,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse(runtime.exists(), 'Planning must not initialize application work storage')
            self.assertFalse(comfy.exists(), 'Planning must not initialize an executor or install weights')
            self.assertEqual(list(root.iterdir()), [], 'Cold plan/help must leave its working directory unchanged')
            return result.stdout

    def test_help_does_not_initialize_runtime(self):
        self.assertIn('--dry-run', self.run_cli('--help'))

    def test_plan_modes_do_not_initialize_runtime_or_use_network(self):
        for flags in [(), ('--dry-run',), ('--download', '--dry-run')]:
            with self.subTest(flags=flags):
                self.assertIn('Plan only', self.run_cli(*flags))

    def test_h3_upscaler_destination_matches_pinned_upstream_loader(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        download_models = importlib.import_module("download_models")
        manifest = json.loads((ROOT / 'dependencies.json').read_text())
        plan, unresolved = download_models.build_plan(manifest, 'h3')
        self.assertEqual(unresolved, [])
        upscaler = next(item for item in plan if item['role_key'] == 'h3_upscaler')
        self.assertEqual(upscaler['relative'],
                         'latent_upscale_models/minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors')

    def test_dependency_checker_recognizes_upstream_upscaler_folder(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        check_dependencies = importlib.import_module("check_dependencies")
        filename = 'minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors'
        inventory = {'MinimaxH3LatentUpscaler3D': {
            'input': {'required': {'model_name': [[filename]]}}}}
        report = check_dependencies.check(inventory, {'models': [
            {'file': filename, 'folder': 'latent_upscale_models'}]})
        self.assertEqual(report['missing_models'], [])
        self.assertEqual(report['checked_models'], 1)


if __name__ == '__main__':
    unittest.main()
