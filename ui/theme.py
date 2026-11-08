"""
ui/theme.py
────────────────────────────────────────────────────────────────────────────────
Premium Dark Design System & Theme Engine for LedgerMind.
Inspired by modern UI libraries: Tremor, Aceternity UI, Magic UI, and shadcn/ui.
Provides CSS variables, component classes, glowing badges, and responsive card layouts.
"""

import streamlit as st


# Color Palette Tokens
COLORS = {
    "bg_dark": "#0B0F17",
    "surface": "#111827",
    "surface_elevated": "#1E293B",
    "border": "#1F2937",
    "border_highlight": "#374151",
    "text_primary": "#F9FAFB",
    "text_secondary": "#9CA3AF",
    "text_muted": "#6B7280",
    "accent_emerald": "#10B981",
    "accent_emerald_bg": "rgba(16, 185, 129, 0.12)",
    "accent_amber": "#F59E0B",
    "accent_amber_bg": "rgba(245, 158, 11, 0.12)",
    "accent_rose": "#EF4444",
    "accent_rose_bg": "rgba(239, 68, 68, 0.12)",
    "accent_blue": "#3B82F6",
    "accent_blue_bg": "rgba(59, 130, 246, 0.12)",
    "accent_violet": "#8B5CF6",
    "accent_violet_bg": "rgba(139, 92, 246, 0.12)",
    "accent_cyan": "#06B6D4",
    "accent_cyan_bg": "rgba(6, 182, 212, 0.12)",
}


