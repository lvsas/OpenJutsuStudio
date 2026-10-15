"""Regression coverage for SDK target and authenticated workflow transport."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import comfy_transport as transport


class ComfyTargetTests(unittest.TestCase):
    def test_no_environment_targets_local_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            client = transport.make_client()
            self.addCleanup(client.close)
            self.assertEqual(client._low.safe_base_url, "http://127.0.0.1:8189")
            self.assertFalse(client._low.authenticated)

    def test_blank_target_is_local(self):
        with patch.dict(os.environ, {"COMFY_BASE_URL": "  "}, clear=True):
            client = transport.make_client()
            self.addCleanup(client.close)
            self.assertEqual(client._low.safe_base_url, "http://127.0.0.1:8189")

    def test_explicit_target_preserved(self):
        with patch.dict(os.environ, {"COMFY_BASE_URL": "http://127.0.0.1:9876"}, clear=True):
            client = transport.make_client()
            self.addCleanup(client.close)
            self.assertEqual(client._low.safe_base_url, "http://127.0.0.1:9876")

    def test_cloud_requires_key_without_leaking_it(self):
        with patch.dict(os.environ, {"COMFY_BASE_URL": "https://cloud.comfy.org"}, clear=True):
            from comfy_sdk import MissingApiKey
            with self.assertRaises(MissingApiKey):
                transport.make_client()


class SDKTransportTests(unittest.TestCase):
    def test_submission_and_download_use_same_sdk_client(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(transport, "WORK", Path(tmp)):
            client = MagicMock()
            output = MagicMock(name="output")
            output.name = "../../outside.png"
            output.to_file.side_effect = lambda dest: Path(dest).write_bytes(b"image")
            client.run.return_value.get_outputs.return_value = [output]
            graph = {"9": {"class_type": "SaveImage", "inputs": {}}}
            name = transport._run_graph(client, graph, "9")
            client.workflows.from_json.assert_called_once_with(graph)
            client.run.assert_called_once_with(client.workflows.from_json.return_value, timeout=1800)
            client.run.return_value.get_outputs.assert_called_once_with("9")
            self.assertEqual(Path(name).name, name)
            self.assertEqual((Path(tmp) / "media" / name).read_bytes(), b"image")

    def test_missing_requested_output_fails_not_fallback(self):
        client = MagicMock()
        client.run.return_value.get_outputs.return_value = []
        with self.assertRaisesRegex(RuntimeError, "output.*9"):
            transport._run_graph(client, {}, "9")
