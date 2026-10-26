"""Optional original-preserving FaceDetailer policy and integration boundaries."""
import copy
import json
from unittest.mock import patch, MagicMock
import unittest
from tests import test_character_pipeline as worker_tests
from tests import test_character_api as api_tests
png = worker_tests.png
from character_recipe import make_recipe, validate_recipe, validate_current_recipe, digest_json
from character_capsule import freeze_capsule, get_capsule, replay_recipe
from character_pipeline import run_character_pipeline

# Captured with the shipped v5 builder before the schema-6 migration.
V5 = {'schema_version': 5,
 'engine': 'flux3-klein-character',
 'prompt_policy': 'character-v5',
 'job_id': 'legacy_v5',
 'raw_direction': 'an original locksmith',
 'direction_origin': 'generated',
 'trend_id': 'original',
 'selections': {'being': 'model_decides',
                'build': 'model_decides',
                'skin_tone': 'model_decides',
                'hair': 'model_decides',
                'face': 'model_decides',
                'outfit': 'model_decides',
                'role': 'model_decides',
                'era': 'model_decides',
                'attitude': 'model_decides'},
 'mode': 'portrait',
 'aspect_ratio': '3:4 (Portrait Standard)',
 'resolved_request': 'Full-length photograph of one life-sized original adult, both feet visible, '
                     'natural camera perspective on a plain mid-grey seamless backdrop under soft '
                     'neutral studio light; unretouched photographic skin texture, real hair and '
                     'fabric, an original locksmith, no text, no letters, no logo, no watermark, '
                     'no border, no frame, exactly one person, nothing cropped, clear eyes, '
                     'coherent facial anatomy; natural adult head-to-body scale and limb lengths '
                     'unless explicitly requested in the character idea; retain the requested '
                     'distinctive hair, face, expression and build with lifelike skin pores and '
                     'individual hair strands, empty hands, no hand-held or carried props',
 'sampler_seed': 11,
 'upsampler_seed': 29,
 'upsampler': True,
 'model_roles': {'unet': 'flux/flux3-image-klein-base-int8-convrot.safetensors',
                 'conditioning_encoder': 'qwen3vl_4b_int8_convrot.safetensors',
                 'vae': 'flux2-vae.safetensors',
                 'prompt_upsampler': 'qwen3.5_9b_flux3_prompt_upsampler_int8_convrot.safetensors'},
 'vendor_workflow_sha256': '69d685d1d9790312a09bf50e71c9b1ff37b4f001273524e8ed48dda61e238f1f',
 'system_prompt_sha256': 'c3c8f951ef38892e4ef1e251c171d2bde8b50068426c92eece76af71ca8e9f69',
 'graph_template': {'9': {'inputs': {'filename_prefix': 'OpenGenjutsu/characters/legacy_v5/image',
                                     'images': ['18:8', 0]},
                          'class_type': 'SaveImage',
                          '_meta': {'title': 'Save Image'}},
                    '19': {'inputs': {'aspect_ratio': '3:4 (Portrait Standard)',
                                      'megapixels': 1,
                                      'multiple': 16},
                           'class_type': 'ResolutionSelector',
                           '_meta': {'title': 'Resolution Selector'}},
                    '25': {'inputs': {'width': 1024,
                                      'height': 1024,
                                      'editor_state': {'__value__': []},
                                      'last_incoming': {'__value__': []}},
                           'class_type': 'CreateBoundingBoxes',
                           '_meta': {'title': 'Create Bounding Boxes'}},
                    '26': {'inputs': {'source': ['27', 0]},
                           'class_type': 'PreviewAny',
                           '_meta': {'title': 'Preview as Text'}},
                    '27': {'inputs': {'prompt': '', 'element': ['25', 2]},
                           'class_type': 'Flux3LayoutPrompt',
                           '_meta': {'title': 'FLUX.3 Layout Prompt'}},
                    '18:17': {'inputs': {'value': 'Full-length photograph of one life-sized '
                                                  'original adult, both feet visible, natural '
                                                  'camera perspective on a plain mid-grey seamless '
                                                  'backdrop under soft neutral studio light; '
                                                  'unretouched photographic skin texture, real '
                                                  'hair and fabric, an original locksmith, no '
                                                  'text, no letters, no logo, no watermark, no '
                                                  'border, no frame, exactly one person, nothing '
                                                  'cropped, clear eyes, coherent facial anatomy; '
                                                  'natural adult head-to-body scale and limb '
                                                  'lengths unless explicitly requested in the '
                                                  'character idea; retain the requested '
                                                  'distinctive hair, face, expression and build '
                                                  'with lifelike skin pores and individual hair '
                                                  'strands, empty hands, no hand-held or carried '
                                                  'props'},
                              'class_type': 'PrimitiveStringMultiline',
                              '_meta': {'title': 'Text (Multiline)'}},
                    '18:12': {'inputs': {'clip_name': 'qwen3.5_9b_flux3_prompt_upsampler_int8_convrot.safetensors',
                                         'type': 'flux3',
                                         'device': 'default'},
                              'class_type': 'CLIPLoader',
                              '_meta': {'title': 'Load CLIP'}},
                    '18:14': {'inputs': {'value': 'You are the prompt upsampler of a text-to-image '
                                                  "model. Expand the user's short request into ONE "
                                                  'detailed, self-contained caption: the exact '
                                                  'text the image model receives. Output only the '
                                                  'caption, with no greetings, explanations, '
                                                  'refusals, questions, Markdown, headings, JSON, '
                                                  'coordinates, ids or angle-bracket tokens, and '
                                                  'no quotes around it. If the input is not '
                                                  'clearly an image request, caption a '
                                                  'visualization of its concept. The request may '
                                                  'begin with a "TARGET CANVAS: W:H" line: compose '
                                                  'for that canvas (wide spreads content sideways, '
                                                  'tall stacks it) and never mention the ratio or '
                                                  'the canvas.\n'
                                                  '\n'
                                                  'Fidelity and planning: keep every explicit '
                                                  'subject, attribute, count, spatial constraint, '
                                                  'style cue and piece of wording; never '
                                                  'contradict, substitute, drop or narrow the '
                                                  'request, and keep an abstract concept abstract. '
                                                  'Decide everything left open as ONE concrete, '
                                                  'consistent plan; never offer alternatives or '
                                                  'hedge. Never re-express a stated constraint '
                                                  'through another mechanism; add camera optics '
                                                  '(depth of field, bokeh, blur) only when asked '
                                                  'for or implied. Without a stated style, plan an '
                                                  'actual photograph and open with the medium '
                                                  'convention ("Full-color outdoor photograph, '
                                                  '...", "Full-color indoor photograph, ...", '
                                                  '"Studio photograph, ...", "Close-up photograph, '
                                                  '..."); keep "Photorealistic" for renders, and '
                                                  'turn "photorealistic" or "realistic" requests '
                                                  'for photos into the photograph convention. Give '
                                                  'a photograph a few ordinary, non-ideal '
                                                  "specifics drawn from the scene's own objects "
                                                  'instead of the stock-photo ideal. Do not invent '
                                                  'names, brands, logos or celebrities; keep '
                                                  'user-named ones. A long request keeps its '
                                                  'content but not its wording: drop appraisal and '
                                                  'sales vocabulary, turn moods into observable '
                                                  'physical facts, and add only new concrete '
                                                  'content with positions. Time of day is '
                                                  'lighting, not rendered text.\n'
                                                  '\n'
                                                  'Caption format: one continuous prose block in '
                                                  'the generative voice, never "this image shows", '
                                                  '"we can see" or "is visible". Lead with medium '
                                                  'and style, then scene, lighting and camera, '
                                                  'then the subjects with concrete colors, '
                                                  'materials and state. Every person in focus gets '
                                                  'an observable profile: ethnicity, gender, age '
                                                  'range, skin tone ("fair skin", "brown skin"), '
                                                  'hair and clothing. Make the layout '
                                                  'reconstructable from words: frame-relative '
                                                  'positions (frame-left, frame-right, upper, '
                                                  'lower, foreground, midground, background), '
                                                  'sentence-initial anchors ("On the left, ...", '
                                                  '"In the background, ..."), relations (holds, '
                                                  'faces, behind) and a consistent order; describe '
                                                  'up to about ten instances one by one, beyond '
                                                  'that give the exact count and arrangement. '
                                                  'Out-of-focus or distant planes are shapes, '
                                                  'colors and silhouettes, never identities or '
                                                  'readable text, and the background takes about a '
                                                  'sixth of the caption. Be definite: no hedging '
                                                  'adverbs, no quality or emotion judgments, no '
                                                  'closing sentence about mood; state negations as '
                                                  'what is present. Rendered text: transcribe '
                                                  'every wording verbatim inside double quotes in '
                                                  'its original language and script, keep the line '
                                                  'breaks of multi-line text, and give its '
                                                  'typography, color and placement; author '
                                                  'concrete, domain-correct wording when the '
                                                  'request needs text it does not supply, and name '
                                                  'canonical structures (calendar, keyboard, '
                                                  'periodic table) exactly with their full layout. '
                                                  'All prose is English; only quoted text keeps '
                                                  'its language. Typical length is 100 to 350 '
                                                  'words, more for complex scenes.\n'
                                                  '\n'
                                                  'Output only the caption.\n'},
                              'class_type': 'PrimitiveStringMultiline',
                              '_meta': {'title': 'Text (System prompt)'}},
                    '18:11': {'inputs': {'prompt': ['18:17', 0],
                                         'max_length': 3584,
                                         'sampling_mode': 'on',
                                         'sampling_mode.temperature': 1,
                                         'sampling_mode.top_k': 1,
                                         'sampling_mode.top_p': 0.95,
                                         'sampling_mode.min_p': 0,
                                         'sampling_mode.repetition_penalty': 1,
                                         'sampling_mode.seed': 29,
                                         'sampling_mode.presence_penalty': 1.5,
                                         'thinking': False,
                                         'use_default_template': True,
                                         'mtp': 'off',
                                         'clip': ['18:12', 0],
                                         'system_prompt': ['18:14', 0]},
                              'class_type': 'TextGenerate',
                              '_meta': {'title': 'Generate Text'}},
                    '18:1': {'inputs': {'unet_name': 'flux/flux3-image-klein-base-int8-convrot.safetensors',
                                        'weight_dtype': 'default'},
                             'class_type': 'UNETLoader',
                             '_meta': {'title': 'Load Diffusion Model'}},
                    '18:4': {'inputs': {'text': ['18:13', 0], 'clip': ['18:2', 0]},
                             'class_type': 'CLIPTextEncode',
                             '_meta': {'title': 'Positive Prompt'}},
                    '18:2': {'inputs': {'clip_name': 'qwen3vl_4b_int8_convrot.safetensors',
                                        'type': 'flux3',
                                        'device': 'default'},
                             'class_type': 'CLIPLoader',
                             '_meta': {'title': 'Load CLIP'}},
                    '18:7': {'inputs': {'seed': 11,
                                        'steps': 50,
                                        'cfg': 3.5,
                                        'sampler_name': 'euler',
                                        'scheduler': 'simple',
                                        'denoise': 1,
                                        'model': ['18:1', 0],
                                        'positive': ['18:4', 0],
                                        'negative': ['18:5', 0],
                                        'latent_image': ['18:6', 0]},
                             'class_type': 'KSampler',
                             '_meta': {'title': 'KSampler'}},
                    '18:3': {'inputs': {'vae_name': 'flux2-vae.safetensors'},
                             'class_type': 'VAELoader',
                             '_meta': {'title': 'Load VAE'}},
                    '18:13': {'inputs': {'source': ['18:16', 0]},
                              'class_type': 'PreviewAny',
                              '_meta': {'title': 'Preview as Text'}},
                    '18:16': {'inputs': {'switch': True,
                                         'on_false': ['18:17', 0],
                                         'on_true': ['18:11', 0]},
                              'class_type': 'ComfySwitchNode',
                              '_meta': {'title': 'If/Else Switch'}},
                    '18:6': {'inputs': {'width': ['19', 0], 'height': ['19', 1], 'batch_size': 1},
                             'class_type': 'EmptyFlux2LatentImage',
                             '_meta': {'title': 'Empty Flux 2 Latent'}},
                    '18:5': {'inputs': {'text': '', 'clip': ['18:2', 0]},
                             'class_type': 'CLIPTextEncode',
                             '_meta': {'title': 'Negative Prompt (empty = reference default)'}},
                    '18:8': {'inputs': {'samples': ['18:7', 0], 'vae': ['18:3', 0]},
                             'class_type': 'VAEDecode',
                             '_meta': {'title': 'VAE Decode'}},
                    'character_caption': {'class_type': 'SaveText',
                                          'inputs': {'text': ['18:13', 0],
                                                     'filename_prefix': 'OpenGenjutsu/characters/legacy_v5/caption',
                                                     'format': 'txt'},
                                          '_meta': {'title': 'SAVE — Character resolved caption'}}},
 'graph_sha256': 'a6ed4083e39dbc946b36e6ac5a883440535f877311289095940a8f83e1b84c29'}


