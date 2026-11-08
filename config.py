"""
config.py
────────────────────────────────────────────────────────────────────────────────
LedgerMind Global Configuration & Workflow Bank Isolation.

Defines explicit bank identities to enforce strict separation:
  1. BASELINE_EVAL_BANK_ID: Frozen baseline benchmark bank (historical data only).
     Strictly READ-ONLY during agent evaluation to prevent feedback contamination.
  2. LIVE_DEMO_BANK_ID: Interactive learning bank (historical data + live human feedback).
"""

import os
from pathlib import Path

# Load environment
try:
    from dotenv import load_dotenv
    ROOT_DIR = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=ROOT_DIR / ".env")
except Exception:
    pass

# Frozen evaluation baseline bank (NO feedback writes permitted)
BASELINE_EVAL_BANK_ID = os.getenv("HINDSIGHT_BASELINE_BANK_ID", "ledgermind-ap-exceptions")

# Live demonstration bank (permits reviewer feedback and learning loop)
LIVE_DEMO_BANK_ID = os.getenv("HINDSIGHT_DEMO_BANK_ID", "ledgermind-live-demo")

# Default active bank
DEFAULT_BANK_ID = os.getenv("HINDSIGHT_BANK_ID", BASELINE_EVAL_BANK_ID)

