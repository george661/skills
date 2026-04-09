#!/usr/bin/env python3
"""Tests for validate-config.py hook."""

import json
import sys
import os
import unittest
from unittest.mock import patch
from io import StringIO

# The module under test uses a hyphenated filename, so we import it via importlib.
import importlib.util

_HOOK_PATH = os.path.join(os.path.dirname(__file__), "..", "validate-config.py")
_spec = importlib.util.spec_from_file_location("validate_config", _HOOK_PATH)
validate_config_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate_config_mod)

build_status_table = validate_config_mod.build_status_table
validate_config = validate_config_mod.validate_config
main = validate_config_mod.main


def _clean_env():
    """Return a minimal env dict with all provider vars cleared."""
    return {
        "ISSUE_TRACKER": "",
        "VCS_PROVIDER": "",
        "CI_PROVIDER": "",
        "TENANT_PROJECT": "",
        "JIRA_PROJECT_KEYS": "",
        "PROJECT_ROOT": "",
        "JIRA_HOST": "",
        "JIRA_USERNAME": "",
        "JIRA_API_TOKEN": "",
        "GITHUB_TOKEN": "",
        "GITHUB_OWNER": "",
        "LINEAR_API_KEY": "",
        "BITBUCKET_WORKSPACE": "",
        "BITBUCKET_USERNAME": "",
        "BITBUCKET_TOKEN": "",
        "CONCOURSE_URL": "",
        "AGENTDB_URL": "",
        "SLACK_BOT_TOKEN": "",
        "TENANT_DOMAIN_PATH": "",
    }


class TestAllVarsSet(unittest.TestCase):
    """When every required var is set for jira+bitbucket, no warnings."""

    @patch.dict(os.environ, {
        **_clean_env(),
        "ISSUE_TRACKER": "jira",
        "VCS_PROVIDER": "bitbucket",
        "TENANT_PROJECT": "PROJ",
        "PROJECT_ROOT": "/code",
        "JIRA_HOST": "jira.example.com",
        "JIRA_USERNAME": "user",
        "JIRA_API_TOKEN": "tok",
        "BITBUCKET_WORKSPACE": "ws",
        "BITBUCKET_USERNAME": "user",
        "BITBUCKET_TOKEN": "tok",
    }, clear=False)
    def test_no_warnings_when_all_set(self):
        rows, missing, warnings = build_status_table()
        self.assertEqual(missing, 0)
        self.assertEqual(warnings, [])
        statuses = {r[0]: r[1] for r in rows}
        self.assertEqual(statuses["TENANT_PROJECT"], "SET")
        self.assertEqual(statuses["PROJECT_ROOT"], "SET")
        self.assertEqual(statuses["JIRA_HOST"], "SET")
        self.assertEqual(statuses["BITBUCKET_WORKSPACE"], "SET")


class TestMissingJiraHost(unittest.TestCase):
    """Missing JIRA_HOST when ISSUE_TRACKER=jira produces a warning."""

    @patch.dict(os.environ, {
        **_clean_env(),
        "ISSUE_TRACKER": "jira",
        "TENANT_PROJECT": "PROJ",
        "PROJECT_ROOT": "/code",
        "JIRA_USERNAME": "user",
        "JIRA_API_TOKEN": "tok",
        # JIRA_HOST intentionally absent
    }, clear=False)
    def test_missing_jira_host(self):
        rows, missing, warnings = build_status_table()
        self.assertGreater(missing, 0)
        statuses = {r[0]: r[1] for r in rows}
        self.assertEqual(statuses["JIRA_HOST"], "MISSING")


