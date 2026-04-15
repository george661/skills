#!/usr/bin/env python3
"""
Tests for checkpoint replay/history/inspect commands.

TDD tests for the new checkpoint.py CLI subcommands.
"""

import unittest
from unittest.mock import patch


class TestHistoryCommand(unittest.TestCase):
    """Tests for history_checkpoints function."""

    @patch('checkpoint._agentdb_list')
    def test_history_returns_all_phases_sorted(self, mock_list):
        """History should return all phases sorted by timestamp descending."""
        from checkpoint import history_checkpoints

        mock_list.return_value = [
            {'phase': 'implementation', 'timestamp': '2026-04-15T10:00:00Z', 'data': {'status': 'pass'}},
            {'phase': 'validation', 'timestamp': '2026-04-15T11:00:00Z', 'data': {'status': 'pass'}},
            {'phase': 'pr-creation', 'timestamp': '2026-04-15T12:00:00Z', 'data': {'status': 'running'}},
        ]

        result = history_checkpoints('GW-4986')

        self.assertEqual(result['issue'], 'GW-4986')
        self.assertEqual(len(result['checkpoints']), 3)
        # Should be sorted descending (newest first)
        self.assertEqual(result['checkpoints'][0]['phase'], 'pr-creation')
        self.assertEqual(result['checkpoints'][0]['status'], 'running')
        self.assertEqual(result['checkpoints'][2]['phase'], 'implementation')
        self.assertIn('content_hash', result['checkpoints'][0])
        self.assertIn('age_hours', result['checkpoints'][0])

    @patch('checkpoint._agentdb_list')
    def test_history_returns_empty_for_unknown_issue(self, mock_list):
        """History should return empty list for unknown issue."""
        from checkpoint import history_checkpoints

        mock_list.return_value = []

        result = history_checkpoints('UNKNOWN-999')

        self.assertEqual(result['issue'], 'UNKNOWN-999')
        self.assertEqual(len(result['checkpoints']), 0)
        self.assertEqual(result['total'], 0)

    @patch('checkpoint._agentdb_list')
    def test_history_handles_agentdb_unavailable(self, mock_list):
        """History should handle AgentDB unavailable gracefully."""
        from checkpoint import history_checkpoints

        mock_list.return_value = None

        result = history_checkpoints('GW-4986')

        self.assertIn('error', result)
        self.assertIn('AgentDB unavailable', result['error'])

    @patch('checkpoint._agentdb_list')
    def test_history_brief_mode(self, mock_list):
        """History brief mode should return compact output."""
        from checkpoint import history_checkpoints

        mock_list.return_value = [
            {'phase': 'implementation', 'timestamp': '2026-04-15T10:00:00Z', 'data': {'key': 'value'}},
        ]

        result = history_checkpoints('GW-4986', brief=True)

        self.assertEqual(len(result['checkpoints']), 1)
        # Brief mode should NOT include full data
        self.assertNotIn('data', result['checkpoints'][0])


class TestInspectCommand(unittest.TestCase):
    """Tests for inspect_checkpoint function."""

    @patch('checkpoint._agentdb_load')
    def test_inspect_returns_full_state_snapshot(self, mock_load):
        """Inspect should return full state snapshot at checkpoint."""
        from checkpoint import inspect_checkpoint

        mock_load.return_value = {
            'phase': 'implementation',
            'timestamp': '2026-04-15T10:00:00Z',
            'data': {'branch': 'feature', 'files': ['a.py', 'b.py']}
        }

        result = inspect_checkpoint('GW-4986', 'implementation')

        self.assertEqual(result['issue'], 'GW-4986')
        self.assertEqual(result['phase'], 'implementation')
        self.assertIn('data', result)
        self.assertIn('content_hash', result)
        self.assertIn('data_size_bytes', result)
        self.assertIn('timestamp', result)

    @patch('checkpoint._agentdb_load')
    def test_inspect_returns_error_for_unknown_step(self, mock_load):
        """Inspect should return error for unknown issue/step."""
        from checkpoint import inspect_checkpoint

        mock_load.return_value = None

        result = inspect_checkpoint('GW-4986', 'nonexistent')

        self.assertIn('error', result)
        self.assertIn('not found', result['error'])

    @patch('checkpoint._agentdb_load')
    def test_inspect_handles_agentdb_unavailable(self, mock_load):
        """Inspect should handle AgentDB unavailable gracefully."""
        from checkpoint import inspect_checkpoint

        mock_load.side_effect = Exception('AgentDB connection failed')

        result = inspect_checkpoint('GW-4986', 'implementation')

        self.assertIn('error', result)