CUSTOM_CSS = """
<style>
/* ─────────────────────────────────────────────────────────────────────────────
   LEDGERMIND PREMIUM DESIGN SYSTEM (Tremor / Aceternity / MagicUI / shadcn)
   ───────────────────────────────────────────────────────────────────────────── */

:root {
    --lm-bg: #0B0F17;
    --lm-surface: #111827;
    --lm-surface-elevated: #1F2937;
    --lm-border: #1F2937;
    --lm-border-hover: #374151;
    --lm-emerald: #10B981;
    --lm-amber: #F59E0B;
    --lm-rose: #EF4444;
    --lm-blue: #3B82F6;
    --lm-violet: #8B5CF6;
    --lm-cyan: #06B6D4;
}

/* Modern Clean Typography & Font Weights */
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    letter-spacing: -0.011em;
}

/* Streamlit Header & Background Cleanups */
header[data-testid="stHeader"] {
    background: transparent;
}

/* Main Container Padding */
.main .block-container {
    padding-top: 2rem;
    padding-bottom: 3.5rem;
    max-width: 1350px;
}

/* Sidebar Custom Styling */
section[data-testid="stSidebar"] {
    background-color: #0d121c;
    border-right: 1px solid #1f2937;
}

/* Tremor-style KPI Metric Cards */
div[data-testid="stMetric"] {
    background: linear-gradient(180deg, #131b2e 0%, #101624 100%);
    border: 1px solid #1f2937;
    border-radius: 12px;
    padding: 16px 20px;
    box-shadow: 0 4px 14px 0 rgba(0, 0, 0, 0.35);
    transition: transform 0.15s ease, border-color 0.15s ease;
}

div[data-testid="stMetric"]:hover {
    border-color: #374151;
    transform: translateY(-1px);
}

div[data-testid="stMetric"] label {
    font-size: 0.82rem !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #94a3b8 !important;
    font-weight: 600;
}

div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-size: 1.75rem !important;
    font-weight: 700;
    color: #f8fafc !important;
    letter-spacing: -0.02em;
}

/* Bento Card Style */
.lm-card {
    background: #111827;
    border: 1px solid #1f2937;
    border-radius: 14px;
    padding: 22px;
    margin-bottom: 16px;
    box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.45);
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.lm-card:hover {
    border-color: #374151;
    box-shadow: 0 8px 25px -4px rgba(0, 0, 0, 0.6);
}

.lm-card-gradient {
    background: linear-gradient(135deg, rgba(17, 24, 39, 0.95) 0%, rgba(30, 41, 59, 0.7) 100%);
    border: 1px solid #1f2937;
    border-radius: 14px;
    padding: 22px;
    margin-bottom: 16px;
    box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.45);
}

/* Tremor-style Left-Border Callout Card */
.lm-callout {
    border-left: 4px solid #3b82f6;
    background: rgba(30, 41, 59, 0.4);
    border-top: 1px solid #1f2937;
    border-right: 1px solid #1f2937;
    border-bottom: 1px solid #1f2937;
    border-radius: 0 10px 10px 0;
    padding: 16px 20px;
    margin: 12px 0 18px 0;
}

.lm-callout-warning {
    border-left-color: #f59e0b;
    background: rgba(245, 158, 11, 0.05);
}

.lm-callout-danger {
    border-left-color: #ef4444;
    background: rgba(239, 68, 68, 0.06);
}

.lm-callout-success {
    border-left-color: #10b981;
    background: rgba(16, 185, 129, 0.05);
}

.lm-callout-policy {
    border-left-color: #8b5cf6;
    background: rgba(139, 92, 246, 0.06);
}

/* Magic UI Pulsating Connectivity Dot */
@keyframes lm-pulse {
    0% {
        box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
    }
    70% {
        box-shadow: 0 0 0 8px rgba(16, 185, 129, 0);
    }
    100% {
        box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
    }
}

.lm-pulse-dot {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background-color: #10b981;
    margin-right: 8px;
    animation: lm-pulse 2s infinite;
    vertical-align: middle;
}

.lm-pulse-dot-amber {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background-color: #f59e0b;
    margin-right: 8px;
    vertical-align: middle;
}

/* Status Badges & Pills (shadcn style) */
.lm-badge {
    display: inline-flex;
    align-items: center;
    padding: 3px 10px;
    border-radius: 9999px;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    line-height: 1.2;
}

.lm-badge-emerald {
    background-color: rgba(16, 185, 129, 0.15);
    color: #34d399;
    border: 1px solid rgba(16, 185, 129, 0.35);
}

.lm-badge-amber {
    background-color: rgba(245, 158, 11, 0.15);
    color: #fbbf24;
    border: 1px solid rgba(245, 158, 11, 0.35);
}

.lm-badge-rose {
    background-color: rgba(239, 68, 68, 0.15);
    color: #f87171;
    border: 1px solid rgba(239, 68, 68, 0.35);
}

.lm-badge-blue {
    background-color: rgba(59, 130, 246, 0.15);
    color: #60a5fa;
    border: 1px solid rgba(59, 130, 246, 0.35);
}

.lm-badge-violet {
    background-color: rgba(139, 92, 246, 0.15);
    color: #c084fc;
    border: 1px solid rgba(139, 92, 246, 0.35);
}

.lm-badge-gray {
    background-color: rgba(107, 114, 128, 0.15);
    color: #9ca3af;
    border: 1px solid rgba(107, 114, 128, 0.35);
}

/* Timeline & Feed styles (Aceternity style) */
.lm-timeline-item {
    position: relative;
    padding-left: 28px;
    padding-bottom: 20px;
    border-left: 2px solid #1f2937;
}

.lm-timeline-item:last-child {
    border-left: 2px solid transparent;
}

.lm-timeline-dot {
    position: absolute;
    left: -7px;
    top: 2px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background-color: #8b5cf6;
    border: 2px solid #0b0f17;
}

/* Comparison Diff Card */
.lm-diff-card {
    background: #111827;
    border: 1px solid #1f2937;
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 16px;
}

.lm-diff-header-off {
    border-bottom: 2px solid #6b7280;
    padding-bottom: 10px;
    margin-bottom: 14px;
}

.lm-diff-header-on {
    border-bottom: 2px solid #10b981;
    padding-bottom: 10px;
    margin-bottom: 14px;
}

/* Glassmorphism subtle overlay */
.lm-glass {
    background: rgba(17, 24, 39, 0.85);
    backdrop-filter: blur(8px);
    border: 1px solid rgba(31, 41, 55, 0.7);
    border-radius: 12px;
}

/* Custom Progress Bar for Confidence Score */
.lm-progress-bg {
    width: 100%;
    background-color: #1f2937;
    border-radius: 9999px;
    height: 8px;
    overflow: hidden;
    margin-top: 6px;
    margin-bottom: 10px;
}

.lm-progress-bar-high {
    height: 100%;
    background: linear-gradient(90deg, #10b981 0%, #34d399 100%);
    border-radius: 9999px;
}

.lm-progress-bar-med {
    height: 100%;
    background: linear-gradient(90deg, #f59e0b 0%, #fbbf24 100%);
    border-radius: 9999px;
}

.lm-progress-bar-low {
    height: 100%;
    background: linear-gradient(90deg, #ef4444 0%, #f87171 100%);
    border-radius: 9999px;
}
</style>
"""


def inject_custom_css() -> None:
    """Inject global custom CSS into the Streamlit session."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def render_pulsing_status(connected: bool, label: str = "Connected") -> str:
    """Return HTML string for live pulsating status badge."""
    if connected:
        return f'<span class="lm-badge lm-badge-emerald"><span class="lm-pulse-dot"></span>{label}</span>'
    return f'<span class="lm-badge lm-badge-amber"><span class="lm-pulse-dot-amber"></span>Offline Fallback</span>'

