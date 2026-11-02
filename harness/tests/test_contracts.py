import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('run_trial', ROOT / 'harness/run_trial.py')
run_trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_trial)
replication_spec = importlib.util.spec_from_file_location('replication', ROOT / 'harness/replication.py')
replication = importlib.util.module_from_spec(replication_spec)
replication_spec.loader.exec_module(replication)


class WireContract(unittest.TestCase):
    def test_empty_or_wrong_model_and_effort_fail_closed(self):
        self.assertIn('no_model_requests', run_trial.wire_violations([], 'low'))
        rows = [{'model': 'wrong', 'reasoning_effort': 'medium'}]
        self.assertEqual(run_trial.wire_violations(rows, 'low'),
                         ['wire_model_mismatch', 'wire_reasoning_effort_mismatch'])
        self.assertEqual(run_trial.wire_violations([{'model': 'deepseek-v4.1-flash',
                                                     'reasoning_effort': 'low'}], 'low'), [])


class HistoricalSafety(unittest.TestCase):
    def test_evaluation_refuses_existing_result(self):
        old = replication.R
        with tempfile.TemporaryDirectory() as tmp:
            replication.R = Path(tmp)
            output = replication.R / 'replication-evaluation-r1.json'
            output.write_text('historical')
            try:
                with self.assertRaises(FileExistsError):
                    replication.evaluate('r1', ['glla'])
                self.assertEqual(output.read_text(), 'historical')
            finally:
                replication.R = old

    def test_rejects_unsafe_trial_path(self):
        with self.assertRaises(ValueError):
            replication.cdir('dsh', '../r1')

    def test_historical_compressed_logs_remain_readable(self):
        expected = {('glla', 'r1'): 49, ('goal-x', 'r1'): 27,
                    ('glla', 'r2'): 42, ('goal-x', 'r2'): 23}
        for (name, trial), requests in expected.items():
            with self.subTest(name=name, trial=trial):
                self.assertEqual(replication.timeline(name, trial)['requests'], requests)


class RelayAccounting(unittest.TestCase):
    def test_cached_and_reasoning_tokens_not_double_counted(self):
        rows = [{'usage': {'prompt_tokens': 100, 'completion_tokens': 20,
                           'prompt_tokens_details': {'cached_tokens': 80},
                           'completion_tokens_details': {'reasoning_tokens': 12}}}]
        result = replication.relay_tokens(rows)
        self.assertEqual((result['input'], result['cacheRead'], result['output'], result['reasoning']),
                         (20, 80, 20, 12))
        self.assertEqual(result['requests_with_usage'], 1)
        self.assertIsNone(replication.relay_tokens([{}])['cost_usd_nominal'])


class NativeEvidenceContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.session = self.root / 'sessions' / 'session.v4.jsonl'
        self.session.parent.mkdir()
        self.events = [
            {'type': 'command/run', 'data': {'name': 'goal', 'commandId': '1'}},
            {'type': 'command/done', 'data': {'commandId': '1', 'kind': 'success'}},
            {'type': 'goal/change', 'data': {'operation': 'create', 'goal': {'phase': 'active'}}},
            {'type': 'user/message', 'data': {'source': {'kind': 'goal'}}},
            {'type': 'user/message', 'data': {'source': {'kind': 'goal'}}},
            {'type': 'goal/change', 'data': {'operation': 'complete', 'goal': {'phase': 'complete'}}},
        ]
        self.final = {'native_goal': {'objective': 'task', 'phase': 'complete', 'roundsStarted': 2}}

    def tearDown(self):
        self.tmp.cleanup()

    def check(self):
        self.session.write_text(''.join(json.dumps(event) + '\n' for event in self.events))
        return run_trial.validate_native_evidence(self.root, self.final, 'task\n')

    def test_two_rounds_and_terminal_persistence(self):
        self.assertEqual(self.check(), [])

    def test_prompt_without_command_is_not_native_evidence(self):
        self.events.pop(0)
        self.assertIn('native_command_not_dispatched', self.check())

    def test_missing_round_and_unpersisted_completion_fail(self):
        self.events = self.events[:3]
        problems = self.check()
        self.assertIn('native_round_evidence_missing', problems)
        self.assertIn('native_terminal_not_persisted', problems)

    def test_sandbox_failure_invalidates_evidence(self):
        self.events.append({'type': 'tool/result', 'data': {'message': {
            'content': [{'text': 'no sandbox backend is usable on this host'}]}}})
        self.assertIn('native_sandbox_unavailable', self.check())

    def test_mismatched_objective_fails(self):
        self.final['native_goal']['objective'] = 'different'
        self.assertIn('native_objective_mismatch', self.check())

    def test_only_single_final_newline_is_normalized(self):
        self.check()
        problems = run_trial.validate_native_evidence(self.root, self.final, ' task\n')
        self.assertIn('native_objective_mismatch', problems)


if __name__ == '__main__':
    unittest.main()
