"""Readonly capability refusals use real boundary arithmetic, never generation."""
import unittest
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import continuity_composer as composer
from h3_av_state import AVState, audio_ticks


def family(width=1280, identity='one'):
    return SimpleNamespace(artifacts=SimpleNamespace(to_manifest=lambda: {'context':
        {'width':width,'height':704,'fps':24,'self_id':identity}}))


class CapabilityReasonsTests(unittest.TestCase):
    def check(self, mode, states, code, families=None):
        with TemporaryDirectory() as root:
            work=Path(root)/'untouched'
            app=FastAPI();app.include_router(composer.create_router(lambda:work))
            with patch.object(composer,'get_validated_family',side_effect=families or [family()]*len(states)), \
                 patch.object(composer,'state_from_family',side_effect=states), \
                 patch('readiness._target_object_info',return_value={}), TestClient(app) as client:
                response=client.get('/api/continuity/composer-readiness',params={
                    'mode':mode,'take_id':'a'*32,'second_take_id':'b'*32})
            self.assertEqual(response.status_code,200)
            result=response.json()
            self.assertEqual(result['reason_code'],code)
            self.assertEqual(result['available'],code is None)
            self.assertNotIn(str(work),response.text)
            self.assertFalse(work.exists())
            return result

    def test_exact_head35_is_refused_before_duration_projection(self):
        with patch.object(composer,'prepare_operation',side_effect=AssertionError('must not project')):
            self.check('prepend',[AVState(158,35,123,263,Fraction(0))],'unaligned_start')

    def test_audio64_of65_and_short_source(self):
        self.check('forward',[AVState(158,35,123,263,Fraction(-333333,1000000))],'audio_window')
        self.check('forward',[AVState(56,35,21,93,Fraction(0))],'short_source')

    def test_geometry_and_timing_are_distinct(self):
        self.check('bridge',[], 'geometry_mismatch',[family(),family(704,'two')])
        self.check('prepend',[None],'timing_unavailable')
        self.check('prepend',[ValueError('/private/SECRET prompt')],'timing_unavailable')
        self.check('prepend',[AVState(192,0,192,320,Fraction(0))],None)

    def test_ready_root_and_phase_conflict(self):
        self.check('root',[],None)
        self.check('bridge',[AVState(56,0,56,audio_ticks(56),Fraction(0)),
            AVState(192,0,192,320,Fraction(0))],'audio_phase_conflict',
            [family(),family(identity='two')])

    def test_root_target_failure_does_not_blame_a_nonexistent_saved_take(self):
        with TemporaryDirectory() as root:
            work=Path(root)/'untouched'
            app=FastAPI();app.include_router(composer.create_router(lambda:work))
            with patch('readiness._target_object_info',side_effect=OSError('/private/SECRET')), TestClient(app) as client:
                response=client.get('/api/continuity/composer-readiness',params={'mode':'root'})
            self.assertEqual(response.json()['reason_code'],'target_unavailable')
            self.assertNotIn('SECRET',response.text)
            self.assertFalse(work.exists())

    def test_unverified_family_is_not_timing_failure(self):
        self.check('forward',[],'state_unverified',[ValueError('/private/SECRET')])
