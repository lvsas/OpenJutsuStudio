"""Current viral-direction contract, keeping actual v3 frozen evidence readable."""
import copy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from character_recipe import make_recipe,validate_recipe,validate_current_recipe


class CharacterViralPolicyTests(unittest.TestCase):
    def recipe(self,**changes):
        params=dict(job_id='viral_policy_test',direction='An original adult concierge with an oversized jaw and enormous sculptural silver hair',mode='portrait',trend_id='original',selections={},sampler_seed=11,upsampler_seed=29,upsampler=True)
        return make_recipe(**(params|changes))

    def test_new_policy_defaults_to_lifelike_adults_not_forced_caricature(self):
        r=self.recipe()
        self.assertEqual((r['schema_version'],r['prompt_policy']),(5,'character-v5'))
        text=r['resolved_request']
        self.assertNotIn('unexaggerated natural expression',text)
        self.assertNotIn('caricature',text)
        self.assertNotIn('intentional exaggeration',text)
        self.assertIn('natural adult head-to-body scale',text)
        self.assertIn('unless explicitly requested',text)
        self.assertIn('both feet',text)
        self.assertIn('clear eyes',text)
        self.assertNotIn('three-quarter body',text)

    def test_explicit_overrides_replace_conflicting_idea_details(self):
        r=self.recipe(selections={'hair':'a giant black geometric pompadour'})
        self.assertIn('override conflicting details',r['resolved_request'])
        self.assertIn('hair: a giant black geometric pompadour',r['resolved_request'])
        validate_current_recipe(r)

    def test_exact_v3_fixture_remains_readable_but_is_not_reinterpreted(self):
        old=json.loads((ROOT/'tests/fixtures/character_recipe_v3_frozen.json').read_text())
        self.assertEqual(validate_recipe(old),old)
        self.assertIn('unexaggerated natural expression',old['resolved_request'])
        with self.assertRaisesRegex(ValueError,'earlier policy'):validate_current_recipe(old)
        bad=copy.deepcopy(old);bad['resolved_request']=bad['resolved_request'].replace('unexaggerated natural expression','dramatic expression')
        with self.assertRaises(ValueError):validate_recipe(bad)

    def test_v4_trial_remains_frozen_readable_and_cannot_be_replayed_as_current(self):
        old=json.loads((ROOT/'tests/fixtures/character_recipe_v4_frozen.json').read_text())
        self.assertEqual(validate_recipe(old),old)
        self.assertIn('deliberately caricatured',old['resolved_request'])
        with self.assertRaisesRegex(ValueError,'earlier policy'):validate_current_recipe(old)

    def test_generated_no_prop_default_does_not_ban_clothing_or_authored_props(self):
        self.assertIn('no hand-held or carried props',self.recipe()['resolved_request'])
        self.assertNotIn('no object in the hands or on the body',self.recipe()['resolved_request'])
        r=self.recipe(direction='An original adult stage performer holding a brass key',direction_origin='user_authored')
        self.assertIn('holding a brass key',r['resolved_request'])
        self.assertNotIn('no hand-held or carried props',r['resolved_request'])

    def test_turnaround_retains_four_views_and_exact_graph_seed_bindings(self):
        r=self.recipe(mode='turnaround')
        for view in ('front view','three-quarter view','left profile','back view'):
            self.assertIn(view,r['resolved_request'])
        self.assertEqual(r['graph_template']['18:7']['inputs']['seed'],11)
        self.assertEqual(r['graph_template']['18:11']['inputs']['sampling_mode.seed'],29)


if __name__=='__main__':unittest.main()