class TestReplayCommand(unittest.TestCase):
    """Tests for replay_checkpoint function."""

    @patch('checkpoint._agentdb_load')
    @patch('checkpoint._agentdb_save')
    @patch('checkpoint._agentdb_list')
    def test_replay_creates_new_run_id(self, mock_list, mock_save, mock_load):
        """Replay should create a new run-id with replay timestamp."""
        from checkpoint import replay_checkpoint

        mock_load.return_value = {
            'phase': 'validation',
            'timestamp': '2026-04-15T10:00:00Z',
            'data': {'branch': 'feature', 'status': 'pass'}
        }
        mock_list.return_value = [
            {'phase': 'implementation', 'timestamp': '2026-04-15T09:00:00Z', 'data': {}},
            {'phase': 'validation', 'timestamp': '2026-04-15T10:00:00Z', 'data': {}},
            {'phase': 'pr-creation', 'timestamp': '2026-04-15T11:00:00Z', 'data': {}},
        ]

        result = replay_checkpoint('GW-4986', 'validation')

        self.assertIn('new_run_id', result)
        self.assertTrue(result['new_run_id'].startswith('GW-4986~replay~'))
        self.assertEqual(result['replayed_from'], 'validation')
        self.assertEqual(result['parent_run_id'], 'GW-4986')
        mock_save.assert_called()

    @patch('checkpoint._agentdb_load')
    @patch('checkpoint._agentdb_save')
    @patch('checkpoint._agentdb_list')
    def test_replay_applies_overrides(self, mock_list, mock_save, mock_load):
        """Replay should merge overrides into loaded state."""
        from checkpoint import replay_checkpoint

        mock_load.return_value = {
            'phase': 'validation',
            'timestamp': '2026-04-15T10:00:00Z',
            'data': {'branch': 'feature', 'status': 'pass'}
        }
        mock_list.return_value = [
            {'phase': 'validation', 'timestamp': '2026-04-15T10:00:00Z', 'data': {}},
        ]

        replay_checkpoint('GW-4986', 'validation', overrides={'status': 'retry', 'new_field': 'value'})

        # Verify save was called with merged data
        call_args = mock_save.call_args
        saved_data = call_args[0][2] if len(call_args[0]) > 2 else call_args[1]['data']
        self.assertEqual(saved_data['status'], 'retry')
        self.assertEqual(saved_data['new_field'], 'value')
        self.assertEqual(saved_data['branch'], 'feature')  # Original preserved

    @patch('checkpoint._agentdb_load')
    @patch('checkpoint._agentdb_save')
    @patch('checkpoint._agentdb_list')
    def test_replay_clears_phases_after_checkpoint(self, mock_list, mock_save, mock_load):
        """Replay should mark phases after from_step as cleared."""
        from checkpoint import replay_checkpoint

        mock_load.return_value = {
            'phase': 'validation',
            'timestamp': '2026-04-15T10:00:00Z',
            'data': {'status': 'pass'}
        }
        mock_list.return_value = [
            {'phase': 'implementation', 'timestamp': '2026-04-15T09:00:00Z', 'data': {}},
            {'phase': 'validation', 'timestamp': '2026-04-15T10:00:00Z', 'data': {}},
            {'phase': 'pr-creation', 'timestamp': '2026-04-15T11:00:00Z', 'data': {}},
        ]
        mock_save.return_value = True

        result = replay_checkpoint('GW-4986', 'validation')

        self.assertIn('phases_cleared', result)
        self.assertIn('pr-creation', result['phases_cleared'])

    @patch('checkpoint._agentdb_load')
    def test_replay_error_on_unknown_step(self, mock_load):
        """Replay should return error for unknown step."""
        from checkpoint import replay_checkpoint

        mock_load.return_value = None

        result = replay_checkpoint('GW-4986', 'nonexistent')

        self.assertIn('error', result)
        self.assertIn('not found', result['error'])

    @patch('checkpoint._agentdb_load')
    @patch('checkpoint._agentdb_save')
    @patch('checkpoint._agentdb_get_state')
    def test_replay_is_nondestructive(self, mock_get, mock_save, mock_load):
        """Replay should not modify existing checkpoints."""
        from checkpoint import replay_checkpoint

        original_state = {'phases': {'validation': {'data': 'original'}}}
        mock_get.return_value = original_state
        mock_load.return_value = {
            'phase': 'validation',
            'timestamp': '2026-04-15T10:00:00Z',
            'data': {'status': 'pass'}
        }

        replay_checkpoint('GW-4986', 'validation')

        # Verify original issue state was NOT modified
        # Only the new replay run-id should be saved
        for call in mock_save.call_args_list:
            issue_arg = call[0][0]
            self.assertIn('~replay~', issue_arg)


if __name__ == '__main__':
    unittest.main()
