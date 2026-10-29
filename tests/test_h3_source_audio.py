"""Source-song timing is exact input preparation, not a lip-sync claim."""
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import patch

from h3_av_state import AVState, child_state


class SourceAudioTimingTests(unittest.TestCase):
    def test_reference_window_matches_the_verified_9cb_native_grid(self):
        from h3_source_audio import audio_window
        parent = AVState(362, 0, 362, 603, Fraction(0))
        window = audio_window(parent, 226, Fraction(14))
        self.assertEqual(window['raw_video_start'], '659/24')
        self.assertEqual(window['start_sample'], 878400)
        self.assertEqual(window['sample_count'], 301600)
        self.assertEqual(Fraction(window['start_sample'], 32000), Fraction('27.450'))
        self.assertEqual(Fraction(window['start_sample'] + window['sample_count'], 32000), Fraction('36.875'))

    def test_child_uses_its_raw_origin_not_delivered_duration(self):
        from h3_source_audio import audio_window
        parent = AVState(362, 0, 362, 603, Fraction(0))
        first = audio_window(parent, 226, Fraction(14))
        next_window = audio_window(child_state(parent, 226), 277, Fraction(first['raw_video_start']))
        self.assertEqual(Fraction(next_window['raw_video_start']), Fraction('35.25'))
        self.assertLessEqual(abs(Fraction(next_window['start_sample'], 32000) - Fraction('35.25')), Fraction(1, 32000))
        self.assertEqual(next_window['sample_count'], 462 * 800)

    def test_no_dead_end_duration_can_be_prepared(self):
        from h3_source_audio import audio_window
        parent = AVState(362, 0, 362, 603, Fraction(0))
        with self.assertRaises(ValueError):
            audio_window(parent, 158, Fraction(14))

    def test_original_track_must_cover_the_entire_window(self):
        from h3_source_audio import require_audio_capacity
        window = {'start_sample': 878400, 'sample_count': 301600}
        require_audio_capacity(window, Fraction('36.875'))
        with self.assertRaisesRegex(ValueError, 'soundtrack'):
            require_audio_capacity(window, Fraction('36.874'))

    def test_extract_is_real_cpu_preprocessing_with_exact_sample_count(self):
        from h3_source_audio import extract_audio_window
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'synthetic.wav'
            target = Path(folder) / 'prepared.wav'
            with wave.open(str(source), 'wb') as wav:
                wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(32000)
                wav.writeframes(b'\x01\x00\x02\x00' * 32000)
            extract_audio_window(source, target, {'start_sample': 800, 'sample_count': 2400})
            with wave.open(str(target), 'rb') as wav:
                self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getnframes()), (32000, 2, 2400))
            self.assertTrue(source.is_file())

    def test_no_padding_when_the_decoded_track_is_too_short(self):
        from h3_source_audio import extract_audio_window
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'synthetic.wav'
            with wave.open(str(source), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(32000)
                wav.writeframes(b'\x00\x00' * 800)
            with self.assertRaisesRegex(ValueError, 'soundtrack'):
                extract_audio_window(source, Path(folder) / 'short.wav', {'start_sample': 0, 'sample_count': 1600})


class FrozenSourceAudioTests(unittest.TestCase):
    def context(self):
        return {'policy': 'original-source-v1', 'source_job': 'a' * 32,
                'source_sha256': 'b' * 64, 'raw_video_start': '659/24',
                'start_sample': 878400, 'sample_count': 301600}

    def test_attempt_freezes_window_and_reuses_it_for_refine_and_sample(self):
        import continuity_attempts as attempts
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            context = self.context()
            record, created = attempts.create_or_get(root, take_id='c' * 32,
                request_id='d' * 32, prompt='Continue the same song.', raw_frames=226,
                seeds=[42], frozen_audio_context=context)
            context['start_sample'] = 0
            refine = Mock(return_value='Prepared continuation.')
            submit = Mock(return_value='e' * 32)
            done = attempts.run(root, record['attempt_id'], refine=refine, submit=submit)
            self.assertTrue(created)
            self.assertEqual(done['status'], 'done')
            self.assertEqual(refine.call_args.kwargs['audio_context'], self.context())
            self.assertEqual(refine.call_args.kwargs['raw_frames'], 226)
            self.assertEqual(submit.call_args.kwargs['audio_context'], self.context())
            self.assertNotIn('raw_frames', submit.call_args.kwargs)
            self.assertNotIn('frozen_audio_context', attempts.public(done))

    def test_native_audio_absence_is_explicitly_frozen_in_new_records(self):
        import continuity_attempts as attempts
        with tempfile.TemporaryDirectory() as root:
            record, _ = attempts.create_or_get(root, take_id='c' * 32, request_id='d' * 32,
                prompt='Continue.', raw_frames=226, seeds=[42])
            self.assertIn('frozen_audio_context', record)
            self.assertIsNone(attempts.load(root, record['attempt_id'])['frozen_audio_context'])

    def test_invalid_soundtrack_context_cannot_create_a_record(self):
        import continuity_attempts as attempts
        with tempfile.TemporaryDirectory() as root:
            invalid = self.context() | {'source_job': '../private'}
            with self.assertRaises(ValueError):
                attempts.create_or_get(root, take_id='c' * 32, request_id='d' * 32,
                    prompt='Continue.', raw_frames=226, seeds=[42], frozen_audio_context=invalid)
            self.assertEqual(list(Path(root).iterdir()), [])


class SourceAudioCostBoundaryTests(unittest.TestCase):
    def context(self):
        return FrozenSourceAudioTests().context()

    def hunt(self, checked):
        import ast
        from types import SimpleNamespace
        from unittest.mock import Mock, MagicMock
        source = Path(__file__).resolve().parents[1] / 'src/app.py'
        function = next(n for n in ast.parse(source.read_text()).body
                        if isinstance(n, ast.FunctionDef) and n.name == '_hunt_refine')
        client = MagicMock()
        env = {'core': SimpleNamespace(WORK=Path('/synthetic-work')), 'Path': Path,
               'parent_references': lambda *args: [Path('/synthetic-reference.png')],
               '_continuity_models': lambda: 'synthetic-models',
               'preflight_continuation': Mock(return_value=checked),
               'precheck_source_audio': Mock(), 'make_client': Mock(return_value=client),
               'refine_continuation_prompt': Mock(return_value='synthetic prepared text')}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), env)
        return env

    def test_changed_or_disappeared_or_newly_added_track_refuses_before_all_costs(self):
        context = self.context()
        for frozen, checked in ((context, context | {'start_sample': 0}),
                                (context, None), (None, context)):
            with self.subTest(frozen=frozen, checked=checked):
                env = self.hunt(checked)
                with patch('h3_source_audio.prepare_source_audio') as prepare:
                    with self.assertRaisesRegex(ValueError, 'frozen'):
                        env['_hunt_refine']('Continue.', 'a' * 32,
                            audio_context=frozen, raw_frames=226)
                prepare.assert_not_called()
                for name in ('precheck_source_audio', 'make_client', 'refine_continuation_prompt'):
                    env[name].assert_not_called()

    def test_matching_frozen_track_prepares_before_client_and_refines_once(self):
        from unittest.mock import Mock
        context = self.context()
        env = self.hunt(context)
        order = Mock()
        order.attach_mock(env['precheck_source_audio'], 'prepare')
        order.attach_mock(env['make_client'], 'client')
        env['_hunt_refine']('Continue.', 'a' * 32, audio_context=context, raw_frames=226)
        self.assertEqual([call[0] for call in order.mock_calls[:2]], ['prepare', 'client'])
        env['refine_continuation_prompt'].assert_called_once()
        self.assertTrue(env['refine_continuation_prompt'].call_args.kwargs['preserve_source_audio'])

    def test_sampling_also_refuses_a_track_added_after_frozen_absence(self):
        import continuity_pipeline as pipeline
        from types import SimpleNamespace
        from unittest.mock import Mock
        context = {'width': 1280, 'height': 704}
        request = SimpleNamespace(raw_frames=226, seed=42, prompt='Continue.')
        client, inventory = Mock(), Mock()
        with patch.object(pipeline, '_checked_anchors', return_value=((object(),), (context,), None)), \
             patch.object(pipeline, 'source_audio_context', return_value=self.context()):
            with self.assertRaisesRegex(ValueError, 'frozen'):
                pipeline.submit_continuation('/synthetic-work', ('a' * 32,), request,
                    mode='forward', client=client, models=object(), references=[],
                    target_fingerprint='f' * 64, work_root='/synthetic-ops',
                    audio_context=None, inventory=inventory)
        client.assets.from_file.assert_not_called()
        client.run.assert_not_called()
        client.submit.assert_not_called()
        inventory.assert_not_called()

    def test_direct_runner_checks_real_audio_before_client_or_refiner(self):
        import subprocess
        import continuity_forward_api as api
        from continuity_requests import ForwardRequest
        from unittest.mock import Mock
        for failure in (ValueError('The decoded original soundtrack is too short.'),
                        subprocess.CalledProcessError(1, ['synthetic-decoder'])):
            with self.subTest(failure=type(failure).__name__):
                factory = Mock()
                runner = api.make_forward_runner(client_factory=factory,
                    models_factory=lambda: 'synthetic-models', fingerprint='f' * 64,
                    work_root='/synthetic-ops', preflight=lambda *a, **k: self.context())
                with patch.object(api, 'parent_references', return_value=[Path('/synthetic-ref.png')]), \
                     patch('h3_source_audio.prepare_source_audio', side_effect=failure), \
                     patch.object(api, '_extract_continuation_frame') as scene, \
                     patch.object(api, 'refine_continuation_prompt') as refine, \
                     patch.object(api, 'submit_forward') as submit:
                    with self.assertRaises(ValueError):
                        runner('/synthetic-work', 'a' * 32, ForwardRequest(
                            request_id='b' * 32, prompt='Continue.', seed=42, raw_frames=226))
                for mock in (factory, scene, refine, submit):
                    mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
