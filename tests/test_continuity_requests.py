"""The Forward request is a server input, not a graph or a filesystem path.

The browser supplies an intention. The operation ID, the compiled graph and the
compute target stay server-side, so these cases pin the exact refusal surface.
"""
import unittest

from pydantic import ValidationError

from continuity_requests import ForwardRequest


class ForwardRequestTests(unittest.TestCase):
    def valid(self):
        return {"request_id": "a" * 32, "prompt": "The character walks onward.",
                "seed": 41, "raw_frames": 56}

    def test_accepts_explicit_request_without_rewriting_prompt(self):
        value = self.valid()
        value["prompt"] = "  The character walks onward.  "
        self.assertEqual(ForwardRequest(**value).prompt, value["prompt"])

    def test_refuses_client_graph_path_target_and_unknown_fields(self):
        for field in ("graph", "path", "target", "backend", "parent_take_id"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                ForwardRequest(**(self.valid() | {field: "not allowed"}))

    def test_refuses_bad_identifiers_boolean_seed_and_invalid_grid(self):
        for patch in ({"request_id": "../outside"}, {"seed": True},
                      {"seed": -1}, {"raw_frames": 55}, {"raw_frames": True},
                      {"prompt": "   "}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                ForwardRequest(**(self.valid() | patch))


if __name__ == "__main__":
    unittest.main()
