"""CPU structural contracts; synthetic SDK assets only, no network or tensors."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import h3_latent_graphs as latent
import h3_continuity_graphs as h3

AUDIO = {'__type': 'core/ASSET', 'info': {'id': 'unit-source-audio'}}
REF = {'__type': 'core/ASSET', 'info': {'id': 'unit-reference'}}
MODELS = h3.H3ContinuityModels(*(h3.Weight(n + '.safetensors')
                               for n in ('unet', 'clip', 'video', 'audio')))
OP = 'a' * 32
PROMPT = 'Continue the performance to <Audio 1>.'


def parent(name):
    return h3.NativeH3Parent(name, f'unit/{name}.mp4', 1280, 704, 191, 24,
                             MODELS, 'b' * 64)


def build_latent(mode='forward', **over):
    args = dict(references=[REF], prompt=PROMPT, width=1280, height=704,
                raw_frames=226, seed=42, models=MODELS, parent_clip='unit/a.mp4',
                operation_id=OP, mode=mode,
                second_parent_clip='unit/b.mp4' if mode == 'bridge' else None)
    args.update(over)
    return latent.build_latent_continuity(**args)


def build_recipe(mode='forward', **over):
    parents = () if mode == 'root' else (parent('a'), parent('b')) if mode == 'bridge' else (parent('a'),)
    args = dict(operation_id=OP, seed=42, width=1280, height=704,
                raw_frames=226, models=MODELS, parents=parents)
    args.update(over)
    return h3.build_h3_continuity(mode, REF, PROMPT, **args)


def verify_latent(graph, source_audio=AUDIO, mode='forward'):
    latent._verify(graph, 1280, 704, 226, 42, PROMPT, [REF], OP,
                   mode=mode, parent_clip='unit/a.mp4',
                   second_parent_clip='unit/b.mp4' if mode == 'bridge' else None,
                   source_audio=source_audio)


class SourceAudioGraphTests(unittest.TestCase):
    def assert_audio_path(self, g):
        loaders = [(n, v) for n, v in g.items() if v['class_type'] == 'LoadAudio']
        self.assertEqual(len(loaders), 1)
        load, item = loaders[0]
        self.assertEqual(item['inputs'], {'audio': AUDIO})
        self.assertEqual(g['797']['inputs']['ref_audios.ref_audio_0'], [load, 0])
        lock_id, slot = g['1488:1486']['inputs']['latent_image']
        self.assertEqual(slot, 0)
        lock = g[lock_id]
        self.assertEqual(lock['class_type'], 'MiniMaxH3SetAVNoiseMask')
        self.assertEqual(set(lock['inputs']), {'latent', 'audio_mask'})
        concat_id, slot = lock['inputs']['latent']
        self.assertEqual(slot, 0)
        concat = g[concat_id]
        self.assertEqual(concat['class_type'], 'LTXVConcatAVLatent')
        self.assertEqual(concat['inputs']['video_latent'], ['1228', 1])
        encode_id, slot = concat['inputs']['audio_latent']
        self.assertEqual(slot, 0)
        self.assertEqual(g[encode_id], {'class_type': 'VAEEncodeAudio', 'inputs': {
            'audio': [load, 0], 'vae': ['752:798', 0]}})
        mask_id, slot = lock['inputs']['audio_mask']
        self.assertEqual(slot, 0)
        self.assertEqual(g[mask_id], {'class_type': 'SolidMask', 'inputs': {
            'value': 0.0, 'width': 1, 'height': 1}})
        for n in ('1488:1483', '1488:1484'):
            self.assertEqual(g[n]['inputs']['model'], ['1517', 0])
        self.assertEqual(g['1488:1483']['inputs']['conditioning'], ['1228', 0])
        for n in ('1216', '751:632', '751:633'):
            self.assertEqual(g[n]['inputs']['samples'], ['1488:1486', 1])
        self.assertEqual(g['1216']['inputs']['pins'], ['1228', 2])
        json.dumps(g, allow_nan=False)
        return {load, encode_id, concat_id, mask_id, lock_id}

    def test_distributed_template_really_removes_private_track_and_pixaroma(self):
        g = json.loads(latent.TEMPLATE.read_text())
        self.assertNotIn('3000', g)
        self.assertNotIn('3001', g)
        self.assertNotIn('PixaromaH3AudioSync', {n['class_type'] for n in g.values()})
        self.assertNotIn('LoadAudio', {n['class_type'] for n in g.values()})
        self.assertNotIn('chouxa', json.dumps(g))
        self.assertNotIn('CharSheet_', json.dumps(g))
        for n in ('1488:1483', '1488:1484'):
            self.assertEqual(g[n]['inputs']['model'], ['1517', 0])

    def test_none_is_native_generative_with_no_external_audio_branch(self):
        for builder, modes in ((build_latent, latent.MODES),
                               (build_recipe, ('root', 'forward', 'reverse', 'bridge'))):
            for mode in modes:
                with self.subTest(builder=builder.__name__, mode=mode):
                    implicit = builder(mode)
                    explicit = builder(mode, source_audio=None)
                    g = explicit.graph if isinstance(explicit, h3.ContinuityRecipe) else explicit
                    self.assertEqual(implicit, explicit)
                    self.assertEqual(g['1488:1486']['inputs']['latent_image'], ['1228', 1])
                    self.assertFalse(any('ref_audios.' in f for f in g['797']['inputs']))
                    self.assertFalse(any(n['class_type'] == 'LoadAudio' for n in g.values()))
                    self.assertNotIn('chouxa', json.dumps(g))
                    for n in g.values():
                        if n['class_type'] == 'LoadImage':
                            self.assertEqual(n['inputs']['image'], REF)

    def test_source_reaches_conditioning_and_consumed_av_in_all_modes(self):
        for builder, modes in ((build_latent, latent.MODES),
                               (build_recipe, ('root', 'forward', 'reverse', 'bridge'))):
            for mode in modes:
                for publish in (False, True):
                    with self.subTest(builder=builder.__name__, mode=mode, publish=publish):
                        base = builder(mode, publish_family=publish)
                        result = builder(mode, source_audio=AUDIO, publish_family=publish)
                        g = result.graph if isinstance(result, h3.ContinuityRecipe) else result
                        native = base.graph if isinstance(base, h3.ContinuityRecipe) else base
                        added = self.assert_audio_path(g)
                        # Only the explicit audio target/ref edge changes. Pins,
                        # video masks, model/sampling and publication stay native.
                        expected = copy.deepcopy(g)
                        for n in added:
                            del expected[n]
                        del expected['797']['inputs']['ref_audios.ref_audio_0']
                        expected['1488:1486']['inputs']['latent_image'] = ['1228', 1]
                        if isinstance(result, h3.ContinuityRecipe):
                            expected['1216']['inputs']['metadata'] = native['1216']['inputs']['metadata']
                            h3.validate_consumed_links(g)
                            self.assertFalse(h3.unconsumed_nodes(g))
                        else:
                            verify_latent(g, mode=mode)
                        self.assertEqual(expected, native)

    def test_source_is_canonical_frozen_and_does_not_leak_to_later_builds(self):
        source = copy.deepcopy(AUDIO)
        source['info']['ignored'] = 'not part of the SDK contract'
        r = build_recipe(source_audio=source)
        self.assertEqual(r.as_dict()['source_audio'], AUDIO)
        self.assertEqual(json.loads(r.graph['1216']['inputs']['metadata'])['source_audio'], AUDIO)
        self.assertEqual(r.as_dict()['graph_digest'], h3.canonical_digest(r.graph))
        source['info']['id'] = 'changed'
        self.assert_audio_path(r.graph)
        g = r.graph
        g['source_audio']['inputs']['audio']['info']['id'] = 'mutated-copy'
        self.assert_audio_path(r.graph)
        self.assertNotEqual(r.digest, build_recipe(source_audio={'__type': 'core/ASSET', 'info': {'id': 'other'}}).digest)
        self.assertNotIn('source_audio', build_recipe().as_dict())
        build_latent(source_audio=AUDIO)
        self.assertFalse(any(n['class_type'] == 'LoadAudio' for n in build_latent().values()))

    def test_audio_validation_is_exactly_the_existing_sdk_asset_boundary(self):
        invalid = ('private.wav', '/tmp/private.wav', '', False, [], {},
                   {'__type': 'core/ASSET'}, {'__type': 'other', 'info': {'id': 'x'}},
                   {'__type': 'core/ASSET', 'info': {'id': '../escape'}},
                   {'__type': 'core/ASSET', 'info': {'id': True}})
        for builder in (build_latent, build_recipe):
            for value in invalid:
                with self.subTest(builder=builder.__name__, value=value), self.assertRaises(ValueError):
                    builder(source_audio=value)

    def test_every_audio_edge_and_video_mask_override_is_guarded(self):
        for builder, verify in ((build_latent, verify_latent),
                                (lambda **kw: build_recipe(**kw).graph, h3.validate_consumed_links)):
            base = builder(source_audio=AUDIO)
            nodes = self.assert_audio_path(base)
            mutations = [('797', 'ref_audios.ref_audio_0', ['752:798', 0]),
                         ('797', 'ref_audios.ref_audio_1', ['source_audio', 0]),
                         ('1488:1486', 'latent_image', ['1228', 1]),
                         ('source_audio_lock', 'video_mask', ['source_audio_zero', 0]),
                         ('source_audio_zero', 'value', 1.0),
                         ('source_audio_zero', 'width', 2),
                         ('source_audio', 'audio', 'private.wav')]
            mutations += [(n, f, ['797', 1]) for n in nodes
                          for f, v in base[n]['inputs'].items() if latent._is_ref(v)]
            for n, f, value in mutations:
                g = copy.deepcopy(base)
                g[n]['inputs'][f] = value
                with self.subTest(node=n, field=f), self.assertRaises(ValueError):
                    verify(g)
            for n in nodes:
                g = copy.deepcopy(base)
                del g[n]
                with self.subTest(missing=n), self.assertRaises(ValueError):
                    verify(g)

    def test_recipe_validator_binds_audio_identity_to_frozen_metadata(self):
        base = build_recipe(source_audio=AUDIO).graph
        changed = copy.deepcopy(base)
        changed['source_audio']['inputs']['audio']['info']['id'] = 'another-committed-audio'
        with self.assertRaisesRegex(ValueError, 'frozen recipe metadata'):
            h3.validate_consumed_links(changed)
        # Removing the entire branch must not silently turn a frozen source
        # recipe into native audio generation either.
        changed = copy.deepcopy(base)
        for n in self.assert_audio_path(changed):
            del changed[n]
        del changed['797']['inputs']['ref_audios.ref_audio_0']
        changed['1488:1486']['inputs']['latent_image'] = ['1228', 1]
        with self.assertRaisesRegex(ValueError, 'frozen recipe metadata'):
            h3.validate_consumed_links(changed)

    @unittest.skipUnless(importlib.util.find_spec('comfy_sdk'), 'optional SDK unavailable')
    def test_sdk_factory_accepts_both_compilers_without_submission(self):
        from comfy_sdk.workflows import WorkflowFactory
        for audio in (None, AUDIO):
            for graph in (build_latent(source_audio=audio), build_recipe(source_audio=audio).graph):
                before = copy.deepcopy(graph)
                workflow = WorkflowFactory().from_json(graph)
                self.assertEqual(workflow.json, before)
                self.assertEqual(graph, before)

    def test_preflight_inventory_comes_from_compiled_graph_not_a_second_registry(self):
        import readiness
        g = build_latent(source_audio=AUDIO)
        classes = {n['class_type'] for n in g.values()}
        self.assertTrue({'LoadAudio', 'VAEEncodeAudio', 'LTXVConcatAVLatent',
                         'SolidMask', 'MiniMaxH3SetAVNoiseMask'} <= classes)
        # Inventory is synthetic; omit each new class and prove the existing
        # preflight notices it from this exact graph, without any HTTP request.
        info = {c: {'input': {'required': {}}} for c in classes}
        for node in g.values():
            fields = info[node['class_type']]['input']['required']
            for f, v in node['inputs'].items():
                if f in ('unet_name', 'clip_name', 'vae_name', 'lora_name', 'model_name') and isinstance(v, str):
                    fields.setdefault(f, [[]])[0].append(v)
        for c in ('LoadAudio', 'VAEEncodeAudio', 'MiniMaxH3SetAVNoiseMask', 'SolidMask'):
            partial = {k: v for k, v in info.items() if k != c}
            with patch.object(readiness, '_target_object_info', return_value=partial):
                missing, _ = readiness.missing_dependencies(g)
            self.assertIn(c, missing)

    def test_installed_schema_checker_accepts_sdk_load_audio_before_filename_resolution(self):
        g = build_recipe(source_audio=AUDIO).graph
        # Deliberately minimal synthetic socket schemas. Real GET evidence is a
        # separate manual check; unit tests never depend on the target/media.
        info = {}
        for node in g.values():
            schema = info.setdefault(node['class_type'], {'input': {'optional': {}}, 'output': ['*'] * 10})
            schema['input']['optional'].update({f: ['*'] for f in node['inputs']})
        info['LoadAudio'] = {'input': {'required': {'audio': ['COMBO', {'options': ['unit.wav']}] }}, 'output': ['AUDIO']}
        h3.validate_graph_contracts(g, info)
        invalid = copy.deepcopy(g)
        invalid['source_audio']['inputs']['audio'] = 'unit.wav'
        with self.assertRaises(ValueError):
            h3.validate_graph_contracts(invalid, info)


if __name__ == '__main__':
    unittest.main()
