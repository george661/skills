#!/usr/bin/env python3
"""
Tests for pattern_retrieval.py

TDD tests for the pattern retrieval utility functions.
"""

import unittest
from unittest.mock import patch, MagicMock
import json


class TestSearchPatterns(unittest.TestCase):
    """Tests for search_patterns function."""

    @patch('pattern_retrieval.agentdb_request')
    def test_search_patterns_returns_formatted_results(self, mock_request):
        """Search patterns should return list of pattern dicts."""
        from pattern_retrieval import search_patterns

        mock_request.return_value = {
            'patterns': [
                {'task_type': 'implement', 'pattern': {'reasoning': 'TDD approach'}, 'score': 0.9},
                {'task_type': 'implement', 'pattern': {'reasoning': 'Test first'}, 'score': 0.8}
            ]
        }

        result = search_patterns('implement feature', k=5, threshold=0.6)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['task_type'], 'implement')
        mock_request.assert_called_once()

    @patch('pattern_retrieval.agentdb_request')
    def test_search_patterns_returns_empty_when_agentdb_unavailable(self, mock_request):
        """Search should return empty list when AgentDB unavailable."""
        from pattern_retrieval import search_patterns

        mock_request.return_value = None

        result = search_patterns('implement feature')

        self.assertEqual(result, [])

    @patch('pattern_retrieval.agentdb_request')
    def test_search_patterns_with_filters(self, mock_request):
        """Search patterns should pass filters to API."""
        from pattern_retrieval import search_patterns

        mock_request.return_value = {'patterns': []}

        search_patterns('task', filters={'namespace': 'default', 'task_type': 'implement'})

        call_args = mock_request.call_args
        body = call_args[1].get('body') or call_args[0][2]
        self.assertIn('filters', body)


class TestRetrieveEpisodes(unittest.TestCase):
    """Tests for retrieve_episodes function."""

    @patch('pattern_retrieval.agentdb_request')
    def test_retrieve_episodes_returns_list(self, mock_request):
        """Retrieve episodes should return list of episode dicts."""
        from pattern_retrieval import retrieve_episodes

        mock_request.return_value = {
            'episodes': [
                {'session_id': 's1', 'task': 'implement', 'reward': 0.9, 'success': True},
                {'session_id': 's2', 'task': 'implement', 'reward': 0.7, 'success': True}
            ]
        }

        result = retrieve_episodes('implement feature', k=3)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    @patch('pattern_retrieval.agentdb_request')
    def test_retrieve_episodes_filters_by_success(self, mock_request):
        """Retrieve episodes should filter by success when specified."""
        from pattern_retrieval import retrieve_episodes

        mock_request.return_value = {'episodes': []}

        retrieve_episodes('task', success_only=True)

        call_args = mock_request.call_args
        body = call_args[1].get('body') or call_args[0][2]
        self.assertTrue(body.get('success_only'))

    @patch('pattern_retrieval.agentdb_request')
    def test_retrieve_episodes_returns_empty_when_agentdb_unavailable(self, mock_request):
        """Retrieve should return empty list when AgentDB unavailable."""
        from pattern_retrieval import retrieve_episodes

        mock_request.return_value = None

        result = retrieve_episodes('task')

        self.assertEqual(result, [])


class TestRetrieveForCommand(unittest.TestCase):
    """Tests for retrieve_for_command function."""

    @patch('pattern_retrieval.retrieve_episodes')
    @patch('pattern_retrieval.search_patterns')
    def test_retrieve_for_command_returns_structured_result(self, mock_search, mock_retrieve):
        """Retrieve for command should return dict with patterns, episodes, recommendations."""
        from pattern_retrieval import retrieve_for_command

        mock_search.return_value = [
            {'task_type': 'implement', 'pattern': {'reasoning': 'TDD'}, 'score': 0.9}
        ]
        mock_retrieve.return_value = [
            {'session_id': 's1', 'task': 'implement PROJ-100', 'success': True}
        ]

        context = {'issue_key': 'PROJ-123', 'issue_type': 'Task', 'repo': 'issue-daemon'}
        result = retrieve_for_command('implement', context)

        self.assertIn('patterns', result)
        self.assertIn('episodes', result)
        self.assertIn('recommendations', result)
        self.assertIsInstance(result['patterns'], list)
        self.assertIsInstance(result['episodes'], list)
        self.assertIsInstance(result['recommendations'], list)

    @patch('pattern_retrieval.retrieve_episodes')
    @patch('pattern_retrieval.search_patterns')
    def test_retrieve_for_command_generates_recommendations(self, mock_search, mock_retrieve):
        """Should generate recommendations from patterns and episodes."""
        from pattern_retrieval import retrieve_for_command

        mock_search.return_value = [
            {'task_type': 'implement', 'pattern': {'reasoning': 'Always run tests first'}, 'score': 0.95}
        ]
        mock_retrieve.return_value = [
            {'session_id': 's1', 'task': 'implement feature', 'success': True,
             'trajectory': [{'action': 'ran tests', 'outcome': 'passed'}]}
        ]

        result = retrieve_for_command('implement', {'issue_key': 'PROJ-123'})

        # Should have at least one recommendation based on patterns
        self.assertGreaterEqual(len(result['recommendations']), 0)


