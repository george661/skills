#!/usr/bin/env python3
"""
Module wrapper for testing-md-parser.py

This allows other hooks to import the parser using:
    from testing_md_parser import parse_testing_md
"""

import os
import sys
import importlib.util

# Load testing-md-parser.py (with hyphens) and re-export its functions
_hook_dir = os.path.dirname(os.path.abspath(__file__))
_parser_path = os.path.join(_hook_dir, 'testing-md-parser.py')

_spec = importlib.util.spec_from_file_location("testing_md_parser_impl", _parser_path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

# Re-export all public functions
parse_testing_md = _module.parse_testing_md
parse_pre_commit_requirements = _module.parse_pre_commit_requirements
parse_required_tests = _module.parse_required_tests
parse_test_data = _module.parse_test_data
parse_test_modes = _module.parse_test_modes
parse_markdown_table = _module.parse_markdown_table
detect_technology = _module.detect_technology
TECH_DEFAULTS = _module.TECH_DEFAULTS