class TestGitHubProvider(unittest.TestCase):
    """GitHub provider checks GITHUB_TOKEN and GITHUB_OWNER."""

    @patch.dict(os.environ, {
        **_clean_env(),
        "ISSUE_TRACKER": "github",
        "TENANT_PROJECT": "PROJ",
        "PROJECT_ROOT": "/code",
        # GITHUB_TOKEN and GITHUB_OWNER not set
    }, clear=False)
    def test_missing_github_vars(self):
        rows, missing, warnings = build_status_table()
        statuses = {r[0]: r[1] for r in rows}
        self.assertEqual(statuses.get("GITHUB_TOKEN"), "MISSING")
        self.assertEqual(statuses.get("GITHUB_OWNER"), "MISSING")

    @patch.dict(os.environ, {
        **_clean_env(),
        "ISSUE_TRACKER": "github",
        "TENANT_PROJECT": "PROJ",
        "PROJECT_ROOT": "/code",
        "GITHUB_TOKEN": "ghp_abc",
        "GITHUB_OWNER": "myorg",
    }, clear=False)
    def test_github_vars_set(self):
        rows, missing, warnings = build_status_table()
        statuses = {r[0]: r[1] for r in rows}
        self.assertEqual(statuses.get("GITHUB_TOKEN"), "SET")
        self.assertEqual(statuses.get("GITHUB_OWNER"), "SET")
        self.assertEqual(missing, 0)


class TestLinearProvider(unittest.TestCase):
    """Linear provider checks LINEAR_API_KEY."""

    @patch.dict(os.environ, {
        **_clean_env(),
        "ISSUE_TRACKER": "linear",
        "TENANT_PROJECT": "PROJ",
        "PROJECT_ROOT": "/code",
        # LINEAR_API_KEY not set
    }, clear=False)
    def test_missing_linear_key(self):
        rows, missing, warnings = build_status_table()
        statuses = {r[0]: r[1] for r in rows}
        self.assertEqual(statuses.get("LINEAR_API_KEY"), "MISSING")

    @patch.dict(os.environ, {
        **_clean_env(),
        "ISSUE_TRACKER": "linear",
        "TENANT_PROJECT": "PROJ",
        "PROJECT_ROOT": "/code",
        "LINEAR_API_KEY": "lin_key_123",
    }, clear=False)
    def test_linear_key_set(self):
        rows, missing, warnings = build_status_table()
        statuses = {r[0]: r[1] for r in rows}
        self.assertEqual(statuses.get("LINEAR_API_KEY"), "SET")


class TestUnknownProvider(unittest.TestCase):
    """Unknown provider value produces a warning."""

    @patch.dict(os.environ, {
        **_clean_env(),
        "ISSUE_TRACKER": "trello",
        "TENANT_PROJECT": "PROJ",
        "PROJECT_ROOT": "/code",
    }, clear=False)
    def test_unknown_issue_tracker(self):
        rows, missing, warnings = build_status_table()
        self.assertTrue(any("trello" in w for w in warnings))

    @patch.dict(os.environ, {
        **_clean_env(),
        "VCS_PROVIDER": "gitlab",
        "TENANT_PROJECT": "PROJ",
        "PROJECT_ROOT": "/code",
    }, clear=False)
    def test_unknown_vcs_provider(self):
        rows, missing, warnings = build_status_table()
        self.assertTrue(any("gitlab" in w for w in warnings))


class TestAlwaysAllow(unittest.TestCase):
    """Hook always returns {"decision": "allow"} regardless of missing vars."""

    @patch.dict(os.environ, _clean_env(), clear=False)
    def test_allow_with_all_missing(self):
        """Even with nothing set, stdout must contain the allow decision."""
        captured = StringIO()
        old_stdout = sys.stdout
        old_stdin = sys.stdin
        try:
            sys.stdout = captured
            sys.stdin = StringIO("")
            main()
        finally:
            sys.stdout = old_stdout
            sys.stdin = old_stdin

        output = captured.getvalue().strip()
        result = json.loads(output)
        self.assertEqual(result, {"decision": "allow"})

    @patch.dict(os.environ, {
        **_clean_env(),
        "ISSUE_TRACKER": "jira",
        "TENANT_PROJECT": "PROJ",
        "PROJECT_ROOT": "/code",
        # Missing JIRA_HOST etc.
    }, clear=False)
    def test_allow_with_partial_config(self):
        captured = StringIO()
        old_stdout = sys.stdout
        old_stdin = sys.stdin
        try:
            sys.stdout = captured
            sys.stdin = StringIO("")
            main()
        finally:
            sys.stdout = old_stdout
            sys.stdin = old_stdin

        output = captured.getvalue().strip()
        result = json.loads(output)
        self.assertEqual(result, {"decision": "allow"})


if __name__ == "__main__":
    unittest.main()