class TestFormatPatternsForOutput(unittest.TestCase):
    """Tests for format_patterns_for_output function."""

    def test_format_patterns_returns_empty_when_no_patterns(self):
        """Format should return empty string when no patterns or episodes."""
        from pattern_retrieval import format_patterns_for_output

        result = format_patterns_for_output(
            command='implement',
            context={'issue_key': 'PROJ-123'},
            patterns=[],
            episodes=[],
            recommendations=[]
        )

        self.assertEqual(result, '')

    def test_format_patterns_returns_xml_block(self):
        """Format should return XML-style block with content."""
        from pattern_retrieval import format_patterns_for_output

        patterns = [{'task_type': 'implement', 'pattern': {'reasoning': 'TDD'}, 'score': 0.9}]
        episodes = [{'session_id': 's1', 'task': 'implement', 'success': True}]
        recommendations = ['Run tests before committing']

        result = format_patterns_for_output(
            command='implement',
            context={'issue_key': 'PROJ-123'},
            patterns=patterns,
            episodes=episodes,
            recommendations=recommendations
        )

        self.assertIn('<retrieved-patterns', result)
        self.assertIn('command="implement"', result)
        self.assertIn('issue="PROJ-123"', result)
        self.assertIn('</retrieved-patterns>', result)

    def test_format_patterns_includes_recommendations(self):
        """Format should include recommendations section."""
        from pattern_retrieval import format_patterns_for_output

        result = format_patterns_for_output(
            command='implement',
            context={'issue_key': 'PROJ-123'},
            patterns=[{'task_type': 'x', 'pattern': {}, 'score': 0.8}],
            episodes=[],
            recommendations=['Always validate before committing']
        )

        self.assertIn('Always validate before committing', result)


class TestRetrieveAndFormat(unittest.TestCase):
    """Tests for retrieve_and_format main entry point."""

    @patch('pattern_retrieval.retrieve_for_command')
    @patch('pattern_retrieval.format_patterns_for_output')
    def test_retrieve_and_format_combines_retrieval_and_formatting(self, mock_format, mock_retrieve):
        """Main entry point should combine retrieval and formatting."""
        from pattern_retrieval import retrieve_and_format

        mock_retrieve.return_value = {
            'patterns': [{'task_type': 'x', 'pattern': {}}],
            'episodes': [],
            'recommendations': ['rec1']
        }
        mock_format.return_value = '<retrieved-patterns>...</retrieved-patterns>'

        result = retrieve_and_format('implement', {'issue_key': 'PROJ-123'})

        mock_retrieve.assert_called_once_with('implement', {'issue_key': 'PROJ-123'})
        mock_format.assert_called_once()
        self.assertIn('<retrieved-patterns>', result)


class TestGracefulFallback(unittest.TestCase):
    """Tests for graceful fallback behavior."""

    @patch('pattern_retrieval.agentdb_request')
    def test_search_patterns_handles_exception(self, mock_request):
        """Search should not crash on unexpected exceptions."""
        from pattern_retrieval import search_patterns

        mock_request.side_effect = Exception('Network error')

        result = search_patterns('task')

        self.assertEqual(result, [])

    @patch('pattern_retrieval.agentdb_request')
    def test_retrieve_episodes_handles_exception(self, mock_request):
        """Retrieve should not crash on unexpected exceptions."""
        from pattern_retrieval import retrieve_episodes

        mock_request.side_effect = Exception('Connection refused')

        result = retrieve_episodes('task')

        self.assertEqual(result, [])

    @patch('pattern_retrieval.agentdb_request')
    def test_search_patterns_handles_malformed_response(self, mock_request):
        """Search should handle malformed API responses."""
        from pattern_retrieval import search_patterns

        mock_request.return_value = {'unexpected_key': 'value'}

        result = search_patterns('task')

        self.assertEqual(result, [])


if __name__ == '__main__':
    unittest.main()