def refined(job_id="character_worker_1", **kw):
    return make_recipe(job_id=job_id, direction="an original locksmith", mode="portrait",
                       trend_id="original", selections={}, sampler_seed=11, upsampler_seed=29,
                       upsampler=True, face_refine=True, **kw)


class RefinePolicyTests(unittest.TestCase):
    def test_captured_v5_is_readable_and_not_current(self):
        self.assertEqual(validate_recipe(V5), V5)
        with self.assertRaisesRegex(ValueError, "earlier policy"):
            validate_current_recipe(V5)

    def test_schema6_graph_preserves_base_and_freezes_detail_policy(self):
        recipe = refined()
        self.assertEqual((recipe["schema_version"], recipe["prompt_policy"]), (6, "character-v6"))
        self.assertIs(recipe["face_refine"], True)
        graph = recipe["graph_template"]
        from character_graphs import build_character_graph
        base = build_character_graph(recipe["resolved_request"], 11, recipe["aspect_ratio"], True, recipe["job_id"], upsampler_seed=29)
        self.assertEqual({k:v for k,v in graph.items() if k in base}, base)
        self.assertEqual(set(graph) - set(base), {"character_bbox", "character_sam", "character_detail", "character_refined"})
        self.assertEqual(graph["9"]["inputs"]["images"], ["18:8", 0])
        self.assertEqual(graph["character_refined"]["inputs"]["images"], ["character_detail", 0])
        self.assertNotEqual(graph["9"]["inputs"]["filename_prefix"], graph["character_refined"]["inputs"]["filename_prefix"])
        inputs = graph["character_detail"]["inputs"]
        for key, node in {"image":"18:8", "model":"18:1", "clip":"18:2", "vae":"18:3", "positive":"18:4", "negative":"18:5"}.items():
            self.assertEqual(inputs[key], [node, 0])
        self.assertEqual([inputs[k] for k in ("guide_size", "max_size", "denoise", "seed", "steps", "cfg", "sampler_name", "scheduler")],
                         [768, 1024, .28, 11, 50, 3.5, "euler", "simple"])
        self.assertEqual(recipe["model_roles"]["face_detector"], "bbox/face_yolov8m.pt")
        self.assertEqual(recipe["model_roles"]["face_sam"], "sam_vit_b_01ec64.pth")
        broken = copy.deepcopy(recipe)
        broken["graph_template"]["character_detail"]["inputs"]["denoise"] = .18
        broken["graph_sha256"] = digest_json(broken["graph_template"])
        with self.assertRaisesRegex(ValueError, "graph"):
            validate_recipe(broken)
        missing_roles = copy.deepcopy(recipe)
        missing_roles["model_roles"].pop("face_detector")
        with self.assertRaisesRegex(ValueError, "model-role"):
            validate_recipe(missing_roles)
        missing_flag = copy.deepcopy(recipe); missing_flag.pop("face_refine")
        with self.assertRaises(ValueError):
            validate_recipe(missing_flag)
        for value in (0, 1, "true", None, [], {}):
            broken = copy.deepcopy(recipe); broken["face_refine"] = value
            with self.assertRaises(ValueError):
                validate_recipe(broken)


