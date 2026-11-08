"""
app.py
────────────────────────────────────────────────────────────────────────────────
LedgerMind — Accounts Payable Exception-Handling Agent Dashboard.
Main entry point for the Streamlit web application.
"""

from pathlib import Path
import sys

# Ensure root directory is on PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ROOT_DIR / ".env")
except Exception:
    pass

import streamlit as st

from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from ui.pages.comparison import render_comparison_page
from ui.pages.memory_intelligence import render_memory_intelligence_page
from ui.pages.overview import render_overview_page
from ui.pages.queue import render_queue_page
from ui.pages.workbench import render_workbench_page
from ui.state import check_hindsight_health, get_memory_client, init_session_state
from ui.theme import inject_custom_css, render_pulsing_status


def main() -> None:
    """Main application loop."""
    st.set_page_config(
        page_title="LedgerMind — AP Exception Resolution Agent",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Initialize session state & inject premium theme
    init_session_state()
    inject_custom_css()

    # SIDEBAR NAVIGATION & SYSTEM HEALTH
    with st.sidebar:
        st.markdown(
            """
            <div style="padding: 10px 0 16px 0;">
                <div style="font-size: 1.45rem; font-weight: 800; color: #f8fafc; letter-spacing: -0.02em; display: flex; align-items: center; gap: 8px;">
                    <span style="color: #10b981;">⚡</span> LedgerMind
                </div>
                <div style="font-size: 0.8rem; color: #94a3b8; margin-top: 4px; line-height: 1.4;">
                    Accounts Payable Discrepancy Resolution Agent with Hindsight Persistent Memory
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.divider()

        pages = [
            "Overview",
            "Invoice Queue",
            "Resolution Workbench",
            "Memory OFF vs ON Comparison",
            "Memory Intelligence",
        ]

        current = st.session_state.get("current_page", "Overview")
        current_idx = pages.index(current) if current in pages else 0

        selected_page = st.radio(
            "Navigation:",
            pages,
            index=current_idx,
        )
        st.session_state["current_page"] = selected_page

        st.divider()

        # SYSTEM STATUS CARD IN SIDEBAR
        health = check_hindsight_health()
        connected = health.get("connected", False)

        st.markdown(
            f"""
            <div style="background: rgba(17, 24, 39, 0.7); border: 1px solid #1f2937; border-radius: 10px; padding: 14px; margin-bottom: 14px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <span style="font-size: 0.85rem; font-weight: 700; color: #cbd5e1; text-transform: uppercase; letter-spacing: 0.04em;">Memory Engine</span>
                    {render_pulsing_status(connected, "ONLINE" if connected else "OFFLINE")}
                </div>
                <div style="font-size: 0.8rem; color: #94a3b8; display: flex; flex-direction: column; gap: 6px;">
                    <div>• <strong>Hindsight API:</strong> <code style="color: #60a5fa; font-size: 0.76rem;">{health.get('url', 'N/A')}</code></div>
                    <div>• <strong>Baseline Bank:</strong> <code style="color: #a78bfa; font-size: 0.76rem;">{BASELINE_EVAL_BANK_ID}</code></div>
                    <div>• <strong>Live Demo Bank:</strong> <code style="color: #fbbf24; font-size: 0.76rem;">{LIVE_DEMO_BANK_ID}</code></div>
                    <div>• <strong>Inference LLM:</strong> <code style="color: #34d399; font-size: 0.76rem;">gpt-oss-120b</code></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("🧹 Clear Session Cache", use_container_width=True, help="Clears proposal cache and reloads state."):
            st.session_state["proposal_cache"] = {}
            st.session_state["comparison_cache"] = {}
            st.success("Session caches cleared.")
            st.rerun()

    # MAIN PAGE ROUTING
    page = st.session_state.get("current_page", "Overview")

    if page == "Overview":
        render_overview_page()
    elif page == "Invoice Queue":
        render_queue_page()
    elif page == "Resolution Workbench":
        render_workbench_page()
    elif page == "Memory OFF vs ON Comparison":
        render_comparison_page()
    elif page == "Memory Intelligence":
        render_memory_intelligence_page()
    else:
        render_overview_page()


if __name__ == "__main__":
    main()
