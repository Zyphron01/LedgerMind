"""
tests/test_streamlit_smoke.py
────────────────────────────────────────────────────────────────────────────────
Smoke tests for LedgerMind Streamlit views and pages.
Ensures every page renders cleanly and without unhandled exceptions.
"""

import pytest

from ui.state import init_session_state
from ui.pages.comparison import render_comparison_page
from ui.pages.overview import render_overview_page
from ui.pages.queue import render_queue_page
from ui.pages.workbench import render_workbench_page
from ui.pages.memory_intelligence import render_memory_intelligence_page


def test_overview_page_render():
    """Verify Overview page renders cleanly."""
    init_session_state()
    render_overview_page()


def test_queue_page_render():
    """Verify Invoice Queue page renders cleanly."""
    init_session_state()
    render_queue_page()


def test_workbench_page_render():
    """Verify Resolution Workbench page renders cleanly."""
    init_session_state()
    render_workbench_page()


def test_comparison_page_render():
    """Verify Memory OFF vs ON Comparison page renders cleanly."""
    init_session_state()
    render_comparison_page()


def test_memory_intelligence_page_render():
    """Verify Memory Intelligence page renders cleanly."""
    init_session_state()
    render_memory_intelligence_page()