class RefineWorkerTests(unittest.TestCase):
    setUp = worker_tests.CharacterPipelineTests.setUp
    _artifacts = worker_tests.CharacterPipelineTests._artifacts

    def test_refined_worker_retrieves_and_freezes_both_images(self):
        self.recipe = refined(); self.job.meta["character_recipe"] = self.recipe
        captured = []
        def artifacts(c, g, requests, folder, on_progress):
            captured.append(requests)
            result = self._artifacts(folder)
            result["base_image"] = folder / "base_image.png"
            result["base_image"].write_bytes(png())
            return result
        with patch("character_pipeline.make_client", return_value=MagicMock()), patch("character_pipeline._run_graph_artifacts", side_effect=artifacts):
            run_character_pipeline(self.job, {"recipe":self.recipe, "media_dir":self.media})
        self.assertEqual(self.job.status, "done", self.job.error)
        self.assertEqual(captured, [{"image":("character_refined", {".png"}), "base_image":("9", {".png"}), "caption":("character_caption", {".txt"})}])
        frozen = get_capsule(self.job)
        self.assertEqual(frozen["schema_version"], 6)
        self.assertEqual(set(frozen["assets"]), {"image", "caption", "base_image"})
        self.assertEqual(replay_recipe(self.job, self.media), self.recipe)
        base = __import__('pathlib').Path(self.job.meta["character_base_image"])
        base.write_bytes(png(882, 1184))
        with self.assertRaisesRegex(ValueError, "changed"):
            replay_recipe(self.job, self.media)

    def test_missing_or_invalid_base_cannot_succeed(self):
        for payload in (None, b"bad", png(882,1184)):
            self.recipe = refined(); self.job.meta["character_recipe"] = self.recipe
            def artifacts(c, g, r, folder, on_progress):
                result = self._artifacts(folder)
                if payload is not None:
                    result["base_image"] = folder / "base_image.png"
                    result["base_image"].write_bytes(payload)
                return result
            with patch("character_pipeline.make_client", return_value=MagicMock()), patch("character_pipeline._run_graph_artifacts", side_effect=artifacts):
                run_character_pipeline(self.job, {"recipe":self.recipe, "media_dir":self.media})
            self.assertEqual(self.job.status, "error")
            self.assertNotIn("character_base_image", self.job.meta)
            self.assertNotIn("character_capsule", self.job.meta)
            self.assertFalse((self.media / f"character-{self.job.id}").exists())


