"""Face-only conditioning regressions; isolated CPU fixtures, no worker or GPU."""
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import unittest
from character_recipe import make_recipe, validate_recipe, validate_frozen_recipe, validate_current_recipe, digest_json
from tests.character_recipe_fixtures import direction_facts_fixture, direction_wording_fixture


def recipe(**overrides):
    payload=dict(job_id="face_prompt_v2", direction=direction_wording_fixture(),
                 direction_facts=direction_facts_fixture(), mode="full_body", trend_id="original",
                 selections={"face":"a square jaw, amber eyes and a dense walrus moustache",
                             "outfit":"a neon cyan racing jacket", "hair":"a purple sculptural crest",
                             "attitude":"arms folded and feet wide apart"},
                 sampler_seed=11, upsampler_seed=29, upsampler=False, face_refine=True)
    payload.update(overrides)
    return make_recipe(**payload)


class FacePromptTests(unittest.TestCase):
    def test_second_pass_has_its_own_face_only_encoder_and_leaves_the_base_unchanged(self):
        refined=recipe(); plain=recipe(face_refine=False)
        self.assertEqual(refined["face_refine_policy"],2)
        graph=refined["graph_template"]
        self.assertEqual(graph["character_detail"]["inputs"]["positive"],["character_face_positive",0])
        positive=graph["character_face_positive"]
        self.assertEqual(positive["class_type"],"CLIPTextEncode")
        self.assertEqual(positive["inputs"]["clip"],["18:2",0])
        self.assertEqual(positive["inputs"]["text"],refined["face_refine_prompt"])
        prompt=refined["face_refine_prompt"]
        self.assertIn("square jaw, amber eyes and a dense walrus moustache",prompt)
        self.assertIn("expression",prompt)
        for unwanted in ("cyan", "racing", "purple", "crest", "arms", "feet", "full-length", "backdrop", "profile view"):
            self.assertNotIn(unwanted,prompt.lower())
        for node,value in plain["graph_template"].items():self.assertEqual(graph[node],value)
        self.assertNotIn("face_refine_prompt",plain)
        self.assertNotIn("face_refine_policy",plain)

    def test_face_snapshot_and_explicit_skin_tone_are_used_without_rewriting(self):
        facts=direction_facts_fixture()
        first=recipe(selections={"skin_tone":"warm brown skin"})
        second=recipe(selections={"skin_tone":"warm brown skin"},upsampler=True)
        self.assertIn(facts["face"],first["face_refine_prompt"])
        self.assertIn("warm brown skin",first["face_refine_prompt"])
        self.assertEqual(first["face_refine_prompt"],second["face_refine_prompt"])
        self.assertNotIn(facts["outfit"],first["face_refine_prompt"])

    def test_authored_prose_is_not_blindly_injected_into_the_face_crop(self):
        value=recipe(direction="An adult in an electric yellow jacket and blue trousers.",
                     direction_facts=None,selections={},direction_origin="user_authored")
        self.assertNotIn("yellow",value["face_refine_prompt"])
        self.assertNotIn("trousers",value["face_refine_prompt"])
        self.assertIn("identity",value["face_refine_prompt"])

    def test_rehashed_prompt_or_encoder_substitution_is_rejected(self):
        for target in ("prompt","encoder","policy"):
            broken=recipe()
            if target=="prompt":broken["face_refine_prompt"]+=" a neon jacket"
            if target=="encoder":broken["graph_template"]["character_detail"]["inputs"]["positive"]=["18:4",0]
            if target=="policy":broken["face_refine_policy"]=True
            broken["graph_sha256"]=digest_json(broken["graph_template"])
            for validator in (validate_recipe,validate_frozen_recipe):
                with self.subTest(target=target,validator=validator.__name__),self.assertRaises(ValueError):validator(broken)

    def test_captured_legacy_full_prompt_refine_remains_readable_but_not_replayed_as_current(self):
        legacy=json.loads((Path(__file__).parent/"fixtures/character_recipe_v7_refine_legacy.json").read_text())
        self.assertEqual(legacy["graph_template"]["character_detail"]["inputs"]["positive"],["18:4",0])
        self.assertEqual(validate_recipe(legacy),legacy)
        validate_frozen_recipe(legacy)
        with self.assertRaisesRegex(ValueError,"earlier|refin"):
            validate_current_recipe(legacy)
