"""A capsule is a historical record: an earlier prompt policy must stay readable.

Regression guard: raising the prompt policy once made every previously completed
take return 409, because the read path re-validated the stored recipe against the
current policy.
"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from h3_capsule import freeze_capsule, get_capsule, replay_inputs
from h3_recipe import bind_frames, digest_json, make_recipe

V2_ONLY = ('source_audio', 'source_audio_conditioning', 'character_description')


class Job:
    def __init__(self, job_id, source, reference, result, recipe):
        self.id, self.engine, self.status = job_id, 'minimax-h3', 'done'
        self.video, self.result = str(source), str(result)
        self.meta = {'h3_reference': str(reference), 'h3_recipe': recipe}


class HistoricalCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.media = Path(self.tmp.name)
        self.source, self.reference, self.result = (self.media / name for name in
                                                    ('source.mp4', 'reference.png', 'result.mp4'))
        for path in (self.source, self.reference, self.result):
            path.write_bytes(b'fixture:' + path.name.encode())
        recipe = bind_frames(make_recipe(source_width=1920, source_height=1080), 56, source_audio=True)
        self.job = Job('a' * 32, self.source, self.reference, self.result, recipe)
        freeze_capsule(self.job, recipe, self.source, self.reference, self.result, self.media)

    def reseal(self, capsule):
        capsule.pop('capsule_id', None)
        capsule['capsule_id'] = 'sha256:' + digest_json(capsule)

    def downgrade_to_policy_v1(self):
        """Rewrite the stored capsule as an earlier-policy record, digests included."""
        capsule = self.job.meta['h3_capsule']
        recipe = {key: value for key, value in capsule['recipe'].items() if key not in V2_ONLY}
        capsule['recipe'] = {**recipe, 'schema_version': 1, 'prompt_policy': 'h3-recast-v1'}
        capsule['recipe_sha256'] = digest_json(capsule['recipe'])
        self.reseal(capsule)
        self.job.meta['h3_recipe'] = copy.deepcopy(capsule['recipe'])

    def test_a_capsule_from_an_earlier_policy_stays_readable(self):
        self.downgrade_to_policy_v1()
        capsule = get_capsule(self.job)
        self.assertEqual(capsule['recipe']['prompt_policy'], 'h3-recast-v1')
        self.assertEqual(capsule['job_id'], self.job.id)

    def test_replay_refuses_an_earlier_policy_with_an_actionable_reason(self):
        self.downgrade_to_policy_v1()
        with self.assertRaises(ValueError) as raised:
            replay_inputs(self.job, self.media)
        self.assertIn('earlier H3 prompt policy', str(raised.exception))

    def test_a_current_capsule_still_replays_and_a_tampered_input_is_rejected(self):
        recipe, source, reference = replay_inputs(self.job, self.media)
        self.assertEqual(recipe['prompt_policy'], 'h3-recast-v2')
        self.assertEqual((source, reference), (self.source, self.reference))
        capsule = self.job.meta['h3_capsule']
        capsule['assets']['source']['sha256'] = 'f' * 64
        self.reseal(capsule)
        with self.assertRaises(ValueError) as raised:
            replay_inputs(self.job, self.media)
        self.assertIn('changed after the capsule was frozen', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