class RefineAPITests(unittest.TestCase):
    setUp = api_tests.CharacterAPITests.setUp
    submit = api_tests.CharacterAPITests.submit
    completed = api_tests.CharacterAPITests.completed

    def test_strict_flag_and_required_graph_readiness(self):
        for value in (1, 0, "false", None, [], {}):
            self.assertEqual(self.submit(face_refine=value).status_code, 422)
        self.ready.assert_not_called()
        self.assertEqual(self.submit(face_refine=True).status_code, 202)
        job, opts = self.dispatch.call_args.args
        self.assertIs(self.client.get(f"/api/characters/jobs/{job.id}").json()["face_refine"], True)
        self.ready.assert_called_once_with(required_graph=opts["recipe"]["graph_template"])
        self.ready.reset_mock()
        self.assertEqual(self.submit().status_code, 202)
        self.ready.assert_called_once_with()

    def test_base_route_is_opt_in_done_contained_png_and_replay_preserves_flag(self):
        self.assertEqual(self.submit(face_refine=True).status_code, 202)
        job, opts = self.dispatch.call_args.args
        url = f"/api/characters/jobs/{job.id}/base-image"
        self.assertEqual(self.client.get(url).status_code, 409)
        image, base, caption = [self.media / name for name in ("refined.png", "base.png", "caption.txt")]
        image.write_bytes(png()); base.write_bytes(png()); caption.write_text("caption")
        job.status, job.result = "done", str(image)
        job.meta.update(character_base_image=str(base), character_caption=str(caption))
        freeze_capsule(job, opts["recipe"], image, caption, self.media); job.save()
        result = self.client.get(url)
        self.assertEqual(result.status_code, 200); self.assertEqual(result.headers["content-type"], "image/png")
        self.assertEqual(result.content, base.read_bytes())
        self.assertEqual(self.client.post(f"/api/characters/jobs/{job.id}/replay").status_code, 202)
        self.assertIs(self.dispatch.call_args.args[1]["recipe"]["face_refine"], True)
        for path in (None, str(self.root / "escape.png"), str(caption), str(image)):
            job.meta["character_base_image"] = path; job.save()
            self.assertEqual(self.client.get(url).status_code, 409)
        normal = self.completed(); normal.meta["character_base_image"] = str(base); normal.save()
        self.assertEqual(self.client.get(f"/api/characters/jobs/{normal.id}/base-image").status_code, 409)


