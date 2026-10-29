"""Human directions and generated prompts have different bounded contracts."""
import ast
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from continuity_requests import ForwardRequest, PreparedH3Request
from h3_prompt_generator import MAX_PROMPT_BYTES
from pydantic import ValidationError
import continuity_attempts as attempts
from test_continuity_pipeline import MODELS


class PreparedPromptTests(unittest.TestCase):
    def fields(self, prompt):
        return dict(request_id='a' * 32, prompt=prompt, seed=7, raw_frames=158)

    def test_public_direction_stays_short_but_effective_prompt_is_not_truncated(self):
        text = 'synthetic prepared prompt ' * 200
        with self.assertRaises(ValidationError): ForwardRequest(**self.fields(text))
        prepared = PreparedH3Request(**self.fields(text))
        self.assertEqual(prepared.prompt, text)
        self.assertEqual(PreparedH3Request(**self.fields('é' * (MAX_PROMPT_BYTES // 2))).prompt,
                         'é' * (MAX_PROMPT_BYTES // 2))
        for bad in (' ', 'é' * (MAX_PROMPT_BYTES // 2 + 1)):
            with self.assertRaises(ValidationError): PreparedH3Request(**self.fields(bad))

    def test_internal_model_keeps_seed_and_native_grid_validation(self):
        for changes in ({'seed': True}, {'seed': -1}, {'raw_frames': 159}, {'extra': 'graph'}):
            with self.assertRaises(ValidationError):
                PreparedH3Request(**(self.fields('Prepared direction') | changes))

    def test_real_hunt_callback_accepts_long_generated_text_before_submit(self):
        source = Path(__file__).resolve().parents[1] / 'src/app.py'
        function = next(n for n in ast.parse(source.read_text()).body
                        if isinstance(n, ast.FunctionDef) and n.name == '_hunt_submit')
        client = MagicMock()
        client.assets.from_file.return_value.as_reference.return_value = {
            '__type': 'core/ASSET', 'info': {'id': 'synthetic-reference'}}
        submit = Mock(return_value={'status': 'done', 'take_id': 'b' * 32})
        namespace = {'core': SimpleNamespace(WORK=Path('/synthetic-work')),
            'Path': Path, 'make_client': lambda: client,
            'parent_references': lambda *args: [Path('/synthetic-reference.png')],
            '_continuity_models': lambda: MODELS, 'target_fingerprint': lambda *args: 'f' * 64,
            'comfy_base_url': lambda: 'http://unit.invalid', 'H3Models': lambda: MODELS,
            'submit_forward': submit}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        text = 'synthetic prepared prompt ' * 200
        self.assertEqual(namespace['_hunt_submit']('c' * 32, text, 7, 158, 'a' * 32), 'b' * 32)
        self.assertEqual(submit.call_args.args[2].prompt, text)
        self.assertEqual(submit.call_args.args[2].seed, 7)
        client.submit.assert_not_called()

    def test_forward_resolves_target_identity_for_each_new_run(self):
        import continuity_forward_api as forward
        client = MagicMock()
        target = {'value': 'first-target'}
        request = ForwardRequest(**self.fields('Keep the motion'))
        with patch.object(forward, 'parent_references', return_value=[Path('/synthetic-reference.png')]), \
             patch.object(forward, 'refine_continuation_prompt', return_value='Prepared direction'), \
             patch.object(forward, 'submit_forward', return_value={'status': 'done'}) as submit:
            runner = forward.make_forward_runner(client_factory=lambda: client,
                models_factory=lambda: MODELS, fingerprint=lambda: target['value'],
                work_root=Path('/synthetic-work'), preflight=lambda *a, **k: None)
            runner('/synthetic-work', 'a'*32, request)
            self.assertEqual(submit.call_args.kwargs['target_fingerprint'], 'first-target')
            target['value'] = 'second-target'
            runner('/synthetic-work', 'a'*32, request)
            self.assertEqual(submit.call_args.kwargs['target_fingerprint'], 'second-target')
        client.run.assert_not_called()

    def test_public_attempt_errors_do_not_leak_legacy_generated_text_or_credentials(self):
        secret = 'PRIVATE_GENERATED_PROMPT https://unit.invalid/?token=PRIVATE_TOKEN'
        record = {'attempt_id': 'a' * 32, 'take_id': 'b' * 32, 'status': 'failed',
            'error': secret, 'candidates': [{'seed': 7, 'status': 'failed',
                'take_id': None, 'error': secret}]}
        result = attempts.public(record)
        self.assertNotIn('PRIVATE_', str(result))
        self.assertIsNotNone(result['error'])
        self.assertIsNotNone(result['candidates'][0]['error'])
        self.assertEqual(record['error'], secret, 'private diagnostics remain unchanged')
