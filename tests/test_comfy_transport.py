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

    def test_inherited_sdk_target_is_ignored(self):
        with patch.dict(os.environ, {"COMFY_BASE_URL": "https://cloud.comfy.org"}, clear=True):
            client = transport.make_client()
            self.addCleanup(client.close)
            self.assertEqual(client._low.safe_base_url, "http://127.0.0.1:8189")
            self.assertFalse(client._low.authenticated)

    def test_explicit_app_override_is_preserved(self):
        with patch.dict(os.environ, {"OPENGENJUTSU_COMFY_BASE_URL": "http://127.0.0.1:9876"}, clear=True):
            client = transport.make_client()
            self.addCleanup(client.close)
            self.assertEqual(client._low.safe_base_url, "http://127.0.0.1:9876")
    def test_explicit_cloud_target_uses_sdk_api_key_without_logging_it(self):
        with patch.dict(os.environ, {
            "OPENGENJUTSU_COMFY_BASE_URL": "https://cloud.comfy.org",
            "COMFY_API_KEY": "test-cloud-key",
        }, clear=True):
            client = transport.make_client()
            self.addCleanup(client.close)
            self.assertEqual(client._low.safe_base_url, "https://cloud.comfy.org")
            self.assertTrue(client._low.authenticated)
            self.assertNotIn("test-cloud-key", repr(client))


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

    def test_multi_artifact_transport_rejects_invalid_node_before_submission(self):
        for node_id in ("   ", "18:13:7", "9foo", "char-name", "foo:bar"):
            with self.subTest(node_id=node_id), tempfile.TemporaryDirectory() as tmp:
                client = MagicMock()
                with self.assertRaisesRegex(ValueError, "node identifier"):
                    transport._run_graph_artifacts(
                        client, {}, {"image": (node_id, {".png"})}, Path(tmp) / "job")
                client.workflows.from_json.assert_not_called()
                client.run.assert_not_called()

    def test_multi_artifact_transport_never_follows_a_dangling_destination_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "job"
            root.symlink_to(Path(tmp) / "does-not-exist")
            client = MagicMock()
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                transport._run_graph_artifacts(
                    client, {}, {"image": ("9", {".png"})}, root)
            self.assertTrue(root.is_symlink())
            client.workflows.from_json.assert_not_called()
            client.run.assert_not_called()

    def test_multi_artifact_publish_never_replaces_a_competing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "job"
            client = MagicMock()
            image, caption = MagicMock(), MagicMock()
            image.name, caption.name = "image.png", "caption.txt"
            image.to_file.side_effect = lambda dest: Path(dest).write_bytes(b"ours")
            caption.to_file.side_effect = lambda dest: Path(dest).write_bytes(b"caption")
            client.run.return_value.get_outputs.side_effect = lambda node: {
                "9": [image], "caption": [caption],
            }[node]
            real_publish = transport._publish_directory

            def raced_publish(staging, destination):
                destination.mkdir()
                (destination / "competitor.txt").write_bytes(b"competitor")
                return real_publish(staging, destination)

            with patch.object(transport, "_publish_directory", side_effect=raced_publish):
                with self.assertRaises(FileExistsError):
                    transport._run_graph_artifacts(
                        client, {}, {"image": ("9", {".png"}), "caption": ("caption", {".txt"})}, root)
            self.assertEqual((root / "competitor.txt").read_bytes(), b"competitor")
            self.assertFalse((root / "image.png").exists())
            self.assertFalse(list(root.parent.glob(f".{root.name}.*.part")))

    def test_multi_artifact_transport_fails_closed_when_renameat2_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "job"
            client = MagicMock()
            output = MagicMock()
            output.name = "image.png"
            output.to_file.side_effect = lambda dest: Path(dest).write_bytes(b"image")
            client.run.return_value.get_outputs.return_value = [output]
            with patch.object(transport.ctypes, "CDLL", return_value=object()):
                with self.assertRaisesRegex(RuntimeError, "lacks renameat2"):
                    transport._run_graph_artifacts(client, {}, {"image": ("9", {".png"})}, root)
            self.assertFalse(root.exists())
            self.assertFalse(list(root.parent.glob(f".{root.name}.*.part")))

    def test_multi_artifact_transport_cleans_staging_when_renameat2_is_unsupported(self):
        class UnsupportedRename:
            argtypes = None
            restype = None

            def __call__(self, *args):
                transport.ctypes.set_errno(transport.errno.ENOSYS)
                return -1

        class UnsupportedLibrary:
            renameat2 = UnsupportedRename()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "job"
            client = MagicMock()
            output = MagicMock()
            output.name = "image.png"
            output.to_file.side_effect = lambda dest: Path(dest).write_bytes(b"image")
            client.run.return_value.get_outputs.return_value = [output]
            with patch.object(transport.ctypes, "CDLL", return_value=UnsupportedLibrary()):
                with self.assertRaises(OSError) as raised:
                    transport._run_graph_artifacts(client, {}, {"image": ("9", {".png"})}, root)
            self.assertEqual(raised.exception.errno, transport.errno.ENOSYS)
            self.assertFalse(root.exists())
            self.assertFalse(list(root.parent.glob(f".{root.name}.*.part")))

    def test_multi_artifact_callback_failure_cleans_unpublished_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "job"
            client = MagicMock()
            output = MagicMock()
            output.name = "image.png"
            output.to_file.side_effect = lambda dest: Path(dest).write_bytes(b"image")
            client.run.return_value.get_outputs.return_value = [output]
            with self.assertRaisesRegex(RuntimeError, "persistence failed"):
                transport._run_graph_artifacts(
                    client, {}, {"image": ("9", {".png"})}, root,
                    on_progress=lambda state: (_ for _ in ()).throw(RuntimeError("persistence failed")),
                )
            self.assertFalse(root.exists())
            self.assertFalse(list(root.parent.glob(f".{root.name}.*.part")))

    def test_multi_artifact_transport_uses_exact_nodes_and_commits_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "job"
            client = MagicMock()
            image, caption = MagicMock(), MagicMock()
            image.name, caption.name = "remote.png", "resolved.txt"
            image.to_file.side_effect = lambda dest: Path(dest).write_bytes(b"png")
            caption.to_file.side_effect = lambda dest: Path(dest).write_bytes(b"caption")
            remote = client.run.return_value
            remote.get_outputs.side_effect = lambda node: {
                "9": [image], "character_caption": [caption],
            }[node]

            artifacts = transport._run_graph_artifacts(
                client, {"graph": {}},
                {"image": ("9", {".png"}), "caption": ("character_caption", {".txt"})},
                root,
            )

            self.assertEqual(artifacts, {"image": root / "image.png", "caption": root / "caption.txt"})
            self.assertEqual(artifacts["image"].read_bytes(), b"png")
            self.assertEqual(artifacts["caption"].read_bytes(), b"caption")
            self.assertEqual(remote.get_outputs.call_args_list, [
                (("9",),), (("character_caption",),),
            ])
            self.assertFalse(list(root.glob("*.part")))

    def test_multi_artifact_transport_rejects_wrong_or_missing_output_without_partial_result(self):
        cases = [
            ([], "Missing output"),
            ([MagicMock(name="bad")], "unsupported extension"),
        ]
        for outputs, error in cases:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "job"
                client = MagicMock()
                if outputs:
                    outputs[0].name = "wrong.jpg"
                client.run.return_value.get_outputs.return_value = outputs
                with self.assertRaisesRegex(RuntimeError, error):
                    transport._run_graph_artifacts(
                        client, {}, {"image": ("9", {".png"})}, root)
                self.assertFalse((root / "image.png").exists())
                self.assertFalse(list(root.glob("*.part")) if root.exists() else [])

    def test_multi_artifact_transport_removes_all_partials_when_one_download_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "job"
            client = MagicMock()
            image, caption = MagicMock(), MagicMock()
            image.name, caption.name = "image.png", "caption.txt"
            image.to_file.side_effect = lambda dest: Path(dest).write_bytes(b"png")
            caption.to_file.side_effect = lambda dest: Path(dest).write_bytes(b"")
            remote = client.run.return_value
            remote.get_outputs.side_effect = lambda node: {"9": [image], "caption": [caption]}[node]
            with self.assertRaisesRegex(RuntimeError, "empty"):
                transport._run_graph_artifacts(
                    client, {}, {"image": ("9", {".png"}), "caption": ("caption", {".txt"})}, root)
            self.assertFalse((root / "image.png").exists())
            self.assertFalse((root / "caption.txt").exists())
            self.assertFalse(list(root.glob("*.part")))