class RefineRegistrationTests(unittest.TestCase):
    def test_default_readiness_and_explicit_graph_forwarding(self):
        from character_studio_app import _character_readiness
        with patch("readiness.check_readiness", return_value={"ready": True}) as check:
            _character_readiness()
            default = check.call_args.kwargs["required_graph"]
            self.assertNotIn("character_detail", default)
            graph = refined()["graph_template"]
            _character_readiness(required_graph=graph)
            self.assertIs(check.call_args.kwargs["required_graph"], graph)


class RefineEvidenceTests(unittest.TestCase):
    setUp = worker_tests.CharacterPipelineTests.setUp

    def test_all_historical_versions_remain_readable_without_upgrade(self):
        from tests.character_recipe_fixtures import v1_recipe_fixture, v2_recipe_fixture
        from pathlib import Path
        recipes = [v1_recipe_fixture(), v2_recipe_fixture(), V5]
        for version in (3, 4):
            recipes.append(json.loads((worker_tests.ROOT / "tests" / "fixtures" / f"character_recipe_v{version}_frozen.json").read_text()))
        from core import Job
        self.media.mkdir()
        image, caption = self.media / "historical.png", self.media / "historical.txt"
        image.write_bytes(png()); caption.write_text("Historical caption")
        for recipe in recipes:
            with self.subTest(version=recipe["schema_version"]):
                self.assertEqual(validate_recipe(recipe), recipe)
                job = Job(id=recipe["job_id"], engine=recipe["engine"], status="done", result=str(image), meta={"character_caption":str(caption)})
                frozen = freeze_capsule(job, recipe, image, caption, self.media)
                self.assertEqual(frozen["schema_version"], 2)
                self.assertEqual(get_capsule(job)["recipe"], recipe)
                self.assertNotIn("face_refine", recipe)
                with self.assertRaisesRegex(ValueError, "earlier policy"):
                    replay_recipe(job, self.media)

    def test_refined_capsule_rejects_missing_base_and_bad_metadata(self):
        self.media.mkdir()
        image, caption, base = [self.media / name for name in ("final.png", "caption.txt", "base.png")]
        image.write_bytes(png()); caption.write_text("caption"); base.write_bytes(png())
        self.recipe = refined(); self.job.result = str(image)
        self.job.meta["character_caption"] = str(caption)
        with self.assertRaises(ValueError):
            freeze_capsule(self.job, self.recipe, image, caption, self.media)
        for path in (image, caption, self.media.parent / "escape.png"):
            self.job.meta["character_base_image"] = str(path)
            with self.assertRaises(ValueError):
                freeze_capsule(self.job, self.recipe, image, caption, self.media)
        self.job.meta["character_base_image"] = str(base)
        frozen = freeze_capsule(self.job, self.recipe, image, caption, self.media)
        self.job.status = "done"
        for malformed in (None, {}, {**frozen["assets"]["base_image"], "suffix":".txt"}, {**frozen["assets"]["base_image"], "size_bytes":0}):
            broken = copy.deepcopy(frozen); broken["assets"]["base_image"] = malformed
            broken.pop("capsule_id"); broken["capsule_id"] = "sha256:" + digest_json(broken)
            self.job.meta["character_capsule"] = broken
            with self.assertRaisesRegex(ValueError, "artifact"):
                get_capsule(self.job)


class RefineReadinessRefusalTests(unittest.TestCase):
    setUp = api_tests.CharacterAPITests.setUp
    submit = api_tests.CharacterAPITests.submit

    def test_missing_refine_capability_never_dispatches(self):
        self.ready.return_value = {"ready":False, "issues":["FaceDetailer missing"]}
        response = self.submit(face_refine=True)
        self.assertEqual(response.status_code, 503)
        self.assertIn("FaceDetailer missing", response.text)
        self.dispatch.assert_not_called()
        self.assertIn("character_detail", self.ready.call_args.kwargs["required_graph"])

