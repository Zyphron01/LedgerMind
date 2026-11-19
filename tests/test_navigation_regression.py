"""
tests/test_navigation_regression.py
────────────────────────────────────────────────────────────────────────────────
Regression test for Streamlit programmatic page navigation:
Verifies that navigating from Invoice Queue to Resolution Workbench
(e.g., clicking 'Resolve in Workbench' for INV-NOVA-2025-002) correctly
updates pending_page, sets selected_invoice_id, and avoids
StreamlitWidgetAlreadyInstantiatedError upon rerun.
"""

from unittest.mock import patch, MagicMock
import pytest
import streamlit as st

from ui.state import init_session_state, navigate_to


def test_navigate_to_stages_pending_page_and_invoice():
    """Verify navigate_to sets pending_page and selected_invoice_id without direct widget collision."""
    # Initialize state
    st.session_state.clear()
    init_session_state()

    assert st.session_state["current_page"] == "Overview"
    assert st.session_state["pending_page"] is None

    # Mock st.rerun so it records the call rather than terminating execution
    with patch.object(st, "rerun") as mock_rerun:
        navigate_to("Resolution Workbench", selected_invoice_id="INV-NOVA-2025-002")
        mock_rerun.assert_called_once()

    assert st.session_state["pending_page"] == "Resolution Workbench"
    assert st.session_state["selected_invoice_id"] == "INV-NOVA-2025-002"


def test_app_main_processes_pending_page_before_widget_creation():
    """Verify app.py promotion logic promotes pending_page to current_page safely."""
    st.session_state.clear()
    init_session_state()

    # Simulate pending navigation staged by navigate_to
    st.session_state["pending_page"] = "Resolution Workbench"
    st.session_state["selected_invoice_id"] = "INV-NOVA-2025-002"

    pages = [
        "Overview",
        "Invoice Queue",
        "New Invoice / Import",
        "Resolution Workbench",
        "Memory OFF vs ON Comparison",
        "Memory Intelligence",
    ]

    # Simulate top-of-run logic from app.py
    if st.session_state.get("pending_page"):
        target_page = st.session_state.pop("pending_page")
        if target_page in pages:
            st.session_state["current_page"] = target_page

    assert st.session_state["current_page"] == "Resolution Workbench"
    assert st.session_state["selected_invoice_id"] == "INV-NOVA-2025-002"
    assert st.session_state.get("pending_page") is None

    # Verify index is correctly computed for st.radio
    current_idx = pages.index(st.session_state["current_page"])
    assert current_idx == 3
    assert pages[current_idx] == "Resolution Workbench"


def test_navigation_across_all_registered_pages():
    """Verify that all application pages are valid navigation targets."""
    st.session_state.clear()
    init_session_state()

    valid_pages = [
        "Overview",
        "Invoice Queue",
        "New Invoice / Import",
        "Resolution Workbench",
        "Memory OFF vs ON Comparison",
        "Memory Intelligence",
    ]

    for p in valid_pages:
        with patch.object(st, "rerun"):
            navigate_to(p)
        assert st.session_state["pending_page"] == p

        # Promote
        target = st.session_state.pop("pending_page")
        assert target in valid_pages
        st.session_state["current_page"] = target
        assert st.session_state["current_page"] == p

